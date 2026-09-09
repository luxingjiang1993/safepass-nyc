"""N2b 三列对照回放（issue 26）：cassette 离线，零真实 API。

运行（独立套件，不进默认基线）：``python -m pytest tests/eval/test_n2_three_column.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safepass import config_loader, intel_agent
from safepass.llm_client import ChatResponse
from safepass.pipeline import _retrieval_snippets

import n2_runner
import n2_scorers

pytestmark = pytest.mark.eval

_CFG = config_loader.load_config()
_L2_CASSETTES = {
    Path(_CFG.eval.cassette),
    Path(_CFG.eval.cassette_template),
    Path(_CFG.eval.cassette_skill),
}


class _FailIfCalled:
    """回放守卫：cassette 存在时底层客户端一次都不许被调。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("N2 cassette 回放不应触发任何底层客户端调用")


def test_n2_cassettes_are_not_l2_files():
    """生成 cassette 与 L2 judge/skill 分文件。"""
    n2_paths = {n2_runner.BARE_CASSETTE, n2_runner.RAG_CASSETTE, n2_runner.SAFEPASS_CASSETTE}
    overlap = {p.resolve() for p in n2_paths} & {
        (n2_runner.REPO_ROOT / p).resolve() if not p.is_absolute() else p.resolve()
        for p in _L2_CASSETTES
    }
    assert not overlap


def test_n2_rag_evidence_is_product_hybrid_top3():
    """无约束 RAG 所塞文本 = 产品混合检索 top-3 整篇，不换检索器。"""
    query = "上东区晚上安全吗？"
    evidence = n2_runner.rag_evidence_text(query)
    hits = intel_agent.search(query)
    assert len(hits) == 3
    snippets = _retrieval_snippets(query)
    assert [s.doc_id for s in snippets] == [doc_id for doc_id, _ in hits]
    for snippet in snippets:
        assert snippet.doc_id in evidence
        assert snippet.text in evidence
    # 禁止另塞图表结构（知识原文里即使出现倍数词也不算「注入统计表」）
    assert "top5_types" not in evidence


def test_n2_runner_does_not_call_l2_judge():
    """打分路径不碰 evaluators。"""
    src = Path(n2_runner.__file__).read_text(encoding="utf-8")
    assert "evaluators" not in src
    assert "FEEDBACK_HALLUCINATION" not in src


def _replay() -> dict:
    inner = _FailIfCalled()
    n2_runner.reset_n2_cassettes()
    results = n2_runner.run_n2_suite(llm_client=inner, cfg=_CFG, record=False)
    assert inner.calls == 0
    return results


def test_n2_cassette_assets_exist():
    for path in (n2_runner.BARE_CASSETTE, n2_runner.RAG_CASSETTE, n2_runner.SAFEPASS_CASSETTE):
        assert path.exists(), (
            f"缺少 {path.name}（一次性录制：python scripts/record_n2_cassette.py）"
        )
    for path in (n2_runner.BARE_CASSETTE, n2_runner.RAG_CASSETTE):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["interactions"]) == 20, f"{path.name} 应为 20 条交互"


def test_n2_replay_offline_and_matches_artifact():
    """同一 cassette 回放产出与录制工件一致。"""
    assert n2_runner.RESULTS_PATH.exists()
    artifact = json.loads(n2_runner.RESULTS_PATH.read_text(encoding="utf-8"))
    replayed = _replay()
    assert replayed == artifact
    assert replayed["n_entries"] == 20
    assert [e["id"] for e in replayed["entries"]] == list(
        n2_scorers.load_n2_subset().all_ids
    )


def test_n2_dod_boolean_closure():
    """票面布尔收口：SafePass 优于另两列；越界编造拉开；评级 100%。"""
    results = _replay()
    closure = results["metrics"]["closure"]
    assert closure["safepass_unevidenced_lt_bare"] is True
    assert closure["safepass_unevidenced_lt_rag"] is True
    assert closure["safepass_ooc_fabrication_zero"] is True
    assert closure["bare_ooc_fabrication_ge_1"] is True
    assert closure["rag_ooc_fabrication_ge_1"] is True
    assert closure["safepass_rating_consistency_100"] is True
    assert len(results["failure_samples"]) >= 3


def test_n2_report_matches_replay_numbers():
    """对照页与现场重算数字一致。"""
    results = _replay()
    report = n2_runner.REPORT_PATH.read_text(encoding="utf-8")
    assert report == n2_runner.render_markdown(results)
    sp = results["metrics"]["safepass"]
    assert f"{sp['unevidenced_factual_claim_rate']:.3f}" in report
    assert "裸 LLM" in report and "无约束 RAG" in report and "SafePass" in report
    assert "和会调 API 的人差在哪" in report
