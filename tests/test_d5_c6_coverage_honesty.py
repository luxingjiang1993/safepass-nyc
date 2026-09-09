"""票 05 / D5+C6：首页价值主张与覆盖边界诚实。

接缝（spec 波 2 第二刀 Implementation Decisions §5）：
    首页渲染、覆盖内结果页渲染、越界降级页渲染；警区清单只读覆盖配置。
不锁 CSS 像素，不锁模板每一个标点。
"""

from __future__ import annotations

from safepass import addressing, config_loader, contracts
from safepass.degraded import RATING_LABELS
from safepass.pipeline import execute_query
from frontend import render

CFG = config_loader.get_config()

_HERO = "中文安全情报；数据评级，AI 只建议"
_OLD_HERO = "安全管家"
_STRUCTURE = "若在覆盖内你会看到什么"
_COVERAGE_SCOPE = "coverage-scope"


def _canonical_names() -> list[str]:
    return list(addressing.canonical_names(CFG).values())


def _index_of(html: str, marker: str) -> int:
    assert html.count(marker) == 1, f"marker 应恰好出现一次：{marker!r}（实际 {html.count(marker)} 次）"
    return html.index(marker)


# ---------------------------------------------------------------- 首页 D5


class TestHomeHeroAndCoverageHonesty:
    def test_hero_states_value_prop_matching_skill_reality(self):
        html = render.render_home(CFG)
        assert _HERO in html
        assert _OLD_HERO not in html
        assert "class=\"query-form\"" in html
        assert 'name="q"' in html

    def test_five_core_area_buttons_come_from_config_aliases(self):
        html = render.render_home(CFG)
        names = _canonical_names()
        assert len(names) == len(CFG.covered_precincts)
        assert html.count("class=\"quick-btn\"") == len(names)
        for name in names:
            assert name in html
            assert f"/query?q={name}" in html
        # 按钮文案是别名，不是配置里的警区号
        for precinct in CFG.covered_precincts:
            assert f">{precinct}<" not in html
            assert f"警区 {precinct}" not in html

    def test_home_says_only_five_areas_and_out_of_coverage_does_not_invent_rating(self):
        html = render.render_home(CFG)
        names = _canonical_names()
        for name in names:
            assert name in html
        assert "五个核心警区" in html
        assert "诚实降级" in html
        assert "不编灯" in html


# ---------------------------------------------------------------- 覆盖内结果 C6


class TestInCoverageResultShowsSharedCoverageList:
    def test_result_page_lists_coverage_and_hit_from_same_config(self):
        result = execute_query("上东区安全吗？")
        assert isinstance(result, contracts.SafetyQueryResult)
        html = render.render_result(result, CFG)
        assert _COVERAGE_SCOPE in html
        names = _canonical_names()
        block_start = html.index(_COVERAGE_SCOPE)
        scope = html[block_start : block_start + 400]
        for name in names:
            assert name in html
            assert name in scope
        assert result.area in scope
        assert str(result.precinct) in scope
        assert "本次命中" in scope

    def test_coverage_scope_does_not_break_first_screen_slot_order(self):
        html = render.render_result(execute_query("上东区安全吗？"), CFG)
        assert _index_of(html, "紧急资源") < _index_of(html, _COVERAGE_SCOPE)
        assert _index_of(html, _COVERAGE_SCOPE) < _index_of(html, 'class="charts"')


# ---------------------------------------------------------------- 越界页 C6


class TestOutOfCoverageStructureSketch:
    def test_ooc_page_shows_in_coverage_structure_without_that_place_rating(self):
        result = execute_query("哥大附近安全吗")
        assert isinstance(result, contracts.DegradedResult)
        assert result.degraded_capability == contracts.CAPABILITY_OUT_OF_COVERAGE
        html = render.render_result(result, CFG)
        assert _STRUCTURE in html
        assert "in-coverage-structure" in html
        for name in _canonical_names():
            assert name in html
        # 不为该地点展示四级灯或犯罪率
        assert result.alternative_info is None
        for label in RATING_LABELS.values():
            assert label not in html
        assert "犯罪率" not in html
        assert "per 100k" not in html
        assert "评级依据" not in html

    def test_ooc_general_suggestions_keep_old_semantics_not_white_light(self):
        html = render.render_result(execute_query("哥大附近安全吗"), CFG)
        assert "<summary>💡 通用建议</summary>" in html
        assert RATING_LABELS[contracts.RATING_INSUFFICIENT] not in html

    def test_path_or_trend_degraded_has_no_c6_structure_sketch(self):
        html = render.render_degraded(
            contracts.DegradedResult(
                degraded_capability="path",
                message="路径级安全暂未覆盖",
                alternative_info=None,
                reselection_invitation="请从覆盖区域中重新选择",
                general_suggestions=["夜间出行尽量结伴，并提前告知朋友行程"],
                emergency_resources=[],
                disclaimer="本分析仅供参考，不替代专业安保建议。",
                sources=[],
            ),
            CFG,
        )
        assert _STRUCTURE not in html
        assert "in-coverage-structure" not in html


# ---------------------------------------------------------------- 紧急页负例


class TestEmergencyHasNoD5C6Slots:
    def test_emergency_page_has_no_chips_rationale_or_coverage_sketch(self):
        result = execute_query("救命！有人抢劫")
        assert isinstance(result, contracts.EmergencyResult)
        html = render.render_result(result, CFG)
        assert 'class="chip"' not in html
        assert "评级依据" not in html
        assert _STRUCTURE not in html
        assert "in-coverage-structure" not in html
        assert _COVERAGE_SCOPE not in html
        assert _HERO not in html
