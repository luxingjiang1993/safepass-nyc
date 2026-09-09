"""issue 32 / N4 脏输入参数化：畸形查询仍须落在合法契约形态。

对应 .scratch/safepass-wave2-second-knife/issues/03-n4-dirty-input.md：
    空 / 仅空白、超长、中英混、复读、控制字符；夹具可含表情符号。
    输出只能是紧急 / 防线拒绝 / 诚实降级之一，或结构完整的覆盖内安全结果
    （含双区对比）；禁止半残契约。安全路径上 rating 只与确定性引擎复算一致。
    不替代 N1 语义攻击表；不加 hypothesis。

只打唯一接缝 execute_query（spec Testing Decisions），不断言内部函数名。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safepass import config_loader, contracts, data_agent, rating_engine
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
REQUIREMENTS = REPO_ROOT / "requirements.txt"
N1_ATTACKS = REPO_ROOT / "fixtures" / "eval" / "injection_attacks_v1.json"

# 夹具里的表情符号（不含四级灯色圆点 🟢/🟡/🔴，那些是既有评级标签）。
_QUERY_EMOJI = frozenset("😀🔥😂")

# 产品文案槽（配置模板 / 确定性填空），与用户脏输入不是同一槽。
_PRODUCT_TEXT_FIELDS = (
    "disclaimer",
    "profile_notice",
    "one_liner",
    "message",
    "reselection_invitation",
    "call_911_prompt",
    "comfort_message",
    "chinese_interpreter_phrase",
    "degradation_notice",
)

# 无覆盖别名：非法桶，只能紧急 / 防线拒绝 / 诚实降级。
UNRESOLVED_CASES = (
    ("empty", ""),
    ("whitespace", " \t\n  "),
    ("overlong_noise", "x" * 4000),
    ("repeater_noise", "啊" * 200),
    ("control_only", "\x00\x01\x07"),
    ("emoji_only", "😀🔥😂"),
)

# 仍能解析到核心警区：允许结构完整的覆盖内安全（或对比）结果。
IN_COVERAGE_DIRTY_CASES = (
    ("overlong_in_coverage", "上东区晚上安全吗" + ("啊" * 1500)),
    ("mixed_cn_en", "Upper East Side 上东区 safe吗 tonight?"),
    ("repeater_in_coverage", "上东区安全吗" * 80),
    ("control_chars", "上东区\x00\x01安全吗\x07"),
    ("emoji_in_coverage", "上东区安全吗😂🔥"),
)

DIRTY_CASES = UNRESOLVED_CASES + IN_COVERAGE_DIRTY_CASES

_LEGAL_TYPES = (
    contracts.EmergencyResult,
    contracts.GuardrailResult,
    contracts.DegradedResult,
    contracts.SafetyQueryResult,
    contracts.ComparisonResult,
)


def _expected_rating(precinct: int) -> rating_engine.RatingResult:
    """Host 侧权威复算（与管线同一数据路径：rating_config 锚定数据集）。"""
    records = data_agent.load_dataset(NYPD_CSV)
    stats = data_agent.aggregate_precinct(records, precinct)
    return rating_engine.rate_precinct(
        stats, data_agent.rating_config(records, config_loader.load_config())
    )


def _assert_complete_safety(result: contracts.SafetyQueryResult) -> None:
    """覆盖内安全契约不得缺必填槽；rating 比特与引擎复算一致。"""
    assert result.type == "safety"
    assert result.area
    assert result.precinct in config_loader.get_config().covered_precincts
    assert result.rating in contracts.LEGAL_RATINGS
    assert result.sample_size >= 0
    assert result.one_liner
    assert result.extracted is not None
    assert result.suggestions
    assert result.sources
    assert result.time_range
    assert result.disclaimer
    assert result.profile_notice
    expected = _expected_rating(result.precinct)
    assert result.rating == expected.rating
    assert result.sample_size == expected.sample_size
    if expected.confidence is None:
        assert result.rating_explainable_basis is None
        assert result.confidence_tier is None
        assert result.charts is None
        assert result.unknowns
    else:
        assert result.rating_explainable_basis is not None
        assert result.confidence_tier == expected.confidence
        assert result.charts is not None


def _assert_complete_comparison(result: contracts.ComparisonResult) -> None:
    assert result.type == "comparison"
    assert result.areas
    assert result.disclaimer
    covered = set(config_loader.get_config().covered_precincts)
    for area in result.areas:
        assert area.precinct in covered
        expected = _expected_rating(area.precinct)
        assert area.rating == expected.rating
        assert area.sample_size == expected.sample_size


def _assert_complete_degraded(result: contracts.DegradedResult) -> None:
    assert result.type == "degraded"
    assert result.degraded_capability in contracts.LEGAL_CAPABILITIES
    assert result.message
    assert result.reselection_invitation
    assert result.disclaimer
    # 越界/未识别不得假装成覆盖内安全契约（无顶栏 rating）。
    assert "rating" not in type(result).model_fields
    if result.alternative_info is not None:
        expected = _expected_rating(result.alternative_info.precinct)
        assert result.alternative_info.rating == expected.rating


def _assert_complete_emergency(result: contracts.EmergencyResult) -> None:
    assert result.type == "emergency"
    assert result.is_emergency is True
    assert result.call_911_prompt
    assert result.chinese_interpreter_phrase
    assert result.info_checklist
    assert result.comfort_message
    assert result.disclaimer


def _assert_complete_guardrail(result: contracts.GuardrailResult) -> None:
    assert result.type == "guardrail"
    assert result.guardrail_kind in contracts.LEGAL_GUARDRAIL_KINDS
    assert result.message
    assert result.disclaimer
    assert "rating" not in type(result).model_fields


def _assert_query_emoji_not_copied_into_product(
    result: contracts.ResponseContract, query: str
) -> None:
    """夹具表情符号不得写进产品模板槽；既有灯色圆点不在此禁。"""
    leaked = {ch for ch in query if ch in _QUERY_EMOJI}
    if not leaked:
        return
    dump = result.model_dump()
    blobs: list[str] = []
    for field in _PRODUCT_TEXT_FIELDS:
        value = dump.get(field)
        if isinstance(value, str):
            blobs.append(value)
    for item in dump.get("suggestions") or []:
        if isinstance(item, str):
            blobs.append(item)
    text = "\n".join(blobs)
    for ch in leaked:
        assert ch not in text, "产品文案不得复制脏输入表情符号"


_ILLEGAL_TYPES = (
    contracts.EmergencyResult,
    contracts.GuardrailResult,
    contracts.DegradedResult,
)


def _assert_legal_complete_contract(result: contracts.ResponseContract) -> None:
    assert isinstance(result, _LEGAL_TYPES)
    type(result).model_validate(result.model_dump())
    if isinstance(result, contracts.SafetyQueryResult):
        _assert_complete_safety(result)
    elif isinstance(result, contracts.ComparisonResult):
        _assert_complete_comparison(result)
    elif isinstance(result, contracts.DegradedResult):
        _assert_complete_degraded(result)
    elif isinstance(result, contracts.EmergencyResult):
        _assert_complete_emergency(result)
    else:
        _assert_complete_guardrail(result)


@pytest.mark.parametrize(
    "query", [c[1] for c in UNRESOLVED_CASES], ids=[c[0] for c in UNRESOLVED_CASES]
)
def test_unresolved_dirty_query_is_illegal_form_not_safety(query):
    """无覆盖别名的畸形查询不得亮覆盖内安全灯。"""
    result = execute_query(query)
    assert isinstance(result, _ILLEGAL_TYPES)
    _assert_legal_complete_contract(result)
    _assert_query_emoji_not_copied_into_product(result, query)


@pytest.mark.parametrize(
    "query",
    [c[1] for c in IN_COVERAGE_DIRTY_CASES],
    ids=[c[0] for c in IN_COVERAGE_DIRTY_CASES],
)
def test_in_coverage_dirty_query_is_complete_and_engine_rated(query):
    """仍走进覆盖内时契约完整，rating 只与引擎复算一致。"""
    result = execute_query(query)
    _assert_legal_complete_contract(result)
    _assert_query_emoji_not_copied_into_product(result, query)


def test_n4_does_not_add_hypothesis_and_keeps_n1_table_separate():
    """N4 用 pytest 参数化，不引入 hypothesis；N1 攻击表仍独立、查询不合并。"""
    req = REQUIREMENTS.read_text(encoding="utf-8").lower()
    assert "hypothesis" not in req
    assert N1_ATTACKS.is_file()
    payload = json.loads(N1_ATTACKS.read_text(encoding="utf-8"))
    n1_queries = {item["query"] for item in payload["attacks"]}
    dirty_queries = {q for _, q in DIRTY_CASES}
    assert dirty_queries.isdisjoint(n1_queries)
