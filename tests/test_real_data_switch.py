"""票 07 / M2 验收测试：真实数据入库 + 生产数据路径切换。

对应 .scratch/safepass-phase2-tickets/issues/07-real-data-ingest-switch.md
四条勾选：
    1. 真实数据入库完成，manifest 来源标注齐
    2. city_mean 重算回填，评级可复算集跨机器复跑仍绿
    3. prod 数据路径切换（config 数据目录），mock fixture 保留为测试资产
    4. 默认数据集解析顺序：显式传参 > SAFEPASS_DATASET_PATH > config

数据事实（人口估算 / 警区清单 / 阈值）一律从 config 读取或从 manifest
推导——本文件不出现警区号、人口数、阈值字面量（红线 1，fixture 数据除外）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from safepass import config_loader, data_agent, rating_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = REPO_ROOT / "fixtures" / "nypd_real"
REAL_CSV = REAL_DIR / "real_nypd.csv"
REAL_MANIFEST = REAL_DIR / "manifest.json"
MOCK_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

# 合成数据集列（仿真实数据结构：无 population 列）。
_SYNTHETIC_COLUMNS = (
    "complaint_id", "precinct", "borough", "offense_level", "offense_type", "occurred_at", "source",
)


def _write_synthetic_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_SYNTHETIC_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for i, r in enumerate(rows, 1):
            row = {"complaint_id": f"SYN-{i:03d}", "borough": "X", "offense_level": "X", "source": "SOCRATA_test"}
            row.update(r)
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# 1. 真实数据入库完成，manifest 来源标注齐
# ---------------------------------------------------------------------------


def test_real_manifest_provenance_complete():
    manifest = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    for key in (
        "dataset_id",
        "source_url",
        "fetched_at",
        "window_start",
        "window_end_exclusive",
        "precincts",
        "fetched_count",
        "accepted_count",
        "rejected_count",
        "provenance",
    ):
        assert key in manifest, f"manifest 缺来源标注字段：{key}"
    assert manifest["dataset_id"].strip() and manifest["source_url"].strip()
    assert manifest["accepted_count"] + manifest["rejected_count"] == manifest["fetched_count"]


def test_real_csv_matches_manifest_counts_and_window():
    """入库产物自洽：CSV 行数 == manifest accepted_count，记录全在窗口内。"""
    cfg = config_loader.load_config()
    manifest = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    with open(REAL_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == manifest["accepted_count"], "CSV 行数与 manifest accepted_count 不符"
    assert rows, "真实数据集不得为空"
    precincts = {int(r["precinct"]) for r in rows}
    assert precincts == set(cfg.covered_precincts), (
        f"真实数据集警区集合必须与覆盖清单一致：{sorted(precincts)}"
    )
    assert set(manifest["precincts"]) == set(cfg.covered_precincts)


# ---------------------------------------------------------------------------
# 2. city_mean 重算回填 + 真实数据评级 Host 独立复算
# ---------------------------------------------------------------------------


def test_real_dataset_loads_with_config_population_join():
    """真实 CSV 无人口字段：按警区 join config 人口表，聚合数值 Host 复算一致。"""
    cfg = config_loader.load_config()
    manifest = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    records = data_agent.load_dataset(REAL_CSV)
    assert len(records) == manifest["accepted_count"]
    stats_by_precinct = data_agent.aggregate_dataset(records)
    for p, stats in stats_by_precinct.items():
        assert stats.population == cfg.precinct_populations[p], f"P{p} 人口未按 config 表 join"
        assert stats.sources == ("真实 NYPD 数据",), f"P{p} 来源标注应为真实数据"
        # Host 独立复算 per-100k（不引用 data_agent 聚合逻辑）
        assert stats.rate_per_100k == pytest.approx(
            stats.sample_size / cfg.precinct_populations[p] * 100_000
        )


def test_city_mean_recompute_matches_config_backfill():
    """评级可复现性约束：Σcount/Σpop × 1e5 复算值 == config 回填值。"""
    cfg = config_loader.load_config()
    records = data_agent.load_dataset(REAL_CSV)
    mean = data_agent.city_mean_per_100k(records)
    assert cfg.city_mean_per_100k is not None, "票 07 应回填 config city_mean_per_100k"
    assert cfg.city_mean_per_100k == pytest.approx(mean, abs=1e-3), (
        f"config 回填值 {cfg.city_mean_per_100k} 与真实数据集复算 {mean:.4f} 不符"
        "（运行 scripts/recompute_city_mean.py --update-config）"
    )


def test_real_dataset_ratings_match_host_recomputation():
    """真实数据逐警区评级：阈值带由 Host 独立复算，与引擎输出 100% 一致。"""
    cfg = config_loader.load_config()
    records = data_agent.load_dataset(REAL_CSV)
    stats_by_precinct = data_agent.aggregate_dataset(records)
    mean = data_agent.city_mean_per_100k(records)
    gmax = cfg.thresholds.green_max_ratio
    rmin = cfg.thresholds.red_min_ratio
    for p, stats in stats_by_precinct.items():
        ratio = stats.rate_per_100k / mean
        if ratio < gmax:
            expected = "green"
        elif ratio <= rmin:
            expected = "yellow"
        else:
            expected = "red"
        got = rating_engine.rate_precinct(stats, data_agent.rating_config(records, cfg))
        assert got.rating == expected, f"P{p} 真实数据评级与 Host 复算不符"


# ---------------------------------------------------------------------------
# 3. 人口 join 的诚实边界：不编造、缺表 loud failure
# ---------------------------------------------------------------------------


def test_population_column_present_takes_column_over_config(tmp_path):
    """population 列存在（mock/合成）时以列为准——列值与 config 表不同也能区分。"""
    cfg = config_loader.load_config()
    some_precinct = sorted(cfg.covered_precincts)[0]
    path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [{"precinct": some_precinct, "offense_type": "A", "occurred_at": "2026-01-01T10:00:00"}],
    )
    # 手工追加与 config 不同值的 population 列（同构改造）
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    with open(path, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(_SYNTHETIC_COLUMNS) + ["population"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            r["population"] = cfg.precinct_populations[some_precinct] + 1  # 刻意不一致
            writer.writerow(r)
    records = data_agent.load_dataset(path)
    assert records[0].population == cfg.precinct_populations[some_precinct] + 1


def test_missing_population_entry_fails_loudly(tmp_path):
    """警区不在 config 人口表 = 数据集与配置不配套：明确失败，不编造、不静默按零。"""
    cfg = config_loader.load_config()
    unknown_precinct = max(cfg.covered_precincts) + 100  # 确定不在表内
    path = _write_synthetic_csv(
        tmp_path / "syn.csv",
        [{"precinct": unknown_precinct, "offense_type": "A", "occurred_at": "2026-01-01T10:00:00"}],
    )
    with pytest.raises(ValueError, match="人口估算表"):
        data_agent.load_dataset(path)


# ---------------------------------------------------------------------------
# 4. 默认数据路径解析顺序：显式传参 > SAFEPASS_DATASET_PATH > config
# ---------------------------------------------------------------------------


def _synthetic_row(cfg: config_loader.AppConfig) -> dict[str, object]:
    """单条合成记录：警区取覆盖清单首元（保证人口 join 命中 config 表）。"""
    return {
        "precinct": sorted(cfg.covered_precincts)[0],
        "offense_type": "A",
        "occurred_at": "2026-01-01T10:00:00",
    }


def test_explicit_path_beats_env(tmp_path, monkeypatch):
    cfg = config_loader.load_config()
    env_csv = _write_synthetic_csv(tmp_path / "env.csv", [_synthetic_row(cfg)] * 2)
    explicit_csv = _write_synthetic_csv(tmp_path / "explicit.csv", [_synthetic_row(cfg)] * 3)
    monkeypatch.setenv(data_agent.DATASET_PATH_ENV, str(env_csv))
    assert len(data_agent.load_dataset(explicit_csv)) == 3
    assert len(data_agent.load_dataset()) == 2


def test_env_path_beats_config_runtime_path(tmp_path, monkeypatch):
    cfg = config_loader.load_config()
    env_csv = _write_synthetic_csv(tmp_path / "env.csv", [_synthetic_row(cfg)] * 4)
    monkeypatch.setenv(data_agent.DATASET_PATH_ENV, str(env_csv))
    assert len(data_agent.load_dataset()) == 4


def test_config_runtime_path_is_real_dataset(monkeypatch):
    """生产切换落点：无环境变量时默认数据集 = config runtime_dataset_path（真实数据）。"""
    cfg = config_loader.load_config()
    monkeypatch.delenv(data_agent.DATASET_PATH_ENV, raising=False)
    records = data_agent.load_dataset()  # 测试世界外的人口径：config → 真实数据
    manifest = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    assert len(records) == manifest["accepted_count"]
    assert (REPO_ROOT / cfg.data_source.runtime_dataset_path) == REAL_CSV


def test_load_time_range_follows_env_path(tmp_path, monkeypatch):
    cfg = config_loader.load_config()
    env_csv = _write_synthetic_csv(tmp_path / "env.csv", [_synthetic_row(cfg)])
    (tmp_path / "manifest.json").write_text(
        json.dumps({"window_start": "2026-01-01", "window_end_exclusive": "2027-01-01"}),
        encoding="utf-8",
    )
    monkeypatch.setenv(data_agent.DATASET_PATH_ENV, str(env_csv))
    assert data_agent.load_time_range() == "2026-01-01 至 2027-01-01"


def test_conftest_pins_mock_dataset():
    """测试世界不变量（票 07「老测试不破」的根基）：conftest 把默认数据集钉到 mock。"""
    import os

    assert os.environ[data_agent.DATASET_PATH_ENV] == str(MOCK_CSV)
    records = data_agent.load_dataset()
    mock_manifest = json.loads((MOCK_CSV.parent / "manifest.json").read_text(encoding="utf-8"))
    assert len(records) == mock_manifest["total_records"]
