"""票 01 / C1a：覆盖内安全查询的确定性「评级依据」人话。

接缝：
    1. 唯一接缝 execute_query —— 覆盖内 SafetyQueryResult 必带非空
       rating_rationale；绿/黄/红/⚪ 可区分；LLM 输出契约不含该字段。
    2. 结果页渲染 —— 核心结论行之下有且仅有一行「评级依据」+ 该字段；
       旧硬编码倍数散文消失；越界/紧急/对比/防线页不渲染该槽。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from safepass import config_loader, contracts
from safepass.pipeline import execute_query
from safepass.skills import suggestion as suggestion_skill
from frontend import render

CFG = config_loader.get_config()

# mock 世界钉死的四档代表查询（与 A3 金标同源：P19 绿 / P109 黄 / P5 红 / P84 ⚪）
_GREEN_Q = "上东区安全吗？"
_YELLOW_Q = "法拉盛晚上安全吗？"
_RED_Q = "唐人街安全吗？"
_WHITE_Q = "布鲁克林高地安全吗？"

_OLD_PROSE = "该警区犯罪率（per 100k）约为全市均值的"


def test_safety_contract_requires_non_empty_rating_rationale():
    payload = dict(
        area="上东区",
        precinct=19,
        rating="green",
        sample_size=105,
        one_liner="上东区：相对安全",
        extracted=contracts.ExtractedDimensions(),
        sources=["mock"],
        time_range="t",
        charts=None,
        profile_notice="画像仅在本次会话生效，关闭页面即删除",
        disclaimer="本分析仅供参考，不替代专业安保建议。",
    )
    with pytest.raises(ValidationError):
        contracts.SafetyQueryResult(**payload)
    with pytest.raises(ValidationError):
        contracts.SafetyQueryResult(**{**payload, "rating_rationale": "   "})
    ok = contracts.SafetyQueryResult(
        **{**payload, "rating_rationale": "相对全市约 0.6 倍，数据量充足。"}
    )
    assert ok.rating_rationale.strip()


def test_non_safety_contracts_have_no_rating_rationale_field():
    for cls in (
        contracts.ComparisonResult,
        contracts.EmergencyResult,
        contracts.DegradedResult,
        contracts.GuardrailResult,
    ):
        assert "rating_rationale" not in cls.model_fields


def test_suggestion_skill_output_cannot_write_rating_rationale():
    assert "rating_rationale" not in suggestion_skill.SuggestionSkillOut.model_fields


@pytest.mark.parametrize(
    "query, rating",
    [
        (_GREEN_Q, contracts.RATING_GREEN),
        (_YELLOW_Q, contracts.RATING_YELLOW),
        (_RED_Q, contracts.RATING_RED),
        (_WHITE_Q, contracts.RATING_INSUFFICIENT),
    ],
)
def test_in_coverage_seam_emits_nonempty_rating_rationale(query, rating):
    result = execute_query(query)
    assert isinstance(result, contracts.SafetyQueryResult)
    assert result.rating == rating
    assert result.rating_rationale.strip()


def test_four_rating_rationales_are_distinguishable():
    texts = {
        execute_query(q).rating_rationale
        for q in (_GREEN_Q, _YELLOW_Q, _RED_Q, _WHITE_Q)
    }
    assert len(texts) == 4


def test_rated_rationale_shares_one_decimal_with_city_hook():
    for query in (_GREEN_Q, _YELLOW_Q, _RED_Q):
        result = execute_query(query)
        assert result.rating_explainable_basis is not None
        ratio = f"{result.rating_explainable_basis:.1f}"
        assert ratio in result.rating_rationale
        if "约为全市均值" in result.one_liner:
            assert f"{ratio}倍" in result.one_liner
        tier_label = CFG.rating_rationale.sample_tier_labels[result.confidence_tier]
        assert tier_label in result.rating_rationale


def test_insufficient_rationale_has_no_multiplier():
    result = execute_query(_WHITE_Q)
    assert result.rating == contracts.RATING_INSUFFICIENT
    assert "倍" not in result.rating_rationale
    assert str(result.sample_size) in result.rating_rationale


def test_safety_page_has_exactly_one_rationale_line():
    result = execute_query(_GREEN_Q)
    html = render.render_result(result, CFG)
    assert html.count("评级依据") == 1
    assert result.rating_rationale in html
    assert _OLD_PROSE not in html
    block_start = html.index('class="one-liner"')
    block = html[block_start : html.index("</section>", block_start)]
    assert result.one_liner in block
    assert "评级依据" in block
    assert block.count("评级依据") == 1
    assert block.index(result.one_liner) < block.index("评级依据")


@pytest.mark.parametrize("query", [_GREEN_Q, _YELLOW_Q, _RED_Q, _WHITE_Q])
def test_all_four_ratings_render_one_rationale_line(query):
    result = execute_query(query)
    html = render.render_result(result, CFG)
    assert html.count("评级依据") == 1
    assert result.rating_rationale in html
    assert _OLD_PROSE not in html


def test_insufficient_page_still_shows_rating_rationale():
    result = execute_query(_WHITE_Q)
    html = render.render_result(result, CFG)
    assert html.count("评级依据") == 1
    assert result.rating_rationale in html
    assert _OLD_PROSE not in html


@pytest.mark.parametrize(
    "query",
    [
        "哥大附近安全吗",
        "救命！有人抢劫",
        "上东区和唐人街哪个更安全",
        "防身用什么比较好",
    ],
)
def test_non_safety_pages_do_not_render_rating_rationale_slot(query):
    result = execute_query(query)
    assert not isinstance(result, contracts.SafetyQueryResult)
    html = render.render_result(result, CFG)
    assert "评级依据" not in html
    assert _OLD_PROSE not in html
    assert "rating_rationale" not in result.model_dump()
