"""真实 NYPD 数据 adapter 运行脚本（issue 05 / M2，spec v2）。

单向管道：Socrata API → 入库校验（safepass.nypd_adapter）→ 落 fixtures/nypd_real/。
手动/月更运行；运行时（产品代码）永不直连外部 API——全仓库唯一发起 Socrata
真实网络的地方就是本脚本的 urllib 调用（录制模式同样走这里）。

用法：
    python scripts/fetch_nypd.py                  # 真实拉取 → 校验 → 落盘
    python scripts/fetch_nypd.py --record-fixture # 真实拉取并录制响应投影到
                                                  # tests/fixtures/socrata_response.json
                                                  #（仅 adapter 消费的列，值原样；
                                                  #  此后测试离线回放，零网络）
    python scripts/fetch_nypd.py --from-fixture   # 用录制 fixture 离线跑通管道（演示/验收）

窗口：以今天为窗尾（不含）的过去 12 个日历月；警区清单与来源配置一律
从 config/app.yaml 读取（config_loader），本脚本不散落警区号/阈值字面量。
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from safepass import config_loader, nypd_adapter  # noqa: E402

MONTHS_PER_WINDOW = 12  # 数据口径：过去 12 个日历月（与数据集 12 个月窗口一致）

# 录制 fixture 时保留的字段投影：adapter 消费的全部 Socrata 列（值原样未改动），
# 其余列（坐标/嫌疑人特征等）不落 fixture——体积约为全量原始响应的 1/8，
# 来源可溯性不受影响（dataset_id + source_url + fetched_at 全记录）。
RECORD_FIELDS = (
    nypd_adapter.FIELD_COMPLAINT_ID,
    nypd_adapter.FIELD_DATE,
    nypd_adapter.FIELD_TIME,
    nypd_adapter.FIELD_PRECINCT,
    nypd_adapter.FIELD_OFFENSE_TYPE,
    nypd_adapter.FIELD_OFFENSE_LEVEL,
    nypd_adapter.FIELD_BOROUGH,
)


def shift_months(day: date, months: int) -> date:
    """date 按月偏移（窗尾回推 12 个月用）；目标月无该日时钳到月末。"""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def build_plan(cfg: config_loader.AppConfig, today: date | None = None) -> nypd_adapter.FetchPlan:
    """拉取计划：窗尾 = 今天（不含）的 12 个日历月；警区 = config 覆盖清单。"""
    if today is None:
        today = date.today()
    window_end = datetime(today.year, today.month, today.day)
    window_start = datetime.combine(shift_months(today, -MONTHS_PER_WINDOW), datetime.min.time())
    dataset_id = cfg.data_source.nypd_dataset_id
    return nypd_adapter.FetchPlan(
        dataset_id=dataset_id,
        source_url=f"{cfg.data_source.socrata_base_url}/{dataset_id}.json",
        window_start=window_start,
        window_end_exclusive=window_end,
        precincts=tuple(sorted(cfg.covered_precincts)),
    )


def make_http_get_json(cfg: config_loader.AppConfig) -> nypd_adapter.HttpGetJson:
    """真实 Socrata HTTP（urllib，stdlib 零新依赖）；超时/来源配置来自 config。"""

    def http_get_json(url: str, params: dict[str, str]) -> list[dict]:
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "safepass-adapter/1.0"})
        with urllib.request.urlopen(req, timeout=cfg.data_source.request_timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return http_get_json


def run_pipeline(
    cfg: config_loader.AppConfig,
    rows: list[dict],
    plan: nypd_adapter.FetchPlan,
    output_dir: Path | None = None,
) -> Path:
    """校验 + 落盘共享路径（真实拉取与 --from-fixture 回放同一条管道）。"""
    source = f"SOCRATA_{plan.dataset_id}"
    result = nypd_adapter.validate_rows(
        rows,
        window_start=plan.window_start,
        window_end_exclusive=plan.window_end_exclusive,
        allowed_precincts=cfg.covered_precincts,
        source=source,
    )
    if output_dir is None:
        output_dir = REPO_ROOT / cfg.data_source.output_dir
    nypd_adapter.write_output(output_dir, plan=plan, result=result, fetched_count=len(rows))
    print(
        f"入库完成：{len(result.accepted)} 条接受 / {len(result.rejected)} 条拒收"
        f"（见 {output_dir}/rejected.csv 与 manifest.json）"
    )
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SafePass 真实 NYPD 数据 adapter（单向管道，手动/月更）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record-fixture", action="store_true", help="真实拉取并录制原始响应供测试离线回放")
    mode.add_argument("--from-fixture", action="store_true", help="用录制 fixture 离线跑通管道")
    args = parser.parse_args(argv)

    cfg = config_loader.get_config()
    plan = build_plan(cfg)

    if args.from_fixture:
        fixture_path = REPO_ROOT / cfg.data_source.recorded_response
        if not fixture_path.exists():
            print(f"录制 fixture 不存在：{fixture_path}（先运行 --record-fixture）", file=sys.stderr)
            return 1
        doc = json.loads(fixture_path.read_text(encoding="utf-8"))
        # 回放必须用录制时的窗口（而非今天），否则历史记录会被误判越窗。
        plan = nypd_adapter.FetchPlan(
            dataset_id=doc["dataset_id"],
            source_url=doc["source_url"],
            window_start=datetime.strptime(doc["window_start"], "%Y-%m-%d"),
            window_end_exclusive=datetime.strptime(doc["window_end_exclusive"], "%Y-%m-%d"),
            precincts=tuple(sorted(cfg.covered_precincts)),
        )
        run_pipeline(cfg, doc["rows"], plan)
        return 0

    http_get_json = make_http_get_json(cfg)
    rows = nypd_adapter.fetch_complaints(http_get_json, plan=plan, page_limit=cfg.data_source.page_limit)

    if args.record_fixture:
        fixture_path = REPO_ROOT / cfg.data_source.recorded_response
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "dataset_id": plan.dataset_id,
            "source_url": plan.source_url,
            "window_start": plan.window_start.strftime("%Y-%m-%d"),
            "window_end_exclusive": plan.window_end_exclusive.strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().strftime(nypd_adapter.TIMESTAMP_FORMAT),
            "row_count": len(rows),
            "row_projection": list(RECORD_FIELDS),
            "projection_note": "rows 仅保留 adapter 消费的 Socrata 列投影，值原样未改动",
            "rows": [{k: r.get(k) for k in RECORD_FIELDS} for r in rows],
        }
        fixture_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已录制 {len(rows)} 行响应投影（字段 {len(RECORD_FIELDS)} 列，值原样）→ {fixture_path}")
        return 0

    run_pipeline(cfg, rows, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
