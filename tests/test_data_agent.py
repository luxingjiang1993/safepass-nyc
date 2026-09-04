"""issue 03 / RALPH T1 验收测试：数据 Agent 聚合集。

对应 .scratch/safepass-nyc-mvp/issues/03-data-agent-aggregation.md 四条勾选：
    1. 给定固定模拟数据集，逐警区断言聚合数值精确相等（Host 独立复算比对，见 D10 验收模式）
    2. sample_size 等于数据集真实命中条数（测试断言与独立计数一致，无硬编码数字）
    3. 白天/夜间案件量分布可由时间戳字段确定性判定
    4. sources 字段非空且含合法来源枚举（模拟数据/真实 NYPD 数据/混合）

附：AC-022 图表数据边界 —— charts 数值 = 本次聚合输出；样本量不足档 charts = None。
"""

from __future__ import annotations

import csv
import dataclasses
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from safepass import config_loader, data_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
MANIFEST = REPO_ROOT / "fixtures" / "nypd" / "manifest.json"

LEGAL_SOURCES = {"模拟数据", "真实 NYPD 数据", "混合"}


# ---------------------------------------------------------------------------
# Host 侧独立复算（不引用 safepass.data_agent 的任何聚合逻辑）
# ---------------------------------------------------------------------------


def _read_rows(path: Path = NYPD_CSV) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _recompute(rows: list[dict[str, str]]) -> dict[int, dict[str, object]]:
    """独立复算：逐警区计数 / 人口 / per-100k / top5（-count, type 字典序）/ 昼夜分布。"""
    stats: dict[int, dict[str, object]] = {}
    for r in rows:
        p = int(r["precinct"])
        hour = datetime.strptime(r["occurred_at"], "%Y-%m-%dT%H:%M:%S").hour
        s = stats.setdefault(
            p,
            {"count": 0, "pop": int(r["population"]), "types": Counter(), "day": 0, "night": 0, "sources": set()},
        )
        assert int(r["population"]) == s["pop"], f"P{p} 人口字段不一致"
        s["count"] += 1
        s["types"][r["offense_type"]] += 1
        if hour >= 20 or hour < 6:
            s["night"] += 1
        else:
            s["day"] += 1
        s["sources"].add(r["source"])
    for p, s in stats.items():
        s["top5"] = sorted(s["types"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        s["rate"] = s["count"] / s["pop"] * 100_000
    return stats


def _write_synthetic_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    """合成数据集：字段结构与 fixture 一致，测试完全掌控每条记录。"""
    fieldnames = ["complaint_id", "precinct", "borough", "offense_level", "offense_type",
                  "occurred_at", "hour", "is_night", "population", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for i, r in enumerate(rows, 1):
            row = {"complaint_id": f"SYN-{i:03d}", "borough": "X", "offense_level": "X",
                   "population": 1000, "source": "MOCK_SYNTHETIC"}
            row.update(r)
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# 1. 逐警区聚合数值精确相等
# ---------------------------------------------------------------------------


def test_aggregated_stats_match_independent_recomputation_exactly():
    rows = _read_rows()
    expected = _recompute(rows)
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    assert set(actual) == set(expected), "聚合遗漏/多出警区"
    for p, exp in expected.items():
        got = actual[p]
        assert got.sample_size == exp["count"], f"P{p} sample_size"
        assert got.population == exp["pop"], f"P{p} population"
        assert got.rate_per_100k == exp["rate"], f"P{p} rate 必须精确相等"
        assert [(o.offense_type, o.count) for o in got.top5_types] == exp["top5"], f"P{p} top5"
        assert (got.day_night.day, got.day_night.night) == (exp["day"], exp["night"]), f"P{p} day_night"


def test_rate_per_100k_matches_manifest():
    """per-100k 与 manifest（T0 落盘独立产物）逐警区一致（manifest 保留 4 位小数）。"""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    for p_str, entry in manifest["precincts"].items():
        got = actual[int(p_str)]
        assert got.sample_size == entry["records"], f"P{p_str} sample_size vs manifest"
        assert got.rate_per_100k == pytest.approx(entry["rate_per_100k"], abs=5e-5), f"P{p_str} rate vs manifest"


# ---------------------------------------------------------------------------
# 2. sample_size = 真实命中条数，无硬编码数字
# ---------------------------------------------------------------------------


def test_sample_size_equals_true_hit_count_dynamically():
    rows = _read_rows()
    expected = _recompute(rows)
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    total = 0
    for p, exp in expected.items():
        assert actual[p].sample_size == exp["count"], f"P{p} sample_size 与独立计数不一致"
        total += actual[p].sample_size
    assert total == len(rows), "sample_size 总和必须等于数据集真实总条数"
    assert len(rows) == json.loads(MANIFEST.read_text(encoding="utf-8"))["total_records"]


def test_aggregate_stats_contain_no_hardcoded_sample_numbers():
    """聚合实现中样本量必须来自计数，不得出现写死的档位/记录数。"""
    text = (REPO_ROOT / "safepass" / "data_agent.py").read_text(encoding="utf-8")
    for banned in ("1280", "1_280", "MOCK-000001"):
        assert banned not in text, f"聚合实现出现硬编码数字：{banned}"


# ---------------------------------------------------------------------------
# 3. 白天/夜间由时间戳字段确定性判定
# ---------------------------------------------------------------------------


def test_day_night_derived_from_timestamp_not_flag_column(tmp_path):
    """is_night 列与 occurred_at 矛盾时，以时间戳为准（小时 ∈ [6,20) 为白天）。"""
    path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T05:59:59", "hour": 5, "is_night": 0},
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T06:00:00", "hour": 6, "is_night": 1},
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T19:59:59", "hour": 19, "is_night": 1},
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T20:00:00", "hour": 20, "is_night": 0},
        ],
    )
    stats = data_agent.aggregate_dataset(data_agent.load_dataset(path))[1]
    assert (stats.day_night.day, stats.day_night.night) == (2, 2)
    assert stats.day_night.day + stats.day_night.night == stats.sample_size


def test_fixture_day_night_consistent_with_timestamp_rule():
    """固定数据集的 is_night 标注列须与时间戳规则自洽（fixture 不变量）。"""
    for r in _read_rows():
        hour = datetime.strptime(r["occurred_at"], "%Y-%m-%dT%H:%M:%S").hour
        expected_flag = 1 if (hour >= 20 or hour < 6) else 0
        assert int(r["is_night"]) == expected_flag, f"{r['complaint_id']} is_night 与时间戳矛盾"


# ---------------------------------------------------------------------------
# 4. sources 非空且含合法来源枚举
# ---------------------------------------------------------------------------


def test_sources_nonempty_and_legal_enum_on_fixture():
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    for p, stats in actual.items():
        assert stats.sources, f"P{p} sources 不能为空"
        assert set(stats.sources) <= LEGAL_SOURCES, f"P{p} sources 含非法枚举：{stats.sources}"
    # 纯模拟数据集 → 透出"模拟数据"
    assert all(stats.sources == ("模拟数据",) for stats in actual.values())


def test_sources_mixed_when_mock_and_real_records_combined(tmp_path):
    path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T10:00:00", "source": "MOCK_SYNTHETIC"},
            {"precinct": 1, "offense_type": "B", "occurred_at": "2026-01-02T10:00:00", "source": "NYPD_REAL_V9"},
        ],
    )
    stats = data_agent.aggregate_dataset(data_agent.load_dataset(path))[1]
    assert stats.sources == ("混合",)


def test_sources_real_only_when_no_mock_records(tmp_path):
    path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [{"precinct": 1, "offense_type": "A", "occurred_at": "2026-01-01T10:00:00", "source": "NYPD_REAL_V9"}],
    )
    stats = data_agent.aggregate_dataset(data_agent.load_dataset(path))[1]
    assert stats.sources == ("真实 NYPD 数据",)


# ---------------------------------------------------------------------------
# 5. Top 5 结构与确定性并列处理
# ---------------------------------------------------------------------------


def test_top5_cutoff_and_tiebreak_deterministic(tmp_path):
    """6 种类型、尾部三类型计数并列 → top5 按 (-count, 类型字典序) 取前 5。"""
    rows = [
        ("A", 3), ("B", 3), ("C", 2), ("D", 1), ("E", 1), ("F", 1),
    ]
    records = []
    for t, n in rows:
        for k in range(n):
            records.append({
                "precinct": 1, "offense_type": t,
                "occurred_at": f"2026-01-{k + 1:02d}T10:00:00",
            })
    path = _write_synthetic_csv(tmp_path / "syn.csv", records)
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(path), 1)
    assert [(o.offense_type, o.count) for o in stats.top5_types] == [
        ("A", 3), ("B", 3), ("C", 2), ("D", 1), ("E", 1),
    ]


# ---------------------------------------------------------------------------
# 6. AC-022 图表数据边界：charts = 聚合输出；不足档 charts = None
# ---------------------------------------------------------------------------


def _insufficient_tier(cfg: config_loader.AppConfig) -> config_loader.SampleSizeTier:
    tier = next((t for t in cfg.sample_size_tiers if t.rating == "insufficient_data"), None)
    assert tier is not None, "配置必须声明 insufficient_data 强制档"
    return tier


def test_charts_null_for_insufficient_sample_tier():
    cfg = config_loader.load_config()
    tier = _insufficient_tier(cfg)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # 动态找出落在不足档的警区（测试不写死警区号与条数）
    small = [int(p) for p, e in manifest["precincts"].items()
             if tier.min <= e["records"] <= tier.max]
    assert small, "fixture 必须含样本量不足档案例"
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    for p in small:
        assert actual[p].sample_size <= tier.max
        assert data_agent.build_charts(actual[p], cfg) is None, f"P{p} 不足档必须 charts=null"


def test_charts_equal_aggregation_output_for_sufficient_precincts():
    cfg = config_loader.load_config()
    tier = _insufficient_tier(cfg)
    actual = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    sufficient = [p for p, s in actual.items() if s.sample_size > tier.max]
    assert sufficient, "fixture 必须含足够样本量案例"
    for p in sufficient:
        charts = data_agent.build_charts(actual[p], cfg)
        assert charts is not None, f"P{p} 足够样本量不得隐藏图表"
        assert charts.top5_types == actual[p].top5_types, f"P{p} charts.top5 必须来自同一次聚合"
        assert charts.day_night == actual[p].day_night, f"P{p} charts.day_night 必须来自同一次聚合"


# ---------------------------------------------------------------------------
# 7. 明确失败：聚合实现零 LLM、零编造
# ---------------------------------------------------------------------------


def test_data_agent_uses_no_llm():
    text = (REPO_ROOT / "safepass" / "data_agent.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "llm_client"):
        assert banned not in text, f"数据 Agent 不得依赖 LLM：{banned}"


def test_aggregate_precinct_with_no_records_fails_loudly():
    with pytest.raises(ValueError):
        data_agent.aggregate_precinct((), 1)


# ---------------------------------------------------------------------------
# 8. 12 个月窗口（spec D2）：有 manifest 时越窗记录明确失败
# ---------------------------------------------------------------------------


def test_out_of_window_records_fail_loudly(tmp_path):
    """带 manifest.json 的数据集：越出 12 个月窗口的记录 = fixture 损坏，明确拒绝。"""
    csv_path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [{"precinct": 1, "offense_type": "A", "occurred_at": "2026-07-01T00:00:00"}],  # 恰为窗口尾（不含）
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"window_start": "2025-07-01", "window_end_exclusive": "2026-07-01"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="越出数据集窗口"):
        data_agent.load_dataset(csv_path)


def test_in_window_records_load_ok_and_window_is_12_months(tmp_path):
    csv_path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [
            {"precinct": 1, "offense_type": "A", "occurred_at": "2025-07-01T00:00:00"},  # 含头
            {"precinct": 1, "offense_type": "A", "occurred_at": "2026-06-30T23:59:59"},  # 不含尾
        ],
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"window_start": "2025-07-01", "window_end_exclusive": "2026-07-01"}),
        encoding="utf-8",
    )
    records = data_agent.load_dataset(csv_path)
    assert len(records) == 2


def test_committed_fixture_loads_within_its_manifest_window():
    """落盘 fixture 必须全部落在自己 manifest 声明的 12 个月窗口内（不变量）。"""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = data_agent.load_dataset(NYPD_CSV)  # 窗口校验在此完成，越窗即抛错
    assert len(records) == manifest["total_records"]


def test_build_charts_fails_loudly_when_config_lacks_insufficient_tier():
    """集中配置缺 insufficient_data 强制档 = 配置损坏，charts 隐藏规则无法判定，明确失败。"""
    cfg = config_loader.load_config()
    patched = dataclasses.replace(
        cfg,
        sample_size_tiers=tuple(
            config_loader.SampleSizeTier(t.min, t.max, None, t.confidence) for t in cfg.sample_size_tiers
        ),
    )
    stats = next(iter(data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV)).values()))
    with pytest.raises(config_loader.ConfigError):
        data_agent.build_charts(stats, patched)
