"""B2 确定性质量维度单测（issue 05）：actionability + specificity + 矛盾检测。

纯函数直接测试（零 cassette、零网络、零真实 LLM——宪法②复现性）：
- actionability：动作词命中（词表 = config eval.quality.action_verbs）
- specificity：grounds union 匹配（top-3 池注入非逐条对齐）+ 锚点长度阈值
- 矛盾检测：夜间方向断言 vs 昼夜计数的算术核对（P6 定案 2：确定性，LLM 零参与）
- quality_dimensions 装配：非 safety 形态 → None；safety 形态 → 三维字典
"""

from __future__ import annotations

import pytest

from safepass import config_loader, contracts, evaluators

_CFG = config_loader.load_config()
_Q = _CFG.eval.quality


def _safety_result(
    suggestions: list[str],
    grounds: list[str],
    *,
    source: str = "skill",
) -> contracts.SafetyQueryResult:
    """最小安全契约构造（只填质量维度用得到的字段）。"""
    return contracts.SafetyQueryResult(
        area="上东区",
        precinct=19,
        rating="green",
        sample_size=105,
        one_liner="上东区：🟢 相对安全",
        rating_rationale="相对全市约 0.6 倍，数据量充足。",
        extracted=contracts.ExtractedDimensions(),
        suggestions=suggestions,
        suggestion_grounds=[
            contracts.SuggestionGround(doc_id=f"doc-{i}", quote=q)
            for i, q in enumerate(grounds)
        ],
        suggestions_source=source,
        sources=["mock_nypd.csv"],
        time_range="2025-09 ~ 2026-08",
        charts=None,
        profile_notice="画像仅用于本会话建议排序，关闭即删除。",
        disclaimer="本分析仅供参考。",
    )


def _safety_evidence(day: int, night: int) -> dict:
    return {
        "kind": "safety",
        "data": {"day_night": {"day": day, "night": night}},
    }


class TestActionability:
    def test_hits_action_verbs(self):
        suggestions = ["夜间出行尽量结伴", "将背包前背以防扒窃"]
        assert evaluators.actionability_scores(suggestions, _Q.action_verbs) == (
            True,
            True,
        )

    def test_misses_non_imperative_text(self):
        suggestions = ["本区治安概况如下所示"]  # 陈述句，零动作词
        assert evaluators.actionability_scores(suggestions, _Q.action_verbs) == (
            False,
        )

    def test_empty_suggestions(self):
        assert evaluators.actionability_scores([], _Q.action_verbs) == ()


class TestSpecificity:
    def test_union_match_hits_second_ground(self):
        """grounds 是 top-3 池注入（非逐条对齐）：条目命中任一引文锚点即达标。"""
        suggestions = ["在缅街商业区行走时将背包前背"]
        grounds = [
            "深夜地铁站周边人流量骤减，独行注意周边环境。",
            "缅街/罗斯福大道一带拥挤，注意背包前背。",
        ]
        assert evaluators.specificity_scores(
            suggestions, grounds, _Q.anchor_min_chars
        ) == (True,)

    def test_anchor_shorter_than_threshold_rejected(self):
        """只有泛词级重叠（夜间/注意 各 2 字）不足 anchor_min_chars，不算锚定。"""
        suggestions = ["夜间注意随身物品保管"]
        grounds = ["夜间出行注意安全"]  # 最长公共子串 = 夜间/注意（2 字）< 阈值
        assert evaluators.specificity_scores(
            suggestions, grounds, _Q.anchor_min_chars
        ) == (False,)

    def test_generic_overlap_at_or_above_threshold_counts(self):
        """行为锁定（口径写明）：实现不校验子串类别，≥ 阈值的泛词级重叠
        也计命中——保守的「本区情报锚定覆盖下限」口径。"""
        suggestions = ["夜间出行注意随身物品"]
        grounds = ["夜间出行注意安全"]  # 最长公共子串 = 夜间出行注意（6 字）
        assert evaluators.specificity_scores(
            suggestions, grounds, _Q.anchor_min_chars
        ) == (True,)

    def test_empty_grounds_never_anchored(self):
        suggestions = ["夜间出行尽量结伴"]
        assert evaluators.specificity_scores(suggestions, [], _Q.anchor_min_chars) == (
            False,
        )
        assert evaluators.specificity_scores(
            suggestions, [""], _Q.anchor_min_chars
        ) == (False,)

    def test_template_path_style_generic_text_not_anchored(self):
        """模板通用建议即使有本区引文池，也不含情报锚点短语（区分度来源）。"""
        suggestions = ["夜间出行尽量结伴，并提前告知朋友行程"]
        grounds = ["缅街/罗斯福大道一带拥挤，注意背包前背。"]
        assert evaluators.specificity_scores(
            suggestions, grounds, _Q.anchor_min_chars
        ) == (False,)


class TestContradictions:
    def test_claim_night_safer_while_night_higher_flagged(self):
        contradictions = evaluators.detect_contradictions(
            ["夜间更安全，可以放心出门"],
            day=40,
            night=60,
            quality_cfg=_Q,
        )
        assert len(contradictions) == 1
        assert "60" in contradictions[0] and "40" in contradictions[0]

    def test_claim_night_safer_while_night_lower_clean(self):
        assert (
            evaluators.detect_contradictions(
                ["夜间更安全"], day=60, night=40, quality_cfg=_Q
            )
            == []
        )

    def test_claim_night_danger_while_night_lower_flagged(self):
        contradictions = evaluators.detect_contradictions(
            ["深夜更危险，尽量少出门"],
            day=60,
            night=40,
            quality_cfg=_Q,
        )
        assert len(contradictions) == 1

    def test_claim_night_danger_while_night_higher_clean(self):
        assert (
            evaluators.detect_contradictions(
                ["深夜更危险"], day=40, night=60, quality_cfg=_Q
            )
            == []
        )

    def test_equality_no_direction_contradiction(self):
        """昼夜持平：两个方向都不构成事实矛盾（严格矛盾口径，不冤枉）。"""
        assert (
            evaluators.detect_contradictions(
                ["夜间更安全", "夜间更危险"],
                day=50,
                night=50,
                quality_cfg=_Q,
            )
            == []
        )

    def test_ambiguous_sentence_skipped(self):
        """更安全/更危险同句 = 歧义跳过（不冤枉也不漏判）。"""
        assert (
            evaluators.detect_contradictions(
                ["有人说夜间更安全，也有人说夜间更危险"],
                day=40,
                night=60,
                quality_cfg=_Q,
            )
            == []
        )

    def test_negated_direction_claim_skipped(self):
        """「并非夜间更危险」是否定表达不是断言：不判矛盾（防误杀）。"""
        assert (
            evaluators.detect_contradictions(
                ["并非夜间更危险，只是深夜照明差"],
                day=60,
                night=40,
                quality_cfg=_Q,
            )
            == []
        )

    def test_question_sentence_skipped(self):
        """疑问句不是断言（「夜间更危险？」不构成声称）：只有第二句判矛盾。"""
        contradictions = evaluators.detect_contradictions(
            ["夜间更危险？", "夜间更危险，尽量少出门"],
            day=60,
            night=40,
            quality_cfg=_Q,
        )
        assert len(contradictions) == 1

    def test_sentence_scoped_not_cross_sentence(self):
        """方向断言只在其所在句内成立：违例句与干净句互不污染。"""
        contradictions = evaluators.detect_contradictions(
            ["夜间更安全，放心出行。白天逛街注意保管财物"],
            day=40,
            night=60,
            quality_cfg=_Q,
        )
        assert len(contradictions) == 1

    def test_no_direction_words_clean(self):
        assert (
            evaluators.detect_contradictions(
                ["夜间避免走偏僻小巷，选择照明良好的路线"],
                day=40,
                night=60,
                quality_cfg=_Q,
            )
            == []
        )


class TestQualityDimensions:
    def test_safety_result_full_quality_face(self):
        result = _safety_result(
            ["在缅街商业区行走时将背包前背以防扒窃"],
            ["缅街/罗斯福大道一带拥挤，注意背包前背。"],
        )
        quality = evaluators.quality_dimensions(result, _safety_evidence(58, 36), _CFG)
        assert quality == {
            "actionability": 1.0,
            "specificity": 1.0,
            "contradictions": [],
            "n_suggestions": 1,
        }

    def test_non_safety_result_none(self):
        result = contracts.DegradedResult(
            degraded_capability="out_of_coverage",
            message="该区域不在覆盖范围内。",
            reselection_invitation="可在覆盖区域内重新选择区域。",
            general_suggestions=["夜间出行尽量结伴"],
            disclaimer="本分析仅供参考。",
        )
        assert (
            evaluators.quality_dimensions(result, _safety_evidence(58, 36), _CFG)
            is None
        )

    def test_non_safety_evidence_kind_none(self):
        result = _safety_result(["夜间出行尽量结伴"], [])
        assert evaluators.quality_dimensions(result, {"kind": "comparison"}, _CFG) is None
        assert evaluators.quality_dimensions(result, {"kind": "degraded"}, _CFG) is None

    def test_empty_suggestions_zero_scores(self):
        result = _safety_result([], [])
        quality = evaluators.quality_dimensions(result, _safety_evidence(58, 36), _CFG)
        assert quality == {
            "actionability": 0.0,
            "specificity": 0.0,
            "contradictions": [],
            "n_suggestions": 0,
        }

    def test_contradiction_recorded_in_quality(self):
        result = _safety_result(["夜间更安全，可以放心出行"], [])
        quality = evaluators.quality_dimensions(
            result, _safety_evidence(day=40, night=60), _CFG
        )
        assert len(quality["contradictions"]) == 1
