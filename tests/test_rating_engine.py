"""issue 04 / RALPH T2 验收测试：评级可复算集。

对应 .scratch/safepass-nyc-mvp/issues/04-rating-engine.md 四条勾选：
    1. 对覆盖区逐警区用阈值规则独立复算期望评级，与引擎输出 100% 一致（含 ⚪ 分支）
    2. 边界值用例通过：恰 0.7×、恰 1.3×、恰 10 条、恰 30 条、恰 100 条
    3. 函数签名与实现中无 LLM 客户端、无画像参数
    4. 可信度档随评级同源输出，<10 时评级与可信度均为空/⚪

验收模式（D10）：Host 侧用阈值规则独立复算期望结果与引擎输出比对。
"""

from __future__ import annotations

import inspect
import math
from dataclasses import replace
from pathlib import Path

import pytest

from safepass import config_loader, data_agent, rating_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"


# ---------------------------------------------------------------------------
# Host 侧工具：构造合成统计与定制配置（全部经 config_loader 类型，不写死业务数字）
# ---------------------------------------------------------------------------


def _base_cfg() -> config_loader.AppConfig:
    return config_loader.load_config()


def _cfg_with(**overrides: object) -> config_loader.AppConfig:
    return replace(_base_cfg(), **overrides)


def _stats(sample_size: int, rate_per_100k: float) -> data_agent.PrecinctStats:
    """合成 PrecinctStats：评级引擎唯一消费的字段是 sample_size 与 rate_per_100k。"""
    return data_agent.PrecinctStats(
        precinct=999999,  # 合成占位，引擎不得依赖警区号
        population=1000,
        sample_size=sample_size,
        rate_per_100k=rate_per_100k,
        top5_types=(),
        day_night=data_agent.DayNight(day=sample_size, night=0),
        sources=("模拟数据",),
    )


def _tier_for(n: int, cfg: config_loader.AppConfig) -> config_loader.SampleSizeTier:
    for t in cfg.sample_size_tiers:
        if t.min <= n and (t.max is None or n <= t.max):
            return t
    raise AssertionError(f"样本量 {n} 无匹配档位（配置区间无缝衔接不变量被破坏）")


def _recompute_expected(stats: data_agent.PrecinctStats, cfg: config_loader.AppConfig) -> dict[str, object]:
    """独立复算期望输出：阈值规则 + 样本量门控，不引用 rating_engine 任何逻辑。"""
    tier = _tier_for(stats.sample_size, cfg)
    ratio = stats.rate_per_100k / cfg.city_mean_per_100k
    if tier.rating is not None:  # 强制档（<10 ⚪）：不给评级数值、不给可信度
        return {"rating": tier.rating, "confidence": None, "explanation": None, "ratio": ratio}
    gmax = cfg.thresholds.green_max_ratio
    rmin = cfg.thresholds.red_min_ratio
    if ratio < gmax:
        rating = "green"
    elif ratio <= rmin:
        rating = "yellow"
    else:
        rating = "red"
    explanation = cfg.confidence_explanations[tier.confidence].format(n=stats.sample_size)
    return {"rating": rating, "confidence": tier.confidence, "explanation": explanation, "ratio": ratio}


# ---------------------------------------------------------------------------
# 1. 逐警区独立复算 100% 一致（含 ⚪ 分支）
# ---------------------------------------------------------------------------


def test_rating_matches_independent_recomputation_every_precinct():
    cfg = _base_cfg()
    stats_by_precinct = data_agent.aggregate_dataset(data_agent.load_dataset(NYPD_CSV))
    assert cfg.covered_precincts <= set(stats_by_precinct), "覆盖警区必须在数据集内（T0 义务）"
    for p in sorted(cfg.covered_precincts):
        got = rating_engine.rate_precinct(stats_by_precinct[p], cfg)
        exp = _recompute_expected(stats_by_precinct[p], cfg)
        assert got.rating == exp["rating"], f"P{p} 评级不一致：{got.rating} != {exp['rating']}"
        assert got.confidence == exp["confidence"], f"P{p} 可信度不一致"
        assert got.explanation == exp["explanation"], f"P{p} 可信度解释不一致"
        assert got.ratio_to_city_mean == exp["ratio"], f"P{p} 倍数基准必须精确相等"
        assert got.sample_size == stats_by_precinct[p].sample_size, f"P{p} sample_size 同源"


def test_all_four_rating_branches_covered_by_fixture():
    """fixture（T0 设计义务）必须把 🟢🟡🔴⚪ 四档全部呈现，否则本集不算真覆盖。

    评级带以数据集自身复算均值为锚（票 07：rating_config，与管线同一数据路径）——
    四档覆盖是 fixture 的设计性质，不随 config 全市均值的回填对象变化。
    """
    cfg = _base_cfg()
    records = data_agent.load_dataset(NYPD_CSV)
    stats_by_precinct = data_agent.aggregate_dataset(records)
    rating_cfg = data_agent.rating_config(records, cfg)
    ratings = {rating_engine.rate_precinct(s, rating_cfg).rating for s in stats_by_precinct.values()}
    insufficient = next(t.rating for t in cfg.sample_size_tiers if t.rating is not None)
    assert {"green", "yellow", "red", insufficient} <= ratings, f"fixture 评级档不全：{ratings}"


def test_confidence_tiers_all_present():
    cfg = _base_cfg()
    records = data_agent.load_dataset(NYPD_CSV)
    rating_cfg = data_agent.rating_config(records, cfg)
    results = [rating_engine.rate_precinct(s, rating_cfg) for s in data_agent.aggregate_dataset(records).values()]
    confidences = {r.confidence for r in results if r.confidence is not None}
    assert {t.confidence for t in cfg.sample_size_tiers if t.confidence is not None} <= confidences


# ---------------------------------------------------------------------------
# 2. 边界值用例
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["below", "at", "above"])
def test_boundary_green_max_ratio(side: str):
    """恰 green_max_ratio → 🟡（区间含端点）；严格小于 → 🟢；严格大于 → 🟡。"""
    cfg = _cfg_with(city_mean_per_100k=100.0)
    gmax = cfg.thresholds.green_max_ratio
    pivot = gmax * 100.0  # ratio 恰为 gmax（浮点：x*100/100 精确回到 gmax）
    rate = {"below": math.nextafter(pivot, 0.0), "at": pivot, "above": math.nextafter(pivot, math.inf)}[side]
    result = rating_engine.rate_precinct(_stats(sample_size=100, rate_per_100k=rate), cfg)
    expected = {"below": "green", "at": "yellow", "above": "yellow"}[side]
    assert result.rating == expected, f"ratio={result.ratio_to_city_mean} 侧={side}"


@pytest.mark.parametrize("side", ["below", "at", "above"])
def test_boundary_red_min_ratio(side: str):
    """恰 red_min_ratio → 🟡；严格小于 → 🟡；严格大于 → 🔴。"""
    cfg = _cfg_with(city_mean_per_100k=100.0)
    rmin = cfg.thresholds.red_min_ratio
    pivot = rmin * 100.0
    rate = {"below": math.nextafter(pivot, 0.0), "at": pivot, "above": math.nextafter(pivot, math.inf)}[side]
    result = rating_engine.rate_precinct(_stats(sample_size=100, rate_per_100k=rate), cfg)
    expected = {"below": "yellow", "at": "yellow", "above": "red"}[side]
    assert result.rating == expected, f"ratio={result.ratio_to_city_mean} 侧={side}"


def _sample_boundary_cases() -> list[tuple[int, str | None]]:
    """从配置档位推导边界用例（不写死 10/30/100）：每档首数与前一数。"""
    cfg = _base_cfg()
    cases: list[tuple[int, str | None]] = []
    tiers = cfg.sample_size_tiers
    for i, t in enumerate(tiers):
        cases.append((t.min, t.confidence if t.rating is None else None))
        if i > 0:
            cases.append((t.min - 1, tiers[i - 1].confidence if tiers[i - 1].rating is None else None))
    return cases


@pytest.mark.parametrize("n,expected_confidence", _sample_boundary_cases())
def test_boundary_sample_size_tiers(n: int, expected_confidence: str | None):
    """恰每档首数/前一数：可信度档与强制 ⚪ 分支随配置档位精确切换。"""
    cfg = _base_cfg()
    tier = _tier_for(n, cfg)
    result = rating_engine.rate_precinct(_stats(sample_size=n, rate_per_100k=cfg.city_mean_per_100k), cfg)
    if tier.rating is not None:
        assert result.rating == tier.rating, f"n={n} 强制档未生效"
        assert result.confidence is None, f"n={n} ⚪ 档不得给可信度"
        assert result.explanation is None, f"n={n} ⚪ 档不得给解释"
    else:
        assert result.rating == "yellow", f"n={n} 恰市均值应为 🟡"
        assert result.confidence == expected_confidence, f"n={n} 可信度档不一致"


# ---------------------------------------------------------------------------
# 3. 签名与实现：零 LLM、零画像
# ---------------------------------------------------------------------------


def test_signature_has_no_llm_client_and_no_profile():
    sig = inspect.signature(rating_engine.rate_precinct)
    param_names = set(sig.parameters)
    assert "profile" not in param_names, "评级引擎不得接受画像参数（ADR-0002）"
    assert "llm_client" not in param_names, "评级引擎不得接受 LLM 客户端"
    for p in sig.parameters.values():
        assert "LLM" not in str(p.annotation), f"参数 {p.name} 注解含 LLM 类型"


def test_implementation_uses_no_llm_and_no_hardcoded_thresholds():
    text = (REPO_ROOT / "safepass" / "rating_engine.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "llm_client", "requests", "httpx"):
        assert banned not in text, f"评级引擎出现禁用依赖：{banned}"
    for banned in ("0.7", "1.3"):
        assert banned not in text, f"评级引擎出现硬编码阈值：{banned}"


# ---------------------------------------------------------------------------
# 4. 可信度与评级同源；⚪ 分支不给评级数值/可信度
# ---------------------------------------------------------------------------


def test_explanation_uses_config_template_with_dynamic_sample_size():
    cfg = _base_cfg()
    n = next(t.min for t in cfg.sample_size_tiers if t.confidence == "HIGH")
    result = rating_engine.rate_precinct(_stats(sample_size=n, rate_per_100k=cfg.city_mean_per_100k), cfg)
    template = cfg.confidence_explanations["HIGH"]
    assert result.explanation == template.format(n=n)
    assert str(n) in result.explanation, "解释必须动态透出真实命中数"


def test_explanation_changes_with_sample_size_same_rating():
    """同一评级带内，解释文案随 n 变化（动态透出，非固定字符串）。"""
    cfg = _base_cfg()
    low_tier = next(t for t in cfg.sample_size_tiers if t.confidence == "LOW")
    results = [
        rating_engine.rate_precinct(_stats(sample_size=n, rate_per_100k=cfg.city_mean_per_100k), cfg)
        for n in (low_tier.min, low_tier.min + 1)
    ]
    assert all(r.rating == "yellow" for r in results)
    assert results[0].explanation != results[1].explanation


def test_insufficient_branch_rating_and_confidence_empty():
    cfg = _base_cfg()
    insufficient = next(t for t in cfg.sample_size_tiers if t.rating is not None)
    assert insufficient.min == 0, "强制档必须从 0 开始（config_loader 不变量）"
    n = insufficient.max  # 该档最大样本数（配置读取，不写死 9）
    result = rating_engine.rate_precinct(_stats(sample_size=n, rate_per_100k=10_000.0), cfg)
    assert result.rating == insufficient.rating, "即使比率再高，<10 也必须强制 ⚪"
    assert result.confidence is None
    assert result.explanation is None


# ---------------------------------------------------------------------------
# 5. 明确失败：配置前提缺失不兜底
# ---------------------------------------------------------------------------


def test_city_mean_missing_fails_loudly():
    cfg = _cfg_with(city_mean_per_100k=None)
    with pytest.raises(config_loader.ConfigError):
        rating_engine.rate_precinct(_stats(sample_size=100, rate_per_100k=188.0), cfg)


def test_explanation_template_missing_fails_loudly():
    cfg = _base_cfg()
    broken = _cfg_with(confidence_explanations={})  # 空映射被 config_loader 拒绝，这里直接构造坏配置
    with pytest.raises(config_loader.ConfigError):
        rating_engine.rate_precinct(_stats(sample_size=100, rate_per_100k=cfg.city_mean_per_100k), broken)


# ---------------------------------------------------------------------------
# 6. 配置↔spec 一致性（spec D4 数字的唯一机器锚点）
# ---------------------------------------------------------------------------
#
# 边界用例从配置推导（上面各 test_boundary_*），若配置本身偏离 spec D4，
# 推导式测试仍会全绿——本条把 spec D4 的数字直接钉死，作为配置↔spec 的
# 一致性校验（grep 审查只覆盖产品代码，不覆盖配置文件内容）。


def test_config_values_match_spec_d4():
    cfg = _base_cfg()
    # spec D4: "阈值系数：green < 0.7× 市均值、yellow 0.7–1.3×、red > 1.3×"
    assert cfg.thresholds.green_max_ratio == 0.7
    assert cfg.thresholds.red_min_ratio == 1.3
    # spec D4: "<10 → ⚪；10–29 → LOW；30–99 → MODERATE；≥100 → HIGH"
    tiers = [(t.min, t.max, t.rating, t.confidence) for t in cfg.sample_size_tiers]
    assert tiers == [
        (0, 9, "insufficient_data", None),
        (10, 29, None, "LOW"),
        (30, 99, None, "MODERATE"),
        (100, None, None, "HIGH"),
    ]
    # spec D4: 可信度解释模板为非学术术语且含 {n} 占位
    for name in ("LOW", "MODERATE", "HIGH"):
        template = cfg.confidence_explanations[name]
        assert "{n}" in template
        assert "记录" in template
