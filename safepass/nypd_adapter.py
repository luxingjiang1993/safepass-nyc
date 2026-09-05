"""真实 NYPD 数据 adapter 核心（issue 05 / M2，spec v2）。

单向管道：Socrata API → 入库校验 → 落 `fixtures/nypd_real/`。
本模块是纯函数核心：HTTP 层可注入（测试用录制 fixture 回放，零真实调用），
真实网络只存在于 scripts/fetch_nypd.py（手动/月更运行）。
运行时（产品代码）永不直连外部 API。

入库校验（spec v2 M2：不合格即拒收并报告，脏数据不静默污染评级）：
1. 缺字段——cmplnt_num / cmplnt_fr_dt / cmplnt_fr_tm / addr_pct_cd / ofns_desc
   缺失、空串、"(null)" 占位（Socrata 对空值的字符串化）或日期/时间/警区号
   无法解析；
2. 时间越界——occurred_at 不在本次拉取的 12 个月窗口 [start, end) 内；
3. 警区不在清单——addr_pct_cd 不在 config coverage.precincts（警区号唯一事实源）。

诚实护栏：真实数据没有人口字段，绝不编造（population 是 mock 元数据，
真实数据的人口口径由后续入库切换票另行处理）；被拒记录原样落
rejected.csv（含原始 JSON 与拒收原因），manifest.json 记录来源与拒收统计。

拒收类别名（REJECT_*）是稳定契约（落盘与测试共用），不是业务阈值。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

# Socrata 行内空值的字符串化占位（真实响应里 parks_nm 等字段为 "(null)"）。
_SOCRATA_NULL = "(null)"

# 入库 CSV 的列（与 fixtures/nypd/mock_nypd.csv 同构子集；真实数据无 population，
# 不编造）。键序即列序。
OUTPUT_COLUMNS = ("complaint_id", "precinct", "borough", "offense_level", "offense_type", "occurred_at", "source")

# 拒收类别（落盘 rejected.csv 的 reason 字段与测试断言共用同一字符串）。
REJECT_MISSING_FIELD = "missing_field"
REJECT_OUT_OF_WINDOW = "out_of_window"
REJECT_PRECINCT_NOT_ALLOWED = "precinct_not_allowed"

# Socrata 响应行 → 本地字段的映射（Socrata 列名单一事实源在此）。
FIELD_COMPLAINT_ID = "cmplnt_num"
FIELD_DATE = "cmplnt_fr_dt"
FIELD_TIME = "cmplnt_fr_tm"
FIELD_PRECINCT = "addr_pct_cd"
FIELD_OFFENSE_TYPE = "ofns_desc"
FIELD_OFFENSE_LEVEL = "law_cat_cd"
FIELD_BOROUGH = "boro_nm"

# 入库校验的必需字段（缺/空/不可解析 → missing_field 拒收）。
_REQUIRED_FIELDS = (
    FIELD_COMPLAINT_ID,
    FIELD_DATE,
    FIELD_TIME,
    FIELD_PRECINCT,
    FIELD_OFFENSE_TYPE,
)

_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
_TIME_FORMAT = "%H:%M:%S"

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True)
class RealComplaint:
    """一条通过校验的真实 NYPD 记录（入库 CSV 行的类型化视图）。"""

    complaint_id: str
    precinct: int
    borough: str
    offense_level: str
    offense_type: str
    occurred_at: datetime
    source: str


@dataclass(frozen=True)
class RejectedRow:
    """一条被拒记录：拒收类别 + 人类可读原因 + 原始行（诚实报告，不静默丢弃）。"""

    reason: str
    detail: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class ValidationResult:
    """校验结果：accepted + rejected 并集 = 输入全集（无静默丢失）。"""

    accepted: tuple[RealComplaint, ...]
    rejected: tuple[RejectedRow, ...]


@dataclass(frozen=True)
class FetchPlan:
    """一次拉取的完整计划（落 manifest 的可复现性元数据）。"""

    dataset_id: str
    source_url: str
    window_start: datetime
    window_end_exclusive: datetime
    precincts: tuple[int, ...]


# HTTP 注入接缝：url + params(dict[str, str]) → 解析后的 JSON（Socrata 行列表）。
HttpGetJson = Callable[[str, dict[str, str]], list[dict[str, Any]]]


def _is_blank(value: Any) -> bool:
    """Socrata 空值判定：None、空串、空白串、"(null)" 占位一律视为缺失。"""
    if value is None:
        return True
    s = str(value).strip()
    return not s or s == _SOCRATA_NULL


def _parse_socrata_date(value: Any) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_socrata_time(value: Any) -> tuple[int, int, int] | None:
    """解析 Socrata 时间 "HH:MM:SS" 为 (hour, minute, second)；不可解析返回 None。"""
    try:
        parsed = datetime.strptime(str(value).strip(), _TIME_FORMAT)
    except ValueError:
        return None
    return parsed.hour, parsed.minute, parsed.second


def validate_rows(
    rows: Iterable[dict[str, Any]],
    *,
    window_start: datetime,
    window_end_exclusive: datetime,
    allowed_precincts: frozenset[int],
    source: str,
) -> ValidationResult:
    """入库前校验（三类拒收：缺字段 / 时间越界 / 警区不在清单）。

    校验顺序确定性：先缺字段，再时间越界，再警区——一条记录只给一个拒收原因。
    accepted/rejected 并集 = 输入全集。
    """
    accepted: list[RealComplaint] = []
    rejected: list[RejectedRow] = []
    for row in rows:
        missing = [f for f in _REQUIRED_FIELDS if _is_blank(row.get(f))]
        if missing:
            rejected.append(
                RejectedRow(REJECT_MISSING_FIELD, f"缺字段或占位空值：{missing}", dict(row))
            )
            continue
        date_part = _parse_socrata_date(row[FIELD_DATE])
        time_part = _parse_socrata_time(row[FIELD_TIME])
        if date_part is None or time_part is None:
            rejected.append(
                RejectedRow(
                    REJECT_MISSING_FIELD,
                    f"时间不可解析：{row[FIELD_DATE]!r} {row[FIELD_TIME]!r}",
                    dict(row),
                )
            )
            continue
        occurred_at = date_part.replace(hour=time_part[0], minute=time_part[1], second=time_part[2])
        if not (window_start <= occurred_at < window_end_exclusive):
            rejected.append(
                RejectedRow(
                    REJECT_OUT_OF_WINDOW,
                    f"{occurred_at} 越出窗口 {window_start}..{window_end_exclusive}",
                    dict(row),
                )
            )
            continue
        try:
            precinct = int(str(row[FIELD_PRECINCT]).strip())
        except ValueError:
            rejected.append(
                RejectedRow(
                    REJECT_MISSING_FIELD,
                    f"警区号缺失或不可解析：{row[FIELD_PRECINCT]!r}",
                    dict(row),
                )
            )
            continue
        if precinct not in allowed_precincts:
            rejected.append(
                RejectedRow(
                    REJECT_PRECINCT_NOT_ALLOWED,
                    f"警区 {precinct} 不在覆盖清单",
                    dict(row),
                )
            )
            continue
        accepted.append(
            RealComplaint(
                complaint_id=str(row[FIELD_COMPLAINT_ID]).strip(),
                precinct=precinct,
                borough="" if _is_blank(row.get(FIELD_BOROUGH)) else str(row[FIELD_BOROUGH]).strip(),
                offense_level=(
                    "" if _is_blank(row.get(FIELD_OFFENSE_LEVEL)) else str(row[FIELD_OFFENSE_LEVEL]).strip()
                ),
                offense_type=str(row[FIELD_OFFENSE_TYPE]).strip(),
                occurred_at=occurred_at,
                source=source,
            )
        )
    return ValidationResult(accepted=tuple(accepted), rejected=tuple(rejected))


def fetch_complaints(
    http_get_json: HttpGetJson,
    *,
    plan: FetchPlan,
    page_limit: int,
) -> list[dict[str, Any]]:
    """按警区分页拉取 Socrata 原始行。HTTP 完全经注入的 http_get_json（可测接缝）。

    SoQL 过滤：addr_pct_cd = '<p>' AND cmplnt_fr_dt >= start AND cmplnt_fr_dt < end
    （与入库校验同为 [start, end) 半开区间；SoQL between 双闭，会多拉窗尾一行）；
    分页：$limit=page_limit，$offset 递增，取到返回行数 < page_limit 为止。
    """
    if page_limit <= 0:
        raise ValueError("page_limit 必须为正")
    rows: list[dict[str, Any]] = []
    start = plan.window_start.strftime("%Y-%m-%dT%H:%M:%S")
    end = plan.window_end_exclusive.strftime("%Y-%m-%dT%H:%M:%S")
    for precinct in plan.precincts:
        offset = 0
        while True:
            params = {
                "$where": (
                    f"{FIELD_PRECINCT} = '{precinct}' "
                    f"AND {FIELD_DATE} >= '{start}' AND {FIELD_DATE} < '{end}'"
                ),
                "$order": FIELD_COMPLAINT_ID,
                "$limit": str(page_limit),
                "$offset": str(offset),
            }
            page = http_get_json(plan.source_url, params)
            if not isinstance(page, list):
                raise ValueError(f"Socrata 响应不是行列表：{type(page).__name__}")
            rows.extend(page)
            if len(page) < page_limit:
                break
            offset += page_limit
    return rows


def write_output(
    output_dir: Path,
    *,
    plan: FetchPlan,
    result: ValidationResult,
    fetched_count: int,
) -> Path:
    """落盘入库产物：real_nypd.csv + rejected.csv + manifest.json（来源标注齐）。

    manifest 记录来源 URL、数据集 ID、窗口、警区清单与拒收统计——
    resource-manifest §A「来源可溯」诚实护栏的机器可读形态。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "real_nypd.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(OUTPUT_COLUMNS))
        writer.writeheader()
        for r in result.accepted:
            writer.writerow(
                {
                    "complaint_id": r.complaint_id,
                    "precinct": r.precinct,
                    "borough": r.borough,
                    "offense_level": r.offense_level,
                    "offense_type": r.offense_type,
                    "occurred_at": r.occurred_at.strftime(TIMESTAMP_FORMAT),
                    "source": r.source,
                }
            )

    rejected_path = output_dir / "rejected.csv"
    with open(rejected_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["reason", "detail", "raw_json"])
        writer.writeheader()
        for r in result.rejected:
            writer.writerow({"reason": r.reason, "detail": r.detail, "raw_json": json.dumps(r.raw, ensure_ascii=False)})

    rejection_counts: dict[str, int] = {}
    for r in result.rejected:
        rejection_counts[r.reason] = rejection_counts.get(r.reason, 0) + 1
    manifest = {
        "dataset_id": plan.dataset_id,
        "source_url": plan.source_url,
        "fetched_at": datetime.now().strftime(TIMESTAMP_FORMAT),
        "window_start": plan.window_start.strftime("%Y-%m-%d"),
        "window_end_exclusive": plan.window_end_exclusive.strftime("%Y-%m-%d"),
        "precincts": list(plan.precincts),
        "fetched_count": fetched_count,
        "accepted_count": len(result.accepted),
        "rejected_count": len(result.rejected),
        "rejection_counts": rejection_counts,
        "rejected_report": rejected_path.name,
        "provenance": (
            f"NYC Open Data (Socrata) dataset {plan.dataset_id}; "
            f"adapter 单向管道 scripts/fetch_nypd.py；运行时零外部调用"
        ),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_dir
