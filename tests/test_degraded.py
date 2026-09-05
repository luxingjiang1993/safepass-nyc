"""issue 05 / RALPH T3 验收测试：降级行为集。

对应 .scratch/safepass-nyc-mvp/issues/05-degraded-branches-d12.md 四条勾选：
    1. 路径/趋势/越界/中城/单边越界对比每类输入 → type=degraded、degraded_capability 正确；
       覆盖内时替代信息含真实评级（与评级引擎独立复算一致）
    2. 响应文本零编造：不含路径级词汇黑名单（"路线风险""照明""替代路线"…）
    3. D12 后置校验：LLM 把越界查询误路由到 area_safety_query → 强制改写为 DegradedResult
    4. 数据不足输入（样本量 <10）→ unknowns 非空、charts 为 null（契约中隐藏图表模块）

只通过唯一接缝 execute_query 断言结构化响应契约（spec Testing Decisions）：
不断言管线内部交互、不 mock 管线内部。LLM 行为经可注入 fake 固定。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from safepass import config_loader, data_agent, rating_engine
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
SAFE_PLACES_JSON = REPO_ROOT / "fixtures" / "safe_places" / "precinct_safe_places.json"

# 路径级词汇黑名单（issue 05 勾选 2）：降级响应中出现任何一个即算编造。
PATH_LEVEL_BLACKLIST = (
    "路线风险",
    "照明",
    "替代路线",
    "人流",
    "路况",
    "途经风险",
    "路径安全评分",
    "安全指数",
)


class _FakeLLM:
    """测试 fake：按注入的 route 返回固定 FC 路由 JSON，并计数调用。"""

    def __init__(self, route: str = "area_safety_query", **extra: Any):
        self.calls = 0
        self.payload = {"route": route, **extra}

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(content=json.dumps(self.payload, ensure_ascii=False), model="fake")


def _expected_rating(precinct: int) -> rating_engine.RatingResult:
    """Host 侧真实评级：直接经数据 Agent 聚合 + 评级引擎（降级分支替代信息的权威；
    与管线同一数据路径——rating_config 锚定数据集复算均值，票 07）。"""
    records = data_agent.load_dataset(NYPD_CSV)
    stats = data_agent.aggregate_precinct(records, precinct)
    return rating_engine.rate_precinct(stats, data_agent.rating_config(records, config_loader.load_config()))


def _all_text(contract: Any) -> str:
    """契约里所有面向用户的文本拼在一起做黑名单扫描（含嵌套替代信息/建议/资源）。"""
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


# ---------------------------------------------------------------------------
# 1. 五类降级输入：type=degraded + degraded_capability 正确
# ---------------------------------------------------------------------------


def test_path_query_in_coverage_degrades_with_real_alternative():
    """路径查询（起终点在覆盖内）→ degraded(path)，替代信息含该区域真实评级与日夜模式。"""
    result = execute_query("从法拉盛地铁站走到 Main Street 40-05 怎么走？")
    assert result.type == "degraded"
    assert result.degraded_capability == "path"

    expected = _expected_rating(109)
    assert result.alternative_info is not None, "覆盖内路径查询必须给出替代信息"
    assert result.alternative_info.precinct == 109
    assert result.alternative_info.rating == expected.rating
    assert result.alternative_info.sample_size == expected.sample_size
    assert result.alternative_info.day_night.day + result.alternative_info.day_night.night == (
        expected.sample_size
    )
    # 替代信息用了真实数据集 → 来源枚举合法透出
    assert result.sources == ["模拟数据"]
    assert result.sample_size == expected.sample_size


def test_trend_query_degrades_with_capability_trend():
    result = execute_query("上东区这五年的治安趋势怎么样？")
    assert result.type == "degraded"
    assert result.degraded_capability == "trend"
    # 覆盖内：替代信息仍给真实评级（趋势结论不给，但区域现状可以给）
    expected = _expected_rating(19)
    assert result.alternative_info is not None
    assert result.alternative_info.rating == expected.rating


def test_out_of_coverage_query_degrades_and_uses_no_foreign_data():
    """"哥大附近"→26 警区 ∉ 覆盖清单 → 诚实降级，绝不硬套其他区域数据。"""
    result = execute_query("哥大附近安全吗？")
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is None, "越界区域没有任何本地评级可给"
    assert result.sample_size is None, "越界区域不得透出样本量（无数据）"


def test_midtown_query_degrades_as_out_of_coverage():
    """中城跨 14/18 两个警区，明确不在覆盖清单 → out_of_coverage。"""
    result = execute_query("中城晚上安全吗？")
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is None


def test_single_sided_out_of_coverage_comparison_degrades():
    """单边越界对比（F3-5）：越界侧无结论，整体进入降级 + 重新选择邀请，
    覆盖侧只以替代信息形式给出真实评级，绝不产出对比结论。"""
    result = execute_query("上东区和哥大附近哪个更安全？")
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is not None, "覆盖侧（上东区）的真实评级应作为替代信息给出"
    assert result.alternative_info.precinct == 19
    assert result.alternative_info.rating == _expected_rating(19).rating
    comparison_fields = {"comparison", "winner", "decision_aid", "verdict"}
    assert not (comparison_fields & set(result.model_dump())), "越界对比不得出现任何对比结论字段"


# ---------------------------------------------------------------------------
# 2. 零编造：降级响应文本不含路径级词汇黑名单
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "从法拉盛地铁站走到 Main Street 40-05 怎么走？",
        "上东区这五年的治安趋势怎么样？",
        "哥大附近安全吗？",
        "中城晚上安全吗？",
        "上东区和哥大附近哪个更安全？",
    ],
)
def test_degraded_response_contains_no_path_level_blacklist_words(query: str):
    result = execute_query(query)
    assert result.type == "degraded"
    text = _all_text(result)
    for word in PATH_LEVEL_BLACKLIST:
        assert word not in text, f"降级响应出现路径级编造词汇「{word}」：{query}"


def test_degraded_result_has_required_honest_components():
    """契约 D3：降级形态必备 = 能力说明 + 替代信息/无数据说明 + 重新选择邀请
    + 通用建议 + 紧急资源 + 横切字段（disclaimer/sources）。"""
    result = execute_query("哥大附近安全吗？")
    assert result.type == "degraded"
    assert result.message, "必须有明确的开发中/无数据说明"
    assert result.reselection_invitation, "必须有重新选择邀请"
    assert result.general_suggestions, "必须给出通用建议"
    assert result.emergency_resources, "必须给出紧急资源"
    assert result.disclaimer, "免责声明必须每处存在"
    # 越界降级未使用任何数据集 → 来源为空是诚实的（不给假来源）
    assert result.sources == []
    # 越界说明必须诚实点出识别到的警区（26），且替代信息为空（不硬塞覆盖区评级）
    assert "26" in result.message
    assert result.alternative_info is None


def test_degraded_emergency_resources_match_safe_places_general_list():
    """紧急资源逐字段来自警区静态表通用清单（911/311 + 五警局），不自行编造。"""
    fixture = json.loads(SAFE_PLACES_JSON.read_text(encoding="utf-8"))
    expected_venues = fixture["general"]["venues"]
    result = execute_query("哥大附近安全吗？")
    got = result.emergency_resources
    assert len(got) == len(expected_venues)
    for got_v, exp_v in zip(got, expected_venues):
        for key, value in exp_v.items():
            assert getattr(got_v, key) == value, f"紧急资源字段 {key} 与静态表不一致"


# ---------------------------------------------------------------------------
# 3. D12 确定性后置：LLM 误路由越界查询 → 强制改写为 DegradedResult
# ---------------------------------------------------------------------------


def test_d12_post_check_overrides_llm_misroute_to_area_query():
    """LLM 把「哥大附近」误路由到 area_safety_query：后置校验（FC 路由之后、
    数据查询之前）必须无条件强制改写为 DegradedResult。"""
    fake = _FakeLLM(route="area_safety_query")
    result = execute_query("哥大附近安全吗？", llm_client=fake)
    assert fake.calls == 1, "管线应真实经过路由层（后置校验发生在路由之后）"
    assert result.type == "degraded", "D12 后置校验必须强制改写 LLM 误路由结果"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is None


def test_d12_post_check_overrides_misrouted_midtown():
    fake = _FakeLLM(route="area_safety_query")
    result = execute_query("Midtown 中城治安怎么样？", llm_client=fake)
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"


def test_d12_ignores_llm_claiming_valid_route_for_out_of_coverage():
    """即使 LLM 声称已解析出覆盖内警区，只要确定性地址解析 ∉ 覆盖清单，照样降级。"""
    fake = _FakeLLM(route="area_safety_query", precinct=19)
    result = execute_query("哥大附近安全吗？", llm_client=fake)
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"


def test_in_coverage_query_still_uses_llm_route():
    """反向对照：覆盖内查询不被误伤——LLM 正常路由出评级结果。"""
    fake = _FakeLLM(route="area_safety_query")
    result = execute_query("上东区晚上安全吗？", llm_client=fake)
    assert result.type == "safety"
    assert result.rating == _expected_rating(19).rating


# ---------------------------------------------------------------------------
# 4. 数据不足（样本量 <10）→ unknowns 非空、charts 为 null
# ---------------------------------------------------------------------------


def test_insufficient_data_query_unknowns_nonempty_and_charts_null():
    """布鲁克林高地（P84）fixture 仅 <10 条 ⚪ 案例：契约必须诚实呈现数据不足，
    图表模块整体隐藏（charts=null）。"""
    cfg = config_loader.load_config()
    insufficient_tier = next(t for t in cfg.sample_size_tiers if t.rating is not None)
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(NYPD_CSV), 84)
    assert insufficient_tier.min <= stats.sample_size <= insufficient_tier.max

    result = execute_query("布鲁克林高地安全吗？")
    assert result.type == "safety"
    assert result.rating == insufficient_tier.rating
    assert result.confidence_tier is None, "⚪ 档不给可信度"
    assert result.unknowns, "数据不足必须透出 honest unknowns（AC-007）"
    assert result.charts is None, "⚪ 时图表模块隐藏（AC-022 / spec D9）"
    assert result.sample_size == stats.sample_size, "样本量 = 数据集真实命中数"


def test_sufficient_data_query_has_charts_matching_aggregation():
    """对照：样本量充足的覆盖区查询，charts 数值与数据 Agent 聚合逐字段一致。"""
    result = execute_query("上东区安全吗？")
    assert result.type == "safety"
    assert result.charts is not None
    stats = data_agent.aggregate_precinct(data_agent.load_dataset(NYPD_CSV), 19)
    assert [(t.offense_type, t.count) for t in result.charts.top5_types] == [
        (t.offense_type, t.count) for t in stats.top5_types
    ]
    assert (result.charts.day_night.day, result.charts.day_night.night) == (
        stats.day_night.day,
        stats.day_night.night,
    )


# ---------------------------------------------------------------------------
# 5. 审查修复锁定：未识别输入不逃出契约；未落地路由显式失败
# ---------------------------------------------------------------------------


def test_unresolvable_path_query_still_degrades_not_raises():
    """路径查询的起终点均无法识别：仍进降级形态（capability=path），
    替代信息为 None，绝不抛出异常逃出响应契约（spec D3）。"""
    result = execute_query("从A站到B站怎么走？")
    assert result.type == "degraded"
    assert result.degraded_capability == "path"
    assert result.alternative_info is None
    assert result.sample_size is None


def test_unresolvable_plain_query_degrades_honestly():
    result = execute_query("今天纽约天气怎么样？")
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is None
    text = _all_text(result)
    for word in PATH_LEVEL_BLACKLIST:
        assert word not in text


def test_emergency_route_builds_static_emergency_result_since_t5():
    """LLM 路由到 emergency_help（第二层兜底，T5 已落地）：路由判定后不再生成
    自由文本，静态组装 EmergencyResult；全管线只此一次 LLM 调用。"""
    fake = _FakeLLM(route="emergency_help")
    result = execute_query("深夜回家路上总觉得身后有脚步声，我不敢回头", llm_client=fake)
    assert fake.calls == 1, "第二层只有路由这一次 LLM 调用"
    assert result.type == "emergency"
    assert result.is_emergency is True


def test_follow_up_without_session_state_degrades_unrecognized():
    """T6 落地后：follow_up 路由无可承接的会话状态 → 不编造承接对象，
    走新查询流程（无区域可识别 → 诚实降级），详见 tests/test_followup.py。"""
    fake = _FakeLLM(route="follow_up")
    result = execute_query("那晚上呢？", llm_client=fake)
    assert result.type == "degraded"
    assert result.degraded_capability == "out_of_coverage"
    assert result.alternative_info is None


def test_dual_in_coverage_comparison_moved_to_t6():
    """双覆盖区对比已由 T6（issue 08）落地为 ComparisonResult 契约；
    降级行为集中保留单边越界形态（test_single_sided_out_of_coverage_comparison_degrades），
    双覆盖区对比断言见 tests/test_followup.py 追问集。"""
    result = execute_query("上东区和法拉盛哪个更安全？")
    assert result.type == "comparison"
