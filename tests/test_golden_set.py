"""issue 01 / M1 验收测试：金标 v1（50 条基准查询）fixture 自检 + L1 断言。

对应 .scratch/safepass-phase2-tickets/issues/01-golden-set-v1.md 四条勾选：
    1. 50 条金标落盘 fixture，矩阵覆盖逐项可核对（越界恰 20%；
       低样本 ⚪ + 画像敏感恰 30%；5 警区均有分布）
    2. 每条带 L1 期望断言数据（expect）与 L2 期望标签（must_mention/must_not_claim）
    3. fixture 自检测试进 pytest 基线且全绿（沿用 tests/test_fixtures.py 自检模式）
    4. 无 config/app.yaml 之外的新阈值/档位字面量（评级/可信度期望值全部
       经数据 Agent 聚合 + 评级引擎从 fixture 数据集复算核对）

L1 断言参数化进本文件：打唯一接缝 execute_query（spec v2 Testing Decisions：
L1 只碰返回契约的字段与值，零新增接缝）。全程离线——新查询/越界走
无客户端确定性 fallback 路由；追问轮注入固定路由 stub（模拟 FC 把追问
路由到 follow_up，与 cassette 同一注入模式，下游细分/承接/D12 全确定性）。
L2 judge 不在本票范围（tests/eval/ 另起）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from safepass import config_loader, contracts, data_agent, rating_engine, routing
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query
from safepass.session_state import SessionState

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
# 金标期望建立在 mock 数据集之上（票 07：mock 保留为测试资产）——
# 权威复算显式钉 mock CSV，与管线同一数据路径（评级锚定数据集复算均值）。
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

GOLDEN: dict[str, Any] = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
ENTRIES: list[dict[str, Any]] = GOLDEN["entries"]

FORM_NEW = "new_query"
FORM_COMPARISON_FU = "comparison_followup"
FORM_DETAIL_FU = "detail_followup"
FORM_OOC = "out_of_coverage"
LEGAL_FORMS = {FORM_NEW, FORM_COMPARISON_FU, FORM_DETAIL_FU, FORM_OOC}

SCENARIO_NORMAL = "normal"
SCENARIO_LOW_SAMPLE = "low_sample"
SCENARIO_PROFILE = "profile_sensitive"
LEGAL_SCENARIOS = {SCENARIO_NORMAL, SCENARIO_LOW_SAMPLE, SCENARIO_PROFILE}

FOLLOWUP_FORMS = {FORM_COMPARISON_FU, FORM_DETAIL_FU}


def _entry(entry_id: str) -> dict[str, Any]:
    return next(e for e in ENTRIES if e["id"] == entry_id)


def _ids_where(pred) -> list[str]:
    return [e["id"] for e in ENTRIES if pred(e)]


def _rate(precinct: int) -> rating_engine.RatingResult:
    """权威复算：fixture 数据集聚合 + 评级引擎（与管线同一数据路径）。"""
    records = data_agent.load_dataset(NYPD_CSV)
    stats = data_agent.aggregate_precinct(records, precinct)
    return rating_engine.rate_precinct(stats, data_agent.rating_config(records, config_loader.load_config()))


class _RouteStub:
    """固定路由 stub：模拟 FC 路由把本轮查询路由到指定工具（零 LLM）。

    只用于追问轮——注入后 routing 层单轮 JSON 询问返回固定合法路由，
    与 cassette 回放同一注入模式；追问轮的三维提取在管线内已降为
    确定性 fallback（extraction_client=None），stub 不会被第二次消费。
    """

    def __init__(self, route: str):
        self.route = route
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(
            content=json.dumps(
                {"route": self.route, "degraded_capability": None}, ensure_ascii=False
            )
        )


def _run_entry(entry: dict[str, Any]) -> contracts.ResponseContract:
    """按金标形态打唯一接缝：追问轮先以真实接缝产出上轮结果建会话状态。"""
    context = entry.get("context")
    if context is None:
        return execute_query(entry["query"], profile=entry.get("profile"))
    state = SessionState.from_result(execute_query(context["base_query"]))
    stub = _RouteStub(routing.ROUTE_FOLLOW_UP)
    result = execute_query(
        entry["query"],
        profile=entry.get("profile"),
        session_state=state,
        llm_client=stub,
    )
    assert stub.calls == 1, "追问轮应只消费一次路由调用（三维提取走确定性 fallback）"
    return result


# ---------------------------------------------------------------------------
# 1. 矩阵覆盖自检（越界恰 20%；低样本 ⚪ + 画像敏感恰 30%；5 警区均有分布）
# ---------------------------------------------------------------------------


def test_golden_set_has_50_entries_with_unique_ids():
    assert len(ENTRIES) == 50, f"金标应为 50 条，实际 {len(ENTRIES)}"
    ids = [e["id"] for e in ENTRIES]
    assert len(set(ids)) == len(ids), "金标 id 重复"
    assert all(e["query"].strip() for e in ENTRIES), "查询文本不得为空"


def test_matrix_form_distribution_ooc_exactly_20pct():
    total = len(ENTRIES)
    counts = {f: sum(1 for e in ENTRIES if e["form"] == f) for f in LEGAL_FORMS}
    assert all(c > 0 for c in counts.values()), f"查询形态应有非零分布：{counts}"
    assert counts[FORM_OOC] * 5 == total, (
        f"越界查询应恰占 20%（{total // 5} 条），实际 {counts[FORM_OOC]} 条"
    )


def test_matrix_scenario_distribution_low_sample_plus_profile_exactly_30pct():
    total = len(ENTRIES)
    counts = {s: sum(1 for e in ENTRIES if e["scenario"] == s) for s in LEGAL_SCENARIOS}
    assert all(c > 0 for c in counts.values()), f"数据场景应有非零分布：{counts}"
    special = counts[SCENARIO_LOW_SAMPLE] + counts[SCENARIO_PROFILE]
    assert special * 10 == total * 3, (
        f"低样本 ⚪ + 画像敏感应恰占 30%（{total * 3 // 10} 条），实际 {special} 条"
    )


def test_matrix_all_five_covered_precincts_distributed():
    cfg = config_loader.load_config()
    present: set[int] = set()
    for e in ENTRIES:
        exp = e["expect"]
        if exp["precinct"] is not None:
            present.add(exp["precinct"])
        for a in exp["areas"] or []:
            present.add(a["precinct"])
    missing = set(cfg.covered_precincts) - present
    assert not missing, f"核心警区缺少金标分布：{sorted(missing)}"


# ---------------------------------------------------------------------------
# 2. 结构自检：每条带 L1 期望断言数据与 L2 期望标签
# ---------------------------------------------------------------------------


def test_every_entry_carries_l1_expect_and_l2_labels():
    for e in ENTRIES:
        exp = e.get("expect") or {}
        assert exp.get("type") in ("safety", "comparison", "degraded"), f"{e['id']} 缺合法 L1 type"
        assert isinstance(exp.get("insufficient"), bool), f"{e['id']} 缺 insufficient 标记"
        if exp["type"] == "safety":
            assert isinstance(exp["precinct"], int), f"{e['id']} safety 缺 precinct"
            assert exp["rating"] in contracts.LEGAL_RATINGS, f"{e['id']} 评级非枚举"
            assert isinstance(exp["sample_size"], int), f"{e['id']} 缺样本量期望"
        if exp["type"] == "comparison":
            areas = exp.get("areas")
            assert isinstance(areas, list) and len(areas) >= 2, f"{e['id']} 对比缺 areas"
            for a in areas:
                assert a["rating"] in contracts.LEGAL_RATINGS, f"{e['id']} 对比评级非枚举"
        l2 = e.get("l2") or {}
        for key in ("must_mention", "must_not_claim"):
            assert isinstance(l2.get(key), list), f"{e['id']} 缺 L2 标签 {key}"
            assert all(isinstance(s, str) and s.strip() for s in l2[key]), (
                f"{e['id']} 的 {key} 含空标签"
            )
        assert l2["must_mention"], f"{e['id']} must_mention 不得为空"


def test_entry_shape_consistency_form_scenario_profile():
    """形态/场景/画像/上下文交叉一致：追问必带 context；画像敏感必带画像。"""
    for e in ENTRIES:
        has_context = e.get("context") is not None
        assert has_context == (e["form"] in FOLLOWUP_FORMS), (
            f"{e['id']} context 与形态不一致"
        )
        if has_context:
            assert e["context"].get("base_query"), f"{e['id']} 追问缺 base_query"
        is_profile = e["scenario"] == SCENARIO_PROFILE
        assert (e.get("profile") is not None) == is_profile, (
            f"{e['id']} profile 与数据场景不一致"
        )
        if is_profile:
            assert e["expect"]["time_note"] or e["expect"]["profile_tag"], (
                f"{e['id']} 画像敏感条目应声明可断言的画像效果（time_note/profile_tag）"
            )


# ---------------------------------------------------------------------------
# 3. L1 期望与 fixture 数据集复算核对（期望值不是手填的空中楼阁）
# ---------------------------------------------------------------------------


def test_l1_expectations_match_recomputed_dataset():
    cfg = config_loader.load_config()
    for e in ENTRIES:
        exp = e["expect"]
        if exp["type"] == "safety":
            rated = _rate(exp["precinct"])
            assert rated.rating == exp["rating"], f"{e['id']} 评级期望与复算不符"
            assert rated.confidence == exp["confidence_tier"], f"{e['id']} 可信度期望与复算不符"
            assert rated.sample_size == exp["sample_size"], f"{e['id']} 样本量期望与复算不符"
            assert (exp["rating"] == contracts.RATING_INSUFFICIENT) == exp["insufficient"], (
                f"{e['id']} insufficient 标记与评级不一致"
            )
        elif exp["type"] == "comparison":
            for a in exp["areas"]:
                rated = _rate(a["precinct"])
                assert a["precinct"] in cfg.covered_precincts, f"{e['id']} 对比区域越界"
                assert rated.rating == a["rating"], (
                    f"{e['id']} P{a['precinct']} 评级期望与复算不符"
                )
        else:  # degraded / out_of_coverage
            if exp["precinct"] is not None:
                assert exp["precinct"] not in cfg.covered_precincts, (
                    f"{e['id']} 越界目标的警区竟在覆盖清单内"
                )
            if exp["alternative_present"]:
                assert exp["alternative_precinct"] in cfg.covered_precincts, (
                    f"{e['id']} 替代信息应来自覆盖内警区"
                )


def test_low_sample_scenario_entries_all_touch_insufficient_precinct():
    """低样本 ⚪ 场景条目必须真的涉及 ⚪ 警区（防场景标签漂移）。"""
    for e in ENTRIES:
        if e["scenario"] != SCENARIO_LOW_SAMPLE:
            continue
        exp = e["expect"]
        touched = {exp["precinct"]} | {a["precinct"] for a in exp["areas"] or []}
        touched.discard(None)
        assert any(_rate(p).rating == contracts.RATING_INSUFFICIENT for p in touched), (
            f"{e['id']} 标为低样本 ⚪ 但未涉及任何 ⚪ 警区"
        )


# ---------------------------------------------------------------------------
# 4. L1 断言：金标参数化进 pytest 基线，打唯一接缝 execute_query
# ---------------------------------------------------------------------------

_SAFETY_IDS = _ids_where(
    lambda e: e["expect"]["type"] == "safety" and e["form"] not in FOLLOWUP_FORMS
)
_DETAIL_FU_IDS = _ids_where(
    lambda e: e["expect"]["type"] == "safety" and e["form"] == FORM_DETAIL_FU
)
_COMPARISON_IDS = _ids_where(lambda e: e["expect"]["type"] == "comparison")
_OOC_IDS = _ids_where(lambda e: e["expect"]["type"] == "degraded")


def _check_safety(result: contracts.SafetyQueryResult, entry: dict[str, Any]) -> None:
    exp = entry["expect"]
    cfg = config_loader.load_config()
    assert result.type == "safety"
    assert result.precinct == exp["precinct"], f"{entry['id']} 警区不符"
    assert result.rating == exp["rating"], f"{entry['id']} 评级不符"
    assert result.confidence_tier == exp["confidence_tier"], f"{entry['id']} 可信度不符"
    assert result.sample_size == exp["sample_size"], f"{entry['id']} 样本量不符"
    # ⚪ 档：不给评级数值/可信度/图表，诚实缺口非空
    assert (result.charts is None) == exp["insufficient"], f"{entry['id']} 图表与 ⚪ 标记不符"
    assert (len(result.unknowns) > 0) == exp["insufficient"], f"{entry['id']} unknowns 与 ⚪ 标记不符"
    if exp["insufficient"]:
        assert result.rating_explainable_basis is None, f"{entry['id']} ⚪ 档不得给评级依据"
    # 横切字段：任何形态都带免责声明与画像声明
    assert result.disclaimer and result.profile_notice
    # 画像敏感的合法消费面（ADR-0002）：评级零接触，只断言时间提示与建议排序
    dim_values = [d["value"] for d in result.dimensions]
    assert (cfg.profile.late_night_note in dim_values) == exp["time_note"], (
        f"{entry['id']} 晚归时间提示与期望不符"
    )
    if exp["profile_tag"]:
        assert result.suggestions, f"{entry['id']} 建议列表不得为空"
        assert result.suggestions[0] == cfg.profile.crowd_suggestions[exp["profile_tag"]], (
            f"{entry['id']} 画像建议应排序前置"
        )
    expected_dims = exp["dimensions"] or []
    present_dims = {d["dimension"] for d in result.dimensions}
    assert set(expected_dims) <= present_dims, (
        f"{entry['id']} 缺叠加维度：期望 {expected_dims}，实际 {present_dims}"
    )


@pytest.mark.parametrize("entry_id", _SAFETY_IDS)
def test_l1_new_query_safety(entry_id):
    entry = _entry(entry_id)
    result = _run_entry(entry)
    assert isinstance(result, contracts.SafetyQueryResult)
    _check_safety(result, entry)


@pytest.mark.parametrize("entry_id", _DETAIL_FU_IDS)
def test_l1_detail_followup_safety(entry_id):
    entry = _entry(entry_id)
    result = _run_entry(entry)
    assert isinstance(result, contracts.SafetyQueryResult)
    _check_safety(result, entry)


@pytest.mark.parametrize("entry_id", _COMPARISON_IDS)
def test_l1_comparison(entry_id):
    entry = _entry(entry_id)
    result = _run_entry(entry)
    assert isinstance(result, contracts.ComparisonResult), f"{entry_id} 应为对比契约"
    got = [(a.precinct, a.rating) for a in result.areas]
    assert got == [(a["precinct"], a["rating"]) for a in entry["expect"]["areas"]], (
        f"{entry_id} 对比结果与金标期望不符：{got}"
    )
    assert result.disclaimer, f"{entry_id} 缺免责声明"


@pytest.mark.parametrize("entry_id", _OOC_IDS)
def test_l1_out_of_coverage_degraded(entry_id):
    entry = _entry(entry_id)
    result = _run_entry(entry)
    assert isinstance(result, contracts.DegradedResult), f"{entry_id} 应为降级契约"
    assert result.degraded_capability == contracts.CAPABILITY_OUT_OF_COVERAGE, (
        f"{entry_id} 越界查询必须走 out_of_coverage 诚实降级分支（D12）"
    )
    exp = entry["expect"]
    assert (result.alternative_info is not None) == exp["alternative_present"], (
        f"{entry_id} 替代信息存在性与期望不符"
    )
    if exp["alternative_present"]:
        assert result.alternative_info.precinct == exp["alternative_precinct"], (
            f"{entry_id} 替代信息警区与期望不符"
        )
    # 诚实降级横切：降级说明 + 通用建议 + 紧急资源 + 免责声明
    assert result.message and result.disclaimer
    assert result.general_suggestions, f"{entry_id} 缺通用建议"
    assert result.emergency_resources, f"{entry_id} 缺紧急资源"
    if exp["precinct"] is not None:
        assert str(exp["precinct"]) in result.message, (
            f"{entry_id} 降级说明应如实告知识别出的警区号（不编造、不硬套数据）"
        )
