"""issue 08 / RALPH T6 验收测试：追问集（spec D6 / F8 / F3-5 / AC-021）。

对应 .scratch/safepass-nyc-mvp/issues/08-follow-up-context.md 四条勾选：
    1. 对比追问/细节追问承接正确（地点、评级、维度叠加均断言）
    2. 换地点/换话题不复用上轮结构化结果，重置明确（follow_up 路由失效、走新查询流程）
    3. 追问越界走单边越界规则（F3-5）：越界侧只有 out_of_coverage 说明、无对比结论字段
    4. 会话状态零持久化：仅存在于当前会话，接缝级断言不含任何落盘行为

LLM 路由行为经 tests/cassettes/followup_*.json 固定（RALPH.md：T6 走 FC 路由
的路径须 cassette），回放底层客户端调用计数 = 0，离线可重复。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from safepass import addressing, config_loader, contracts, data_agent, followup, rating_engine
from safepass.llm_client import reset_cassette_cursor, chat_with_cassette
from safepass.pipeline import execute_query
from safepass.session_state import AreaSnapshot, SessionState

REPO_ROOT = Path(__file__).resolve().parent.parent
CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

CASSETTE_COMPARISON = CASSETTE_DIR / "followup_comparison.json"
CASSETTE_DETAIL = CASSETTE_DIR / "followup_detail.json"
CASSETTE_SHIFT_LOCATION = CASSETTE_DIR / "followup_shift_location.json"
CASSETTE_SHIFT_TOPIC = CASSETTE_DIR / "followup_shift_topic.json"
CASSETTE_OOC = CASSETTE_DIR / "followup_ooc.json"
CASSETTE_EXPLICIT_COMPARISON = CASSETTE_DIR / "followup_explicit_comparison.json"
CASSETTES = (
    CASSETTE_COMPARISON,
    CASSETTE_DETAIL,
    CASSETTE_SHIFT_LOCATION,
    CASSETTE_SHIFT_TOPIC,
    CASSETTE_OOC,
    CASSETTE_EXPLICIT_COMPARISON,
)


class _FailIfCalled:
    """回放路径的底座客户端：被调用即失败（证明 cassette 真的零底层调用）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


class _CassetteClient:
    """把调用转发到 chat_with_cassette 的客户端：录制一次，之后离线零调用回放。"""

    def __init__(self, inner, path: Path):
        self._inner = inner
        self._path = path
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return chat_with_cassette(self._inner, self._path, messages, model=model, **kwargs)


def _cassette_client(path: Path) -> tuple[_CassetteClient, _FailIfCalled]:
    inner = _FailIfCalled()
    reset_cassette_cursor(path)
    return _CassetteClient(inner, path), inner


def _expected_rating(precinct: int) -> rating_engine.RatingResult:
    """Host 侧真实评级：数据 Agent 聚合 + 评级引擎（与追问集承接断言的权威）。"""
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(NYPD_CSV), precinct)
    return rating_engine.rate_precinct(stats, config_loader.load_config())


def _stats(precinct: int) -> data_agent.PrecinctStats:
    return data_agent.aggregate_precinct(data_agent.load_dataset(NYPD_CSV), precinct)


def _canonical(precinct: int) -> str:
    return addressing.canonical_names(config_loader.load_config())[precinct]


def _all_text(contract: Any) -> str:
    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(contract.model_dump() if hasattr(contract, "model_dump") else contract)
    return "\n".join(chunks)


def _narrative_text(contract: Any) -> str:
    """叙事字段文本：排除静态紧急资源清单（通用清单固定列五警局，
    与本轮地点无关；F8-3 的"不得引用上轮地点"约束针对的是分析叙事）。"""
    dump = contract.model_dump(exclude={"emergency_resources", "venues", "non_emergency_contacts"})
    return _all_text(dump)


def _dim_pairs(result: contracts.SafetyQueryResult) -> set[tuple[str, str]]:
    return {(d["dimension"], d["value"]) for d in result.dimensions}


# ---------------------------------------------------------------------------
# 0. 追问细分类（确定性，零 LLM；与 routing 直接测试同一先例）
# ---------------------------------------------------------------------------


@pytest.fixture()
def uptown_state() -> SessionState:
    """真实接缝产出上轮结构化结果（上东区，n=105 → 🟢），会话状态只取其结构化摘要。"""
    return SessionState.from_result(execute_query("上东区晚上安全吗？"))


def _resolve(query: str) -> tuple[addressing.ResolvedArea, ...]:
    return addressing.resolve_areas(query, config_loader.load_config())


def test_classify_comparison_followup(uptown_state):
    plan = followup.classify(
        "那和布鲁克林 Heights 比呢？", _resolve("那和布鲁克林 Heights 比呢？"), uptown_state, config_loader.load_config()
    )
    assert plan.kind == followup.KIND_COMPARISON
    assert plan.target is not None and plan.target.precincts == (84,)


def test_classify_detail_followup_extracts_crowd_and_time_dims(uptown_state):
    plan = followup.classify("女生晚上呢？", (), uptown_state, config_loader.load_config())
    assert plan.kind == followup.KIND_DETAIL
    assert {(d.name, d.value) for d in plan.dimensions} == {("人群", "女生"), ("时间", "晚上")}


def test_classify_shift_location_without_comparison_markers(uptown_state):
    """换地点：文本出现与上轮不同的区域但无对比标记 → 新查询（路由失效）。"""
    plan = followup.classify("那法拉盛呢？", _resolve("那法拉盛呢？"), uptown_state, config_loader.load_config())
    assert plan.kind == followup.KIND_TOPIC_SHIFT


def test_classify_shift_topic_without_area_or_dims(uptown_state):
    plan = followup.classify("纽约哪里租房便宜呢？", (), uptown_state, config_loader.load_config())
    assert plan.kind == followup.KIND_TOPIC_SHIFT


def test_classify_without_session_state_is_topic_shift():
    """无会话状态可承接：follow_up 路由失效，绝不凭空捏出基准区域。"""
    plan = followup.classify(
        "那和布鲁克林 Heights 比呢？", _resolve("那和布鲁克林 Heights 比呢？"), None, config_loader.load_config()
    )
    assert plan.kind == followup.KIND_TOPIC_SHIFT


def test_classify_multi_area_followup_is_topic_shift(uptown_state):
    """追问里一次提到多个新区域 → 超出两种合法追问形态，走新查询流程。"""
    query = "那和法拉盛、唐人街比呢？"
    plan = followup.classify(query, _resolve(query), uptown_state, config_loader.load_config())
    assert plan.kind == followup.KIND_TOPIC_SHIFT


def test_classify_comparison_marker_without_target_area_is_topic_shift(uptown_state):
    """有对比标记但文本里没有可比的新区域 → 承接失败，走新查询流程（诚实不硬凹）。"""
    plan = followup.classify("那和这边比呢？", (), uptown_state, config_loader.load_config())
    assert plan.kind == followup.KIND_TOPIC_SHIFT


# ---------------------------------------------------------------------------
# 1. 勾选 1：对比追问 / 细节追问承接正确（地点、评级、维度叠加均断言）
# ---------------------------------------------------------------------------


def test_comparison_followup_carries_previous_area():
    """F8-1：承接上轮地点走 F3 对比流程；两侧评级与 Host 复算一致。"""
    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    client, inner = _cassette_client(CASSETTE_COMPARISON)

    result = execute_query("那和布鲁克林 Heights 比呢？", session_state=state, llm_client=client)

    assert inner.calls == 0, "cassette 回放必须零底层调用"
    assert result.type == "comparison"
    by_precinct = {a.precinct: a for a in result.areas}
    assert set(by_precinct) == {19, 84}, "对比追问应承接上轮地点（19）+ 文本新区域（84）"
    for precinct, summary in by_precinct.items():
        expected = _expected_rating(precinct)
        assert summary.rating == expected.rating, f"{precinct} 评级必须与评级引擎复算一致"
        assert summary.sample_size == _stats(precinct).sample_size, "样本量 = 数据集真实命中数"
        assert summary.area == _canonical(precinct)
    # 维度表：数据可支撑的维度 available，长期趋势明确开发中（F3-2 的诚实口径）
    dims = {d["dimension"]: d["status"] for d in result.dimensions}
    assert dims["overall_rating"] == "available"
    assert dims["top_offense_types"] == "available"
    assert dims["night_risk"] == "available"
    assert dims["long_term_trend"] == "in_development"
    # 夜间风险与主要犯罪类型维度数据源逐字段来自本次聚合
    for precinct, summary in by_precinct.items():
        stats = _stats(precinct)
        assert (summary.day_night.day, summary.day_night.night) == (
            stats.day_night.day,
            stats.day_night.night,
        )
        assert [(t.offense_type, t.count) for t in summary.top5_types] == [
            (t.offense_type, t.count) for t in stats.top5_types
        ]
    # 84 警区样本量 6（<10 强制 ⚪）：一侧数据不足 → 不出"谁更适合"的结论（诚实）
    assert by_precinct[84].rating == contracts.RATING_INSUFFICIENT
    assert result.decision_aid is None
    assert result.disclaimer.strip() and result.sources, "横切字段齐备（AC-010/AC-008）"


def test_detail_followup_overlays_crowd_and_time_dims():
    """F8-2：承接上轮地点叠加人群/时间维度；评级与直查完全一致（换问法不变评级）。"""
    first = execute_query("上东区晚上安全吗？")
    state = SessionState.from_result(first)
    client, inner = _cassette_client(CASSETTE_DETAIL)

    result = execute_query("女生晚上呢？", session_state=state, llm_client=client)

    assert inner.calls == 0
    assert result.type == "safety"
    assert result.area == _canonical(19) and result.precinct == 19, "地点承接上轮"
    assert result.rating == first.rating == _expected_rating(19).rating, "维度叠加不改变评级"
    assert result.sample_size == first.sample_size
    assert _dim_pairs(result) == {("人群", "女生"), ("时间", "晚上")}, "人群/时间维度叠加断言"
    assert len(result.one_liner) <= 30


def test_explicit_comparison_route_with_session_builds_comparison():
    """AC-016 形态：已查询一个区域后直接问"和X比哪个更安全"（路由 area_comparison）。"""
    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    client, inner = _cassette_client(CASSETTE_EXPLICIT_COMPARISON)

    result = execute_query("和布鲁克林 Heights比哪个更安全？", session_state=state, llm_client=client)

    assert inner.calls == 0
    assert result.type == "comparison"
    assert {a.precinct for a in result.areas} == {19, 84}


def test_direct_dual_in_coverage_comparison_via_seam():
    """双覆盖区直查对比（F3-1）：无需 LLM 也确定性出对比（终局权威在数据，不在路由）。"""
    result = execute_query("上东区和法拉盛哪个更安全？")
    assert result.type == "comparison"
    by_precinct = {a.precinct: a for a in result.areas}
    assert set(by_precinct) == {19, 109}
    assert by_precinct[19].rating == _expected_rating(19).rating
    assert by_precinct[109].rating == _expected_rating(109).rating
    # 两侧都有真实评级 → 决策辅助存在（F3-4 结构断言；话术品味属人工抽查）
    assert result.decision_aid, "两侧均评级时决策辅助字段必须存在"
    assert _canonical(109) in result.decision_aid or _canonical(19) in result.decision_aid
    assert "长期趋势" in result.decision_aid, "趋势维度诚实标注开发中"


def test_ac021_narrative_via_seam():
    """AC-021 全链路：查询 → 对比追问 → 细节追问 → 换地点重置，逐轮承接断言。"""
    cfg = config_loader.load_config()
    first = execute_query("上东区晚上安全吗？")
    assert first.type == "safety"
    state = SessionState.from_result(first)

    # 轮 2：对比追问（cassette 固定 follow_up 路由）
    client, inner = _cassette_client(CASSETTE_COMPARISON)
    second = execute_query("那和布鲁克林 Heights 比呢？", session_state=state, llm_client=client)
    assert inner.calls == 0
    assert second.type == "comparison"
    assert [a.precinct for a in second.areas] == [19, 84]

    # 轮 3：细节追问承接对比轮的最新聚焦区域（布鲁克林 Heights，84）
    state = SessionState.from_result(second)
    assert state.last.precinct == 84, "上轮结构化结果 = 对比轮最后聚焦的区域"
    client, inner = _cassette_client(CASSETTE_DETAIL)
    third = execute_query("女生晚上呢？", session_state=state, llm_client=client)
    assert inner.calls == 0
    assert third.type == "safety"
    assert third.precinct == 84, "细节追问承接上轮地点（对比轮最新区域）"
    assert _dim_pairs(third) == {("人群", "女生"), ("时间", "晚上")}
    # 84 为 ⚪ 档：诚实缺口与图表隐藏同样成立
    assert third.rating == contracts.RATING_INSUFFICIENT
    assert third.unknowns, "⚪ 档 unknowns 非空（AC-007）"
    assert third.charts is None, "⚪ 档图表模块隐藏（AC-022）"

    # 轮 4：换地点 → 不复用上轮任何结构化结果，走新查询流程
    client, inner = _cassette_client(CASSETTE_SHIFT_LOCATION)
    fourth = execute_query("那法拉盛呢？", session_state=state, llm_client=client)
    assert inner.calls == 0
    assert fourth.type == "safety"
    assert fourth.precinct == 109, "换地点后只分析新地点"
    assert fourth.area == _canonical(109)
    assert fourth.rating == _expected_rating(109).rating
    assert "上东区" not in _narrative_text(fourth) and "布鲁克林" not in _narrative_text(fourth)
    assert _dim_pairs(fourth) == set(), "换地点追问不得残留上轮维度叠加"


# ---------------------------------------------------------------------------
# 2. 勾选 2：换地点 / 换话题重置明确
# ---------------------------------------------------------------------------


def test_shift_topic_followup_ignores_previous_area():
    """F8-3：换话题 → follow_up 路由失效，不得引用上轮地点，明确开始新查询。"""
    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    client, inner = _cassette_client(CASSETTE_SHIFT_TOPIC)

    result = execute_query("纽约哪里租房便宜呢？", session_state=state, llm_client=client)

    assert inner.calls == 0
    assert result.type == "degraded"
    assert result.degraded_capability == contracts.CAPABILITY_OUT_OF_COVERAGE
    cfg = config_loader.load_config()
    assert result.message == cfg.degraded.explanation_templates["unrecognized"]
    # 不得承接上轮：说明文案不含任何区域（重新选择邀请是覆盖菜单静态模板，
    # 每次降级响应都会出现，与上轮地点无关，不在"引用上轮"的判定范围）
    assert "上东区" not in result.message
    assert result.alternative_info is None, "重置后不复用上轮区域的替代信息"


def test_follow_up_without_session_state_degrades_unrecognized():
    """无会话状态却路由到 follow_up：不编造承接对象，诚实降级。"""
    client, inner = _cassette_client(CASSETTE_DETAIL)
    result = execute_query("女生晚上呢？", session_state=None, llm_client=client)
    assert inner.calls == 0
    assert result.type == "degraded"
    assert result.alternative_info is None


def test_session_state_carries_only_structured_result():
    """D6：会话状态只存上轮结构化结果（地点/评级/数据摘要），不存对话历史。"""
    fields = {f.name for f in dataclasses.fields(SessionState)}
    assert fields == {"last", "areas"}, "会话状态不得扩展出对话历史类字段"
    snap_fields = {f.name for f in dataclasses.fields(AreaSnapshot)}
    assert snap_fields == {"area", "precinct", "rating", "sample_size"}

    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    assert state.last.area == _canonical(19)
    assert state.last.precinct == 19
    assert state.last.rating == _expected_rating(19).rating
    assert state.last.sample_size == _stats(19).sample_size
    assert state.areas == (state.last,)


def test_from_result_rejects_contracts_without_area_result():
    """降级/紧急响应不含可承接的结构化区域结果：明确失败，不产出伪会话状态。"""
    degraded = execute_query("哥大附近安全吗？")
    assert degraded.type == "degraded"
    with pytest.raises(TypeError):
        SessionState.from_result(degraded)
    emergency = execute_query("救命！有人抢劫")
    assert emergency.type == "emergency"
    with pytest.raises(TypeError):
        SessionState.from_result(emergency)


# ---------------------------------------------------------------------------
# 3. 勾选 3：追问越界走 F3-5 单边越界规则（越界侧无对比结论字段）
# ---------------------------------------------------------------------------


def test_followup_out_of_coverage_single_side_rule():
    """F8-4/F3-5：追问中提到的区域越界 → 覆盖侧只以替代信息给真实评级，
    越界侧只有 out_of_coverage 说明，绝无对比结论。"""
    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    client, inner = _cassette_client(CASSETTE_OOC)

    result = execute_query("那和哥大附近比呢？", session_state=state, llm_client=client)

    assert inner.calls == 0
    assert result.type == "degraded"
    assert result.degraded_capability == contracts.CAPABILITY_OUT_OF_COVERAGE
    assert "哥大附近" in result.message
    assert result.alternative_info is not None, "覆盖侧（上轮地点）真实评级作为替代信息"
    assert result.alternative_info.precinct == 19
    assert result.alternative_info.rating == _expected_rating(19).rating
    comparison_fields = {"areas", "winner", "decision_aid", "verdict", "comparison"}
    assert not (comparison_fields & set(result.model_dump())), "越界追问不得出现任何对比结论字段"
    assert result.reselection_invitation.strip(), "F3-5：邀请重新选择两个覆盖区内区域"


# ---------------------------------------------------------------------------
# 4. 勾选 4：会话状态零持久化（接缝级断言不含任何落盘行为）
# ---------------------------------------------------------------------------


def _snapshot_tree(*roots: Path) -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                st = path.stat()
                state[str(path)] = (st.st_mtime_ns, st.st_size)
    return state


def test_session_state_zero_persistence_via_seam():
    """多轮追问全程经唯一接缝执行后，配置/fixture/cassette 目录逐字节不变：
    会话状态只活在调用方的内存里，管线无任何落盘行为。"""
    watched = (
        REPO_ROOT / "config",
        REPO_ROOT / "fixtures",
        REPO_ROOT / "tests" / "cassettes",
    )
    before = _snapshot_tree(*watched)

    state = SessionState.from_result(execute_query("上东区晚上安全吗？"))
    client, _ = _cassette_client(CASSETTE_COMPARISON)
    comparison = execute_query("那和布鲁克林 Heights 比呢？", session_state=state, llm_client=client)
    state = SessionState.from_result(comparison)
    client, _ = _cassette_client(CASSETTE_DETAIL)
    execute_query("女生晚上呢？", session_state=state, llm_client=client)
    execute_query("上东区和法拉盛哪个更安全？")  # 无 LLM 路径同样执行

    after = _snapshot_tree(*watched)
    assert after == before, "追问流程产生了落盘行为（会话状态必须零持久化）"


# ---------------------------------------------------------------------------
# 5. cassette 资产完整性
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cassette", CASSETTES, ids=[c.name for c in CASSETTES])
def test_cassette_assets_committed_and_wellformed(cassette: Path):
    assert cassette.exists(), f"缺少 {cassette.name}（需录制后提交）"
    data = json.loads(cassette.read_text(encoding="utf-8"))
    interactions = data["interactions"]
    assert len(interactions) == 1, f"{cassette.name} 固定单条路由交互"
    assert interactions[0]["fingerprint"]
    payload = json.loads(interactions[0]["response"]["content"])
    assert payload["route"] in {
        "area_safety_query",
        "area_comparison",
        "follow_up",
        "degraded_response",
        "emergency_help",
    }
