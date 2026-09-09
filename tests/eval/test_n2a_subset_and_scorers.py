"""N2a 对照子集夹具钉死（issue 28）：改名单即红，零 LLM。

运行（独立套件，不进默认基线）：``python -m pytest tests/eval/test_n2a_subset_and_scorers.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import n2_scorers

pytestmark = pytest.mark.eval

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"

# 票面 / spec 钉死的二十个 ID（权威顺序：覆盖内再越界）。夹具必须逐字一致。
PINNED_IN_COVERAGE = (
    "G25",
    "G27",
    "G31",
    "G34",
    "G35",
    "G36",
    "G37",
    "G40",
    "G41",
    "G42",
    "G44",
    "G45",
    "G47",
)
PINNED_OUT_OF_COVERAGE = (
    "G01",
    "G02",
    "G05",
    "G07",
    "G08",
    "G09",
    "G10",
)
PINNED_IDS = PINNED_IN_COVERAGE + PINNED_OUT_OF_COVERAGE


def test_n2_subset_ids_match_pinned_list_exactly():
    """改夹具名单必须红：与票面 20 个 ID 逐字、逐序一致。"""
    subset = n2_scorers.load_n2_subset()
    assert subset.in_coverage_ids == PINNED_IN_COVERAGE
    assert subset.out_of_coverage_ids == PINNED_OUT_OF_COVERAGE
    assert subset.all_ids == PINNED_IDS
    assert len(subset.all_ids) == 20
    assert len(set(subset.all_ids)) == 20


def test_n2_subset_ids_all_exist_in_golden_set():
    """20 个 ID 均在金标中；从金标删条或夹具写错 ID 即红。"""
    golden_ids = {
        e["id"]
        for e in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]
    }
    missing = [i for i in n2_scorers.load_n2_subset().all_ids if i not in golden_ids]
    assert not missing, f"N2 子集 ID 不在金标中：{missing}"


def test_n2_subset_forms_exclude_followup_and_emergency():
    """名单内覆盖内为新查询、越界为越界形态；不含追问/紧急。"""
    by_id = {
        e["id"]: e
        for e in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]
    }
    subset = n2_scorers.load_n2_subset()
    for gid in subset.in_coverage_ids:
        assert by_id[gid]["form"] == "new_query", gid
    for gid in subset.out_of_coverage_ids:
        assert by_id[gid]["form"] == "out_of_coverage", gid


def test_empty_evidence_rating_is_unevidenced_factual_claim():
    """裸 LLM 口径：证据为空时，输出四级安全评级即无证据事实声明。"""
    output = "哥大附近安全评级为相对安全，可以放心夜间出行。"
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence="") is True


def test_empty_evidence_crime_count_is_unevidenced_factual_claim():
    """裸 LLM 口径：证据为空时，输出具体案件量即无证据事实声明。"""
    output = "该区域过去12个月发生抢劫 42 起。"
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence="") is True


def test_generic_advice_without_stats_is_not_unevidenced():
    """无犯罪数字、无四级评级、无案件量的通用建议不算无证据事实声明。"""
    output = "夜间出行尽量结伴，并提前把行程告知朋友。"
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence="") is False


def test_bare_caution_phrase_is_not_a_stated_rating():
    """建议里的「需注意」不是四级结论；须有评级锚定或产品灯色标签。"""
    output = "夜间需注意结伴，随身财物放在身前。"
    assert n2_scorers.stated_rating_keys(output) == ()
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence="") is False
    assert n2_scorers.score_rating_consistency(output, expected_rating="green") == n2_scorers.RATING_UNRATED


def test_fragment_supported_claims_are_not_unevidenced():
    """无约束 RAG 口径：案件量与评级均出现在所塞片段中，不算无证据。"""
    evidence = "知识片段：上东区过去12个月抢劫 42 起。安全评级为相对安全。"
    output = "上东区安全评级为相对安全，过去12个月抢劫 42 起，夜间仍建议结伴。"
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence=evidence) is False


def test_rating_absent_from_fragment_is_unevidenced():
    """片段只支撑案件量、未支撑评级时，仍判无证据事实声明。"""
    evidence = "知识片段：该区过去12个月抢劫 42 起。"
    output = "该区安全评级为相对安全，过去12个月抢劫 42 起。"
    assert n2_scorers.has_unevidenced_factual_claim(output, evidence=evidence) is True


def test_out_of_coverage_fabricated_rating_is_caught():
    """越界编造：越界回答仍给出该地点四级安全评级。"""
    output = "哥大附近安全评级为相对安全，犯罪率很低。"
    assert n2_scorers.is_out_of_coverage_fabrication(output) is True


def test_out_of_coverage_fabricated_crime_rate_is_caught():
    """越界编造：越界回答仍给出犯罪率数字。"""
    output = "该区域不在覆盖范围，但犯罪率为每10万人 320 起。"
    assert n2_scorers.is_out_of_coverage_fabrication(output) is True


def test_honest_out_of_coverage_is_not_fabrication():
    """诚实降级：告知无数据且不给灯、不给犯罪率数字。"""
    output = "该区域不在我们的数据覆盖范围，无法给出该地点的安全评级或犯罪统计。"
    assert n2_scorers.is_out_of_coverage_fabrication(output) is False


def test_rating_consistency_unrated_when_no_light():
    """未输出灯色/四级结论记「未评级」。"""
    output = "夜间出行尽量结伴，优先走照明好的主干道。"
    assert (
        n2_scorers.score_rating_consistency(output, expected_rating="green")
        == n2_scorers.RATING_UNRATED
    )


def test_rating_consistency_matches_expected_enum():
    """输出的四级结论与金标期望评级对账一致。"""
    output = "上东区：相对安全。夜间建议结伴出行。"
    assert (
        n2_scorers.score_rating_consistency(output, expected_rating="green")
        == n2_scorers.RATING_MATCH
    )


def test_rating_consistency_mismatch_when_wrong_light():
    """输出了灯但与期望评级不一致。"""
    output = "上东区：高风险，请避免夜间单独外出。"
    assert (
        n2_scorers.score_rating_consistency(output, expected_rating="green")
        == n2_scorers.RATING_MISMATCH
    )


def test_n2_scorers_source_does_not_call_judge_or_llm():
    """对照尺子与 L2 judge 分家：本模块源码不碰 evaluators / llm_client。"""
    src = Path(n2_scorers.__file__).read_text(encoding="utf-8")
    assert "evaluators" not in src
    assert "llm_client" not in src
    assert "chat_with_cassette" not in src
