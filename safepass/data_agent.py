"""数据 Agent（spec D2）。

对模拟 NYPD 数据集按警区聚合，产出结构化统计：
12 个月 per-100k 犯罪率、样本量（真实命中记录数，动态透出）、
犯罪类型 Top 5、白天/夜间案件量分布。聚合全部来自数据集本身，
零 LLM 参与、零硬编码样本量数字。

图表数据边界（spec D9 / AC-022）：charts 全部来自本次聚合；
样本量落入配置中 insufficient_data 强制档时 charts = None（前端不渲染空图）。

昼夜判定（spec issue 03）：由 occurred_at 时间戳字段确定性推导，
night = hour ∈ [NIGHT_START_HOUR, 24) ∪ [0, DAY_START_HOUR)，与 fixture 生成脚本的
is_night 标注规则一致（scripts/generate_fixtures.py）。

来源分层（spec D8）：sources 为合法来源枚举（模拟数据/真实 NYPD 数据/混合），
按命中记录的来源标注字段推导——"MOCK" 前缀版本号视为模拟数据标注
（见 fixtures/nypd/manifest.json 的 dataset_version），模拟与真实并存 → 混合。

12 个月窗口（spec D2）：per-100k 犯罪率定义在数据集的 12 个月窗口上。
落盘数据集旁带 manifest.json（window_start / window_end_exclusive），
load_dataset 校验全部记录落在窗口内，越窗记录 = fixture 损坏，明确失败不静默。
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from safepass import config_loader

# fixtures/nypd/mock_nypd.csv 相对本文件：safepass/data_agent.py -> 项目根/fixtures/nypd/
DEFAULT_DATASET_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "nypd" / "mock_nypd.csv"

SOURCE_MOCK = "模拟数据"
SOURCE_REAL = "真实 NYPD 数据"
SOURCE_MIXED = "混合"
LEGAL_SOURCES = frozenset({SOURCE_MOCK, SOURCE_REAL, SOURCE_MIXED})

# 昼夜边界（小时，含下不含上）：与 fixture 生成脚本的 is_night 规则一致。
NIGHT_START_HOUR = 20
DAY_START_HOUR = 6

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
_REQUIRED_COLUMNS = ("precinct", "offense_type", "occurred_at", "population", "source")


@dataclass(frozen=True)
class CrimeRecord:
    """单条犯罪记录（数据集行的类型化视图）。"""

    precinct: int
    offense_type: str
    occurred_at: datetime
    population: int
    source: str


@dataclass(frozen=True)
class OffenseCount:
    offense_type: str
    count: int


@dataclass(frozen=True)
class DayNight:
    day: int
    night: int


@dataclass(frozen=True)
class PrecinctStats:
    """单警区聚合统计：评级引擎、charts、可信度档复用的同一来源。"""

    precinct: int
    population: int
    sample_size: int
    rate_per_100k: float
    top5_types: tuple[OffenseCount, ...]
    day_night: DayNight
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Charts:
    """图表数据（spec D9）：数值与 PrecinctStats 同源，逐字段相等。"""

    top5_types: tuple[OffenseCount, ...]
    day_night: DayNight


def _load_window(csv_path: Path) -> tuple[datetime, datetime] | None:
    """读取数据集旁 manifest.json 的 12 个月窗口；无 manifest（如测试合成数据集）返回 None。"""
    manifest_path = csv_path.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    start = datetime.strptime(doc["window_start"], "%Y-%m-%d")
    end = datetime.strptime(doc["window_end_exclusive"], "%Y-%m-%d")
    return start, end


def load_dataset(path: str | Path | None = None) -> tuple[CrimeRecord, ...]:
    """读取模拟 NYPD 数据集为类型化记录元组。显式传 path 便于测试合成数据集。

    有 manifest.json 时校验全部记录落在其声明的 12 个月窗口内（含头不含尾），
    越窗记录视为 fixture 损坏，明确失败。
    """
    csv_path = Path(path) if path is not None else DEFAULT_DATASET_PATH
    if not csv_path.exists():
        raise FileNotFoundError(f"数据集不存在：{csv_path}")
    window = _load_window(csv_path)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"数据集缺少必需列：{missing}")
        records = []
        for r in reader:
            occurred_at = datetime.strptime(r["occurred_at"], _TIMESTAMP_FORMAT)
            if window is not None and not (window[0] <= occurred_at < window[1]):
                raise ValueError(
                    f"记录 {r.get('complaint_id', '?')} 时间 {occurred_at} 越出数据集窗口 {window[0]}..{window[1]}"
                )
            records.append(
                CrimeRecord(
                    precinct=int(r["precinct"]),
                    offense_type=r["offense_type"],
                    occurred_at=occurred_at,
                    population=int(r["population"]),
                    source=r["source"],
                )
            )
    if not records:
        raise ValueError(f"数据集为空：{csv_path}")
    return tuple(records)


def load_time_range(path: str | Path | None = None) -> str | None:
    """数据集 12 个月窗口的面向用户描述（契约 time_range 字段）。

    有 manifest.json 时返回「window_start 至 window_end_exclusive」；
    无 manifest（测试合成数据集）返回 None。
    """
    csv_path = Path(path) if path is not None else DEFAULT_DATASET_PATH
    window = _load_window(csv_path)
    if window is None:
        return None
    return f"{window[0]:%Y-%m-%d} 至 {window[1]:%Y-%m-%d}"


def is_night_hour(hour: int) -> bool:
    """由小时确定性判定夜间：[NIGHT_START_HOUR, 24) ∪ [0, DAY_START_HOUR)。"""
    return hour >= NIGHT_START_HOUR or hour < DAY_START_HOUR


def _derive_sources(source_values: Iterable[str]) -> tuple[str, ...]:
    values = set(source_values)
    if not values:
        raise ValueError("来源标注字段为空，无法透出 sources")
    has_mock = any(v.startswith("MOCK") for v in values)
    has_real = any(not v.startswith("MOCK") for v in values)
    if has_mock and has_real:
        return (SOURCE_MIXED,)
    if has_mock:
        return (SOURCE_MOCK,)
    return (SOURCE_REAL,)


def aggregate_precinct(records: Iterable[CrimeRecord], precinct: int) -> PrecinctStats:
    """聚合单警区统计。该警区无任何命中记录时明确失败（不静默返回零值）。"""
    rows = [r for r in records if r.precinct == precinct]
    if not rows:
        raise ValueError(f"警区 {precinct} 无命中记录，无法聚合")
    populations = {r.population for r in rows}
    if len(populations) != 1:
        raise ValueError(f"警区 {precinct} 人口字段不一致：{sorted(populations)}")
    sample_size = len(rows)
    population = populations.pop()
    type_counts = Counter(r.offense_type for r in rows)
    top5 = tuple(
        OffenseCount(offense_type=t, count=c)
        for t, c in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    )
    night = sum(1 for r in rows if is_night_hour(r.occurred_at.hour))
    return PrecinctStats(
        precinct=precinct,
        population=population,
        sample_size=sample_size,
        rate_per_100k=sample_size / population * 100_000,
        top5_types=top5,
        day_night=DayNight(day=sample_size - night, night=night),
        sources=_derive_sources(r.source for r in rows),
    )


def aggregate_dataset(records: Iterable[CrimeRecord]) -> dict[int, PrecinctStats]:
    """聚合数据集中出现的全部警区。按 precinct 排序返回，结果确定性。"""
    by_precinct: dict[int, list[CrimeRecord]] = {}
    for r in records:
        by_precinct.setdefault(r.precinct, []).append(r)
    return {p: aggregate_precinct(by_precinct[p], p) for p in sorted(by_precinct)}


def build_charts(stats: PrecinctStats, cfg: config_loader.AppConfig | None = None) -> Charts | None:
    """图表数据（spec D9 / AC-022）：全部来自本次聚合；样本量落入配置中
    insufficient_data 强制档（读集中配置，不写死条数）时整个图表模块隐藏（None）。

    配置必须声明 insufficient_data 强制档；缺失 = 集中配置损坏，明确失败不兜底。
    """
    if cfg is None:
        cfg = config_loader.get_config()
    tier = next((t for t in cfg.sample_size_tiers if t.rating == "insufficient_data"), None)
    if tier is None:
        raise config_loader.ConfigError("sample_size_tiers 缺少 insufficient_data 强制档（config/app.yaml）")
    upper = tier.max if tier.max is not None else stats.sample_size
    if tier.min <= stats.sample_size <= upper:
        return None
    return Charts(top5_types=stats.top5_types, day_night=stats.day_night)
