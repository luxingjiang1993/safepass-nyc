"""issue 31 / B4：混合检索 top-3 回归（query → 应命中文档标识）。

对应 .scratch/safepass-wave2-second-knife/issues/02-b4-retrieval-regression.md
与 spec 波 2 第二刀 B4：
    1. 约 20 条标注钉在 mock 世界（fixtures/index + fixtures/knowledge）
    2. 应命中文档标识必须存在于当前索引元数据；改名单即红
    3. 混合检索接缝 intel_agent.search 的 top-3 含应命中文档；零 LLM、不经建议 Skill
    4. community_info 不参与检索排序（CLAUDE.md 棘轮）
    5. 仓库内 BM25-only vs 混合检索对照表存在且含可核对结论（不在测试里重算 embedding）

先验：tests/test_intel.py 检索集、tests/test_a2_retrieval_suggestions.py 召回探针。
"""

from __future__ import annotations

import inspect
import json
import re
import socket
from pathlib import Path

import pytest

from safepass import config_loader, intel_agent

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_PATH = REPO_ROOT / "fixtures" / "eval" / "b4_retrieval_labels_v1.json"
INDEX_META_PATH = REPO_ROOT / "fixtures" / "index" / "meta.json"
KNOWLEDGE_DIR = REPO_ROOT / "fixtures" / "knowledge"
COMPARISON_DOC = REPO_ROOT / "docs" / "b4-bm25-vs-hybrid.md"


def _block_network(monkeypatch):
    """封锁网络：检索必须全程本地离线（本地 embedding，零 API）。"""

    def _no_connect(*args, **kwargs):
        raise AssertionError("B4 检索回归不得访问网络（必须为本地离线路径）")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: _no_connect())


def _load_labels() -> dict:
    assert LABELS_PATH.exists(), (
        f"缺少 B4 标注夹具 {LABELS_PATH.name}（改删名单必须让本回归变红）"
    )
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    data = _load_labels()
    entries = data["entries"]
    assert isinstance(entries, list)
    return entries


# ---------------------------------------------------------------------------
# 1. 标注规模与覆盖（五核心警区 + 诈骗 / 夜间主题差）
# ---------------------------------------------------------------------------


def test_b4_labels_exist_and_cover_about_twenty():
    entries = _entries()
    n = len(entries)
    assert 18 <= n <= 22, f"B4 标注条数应约为 20，实际 {n}"
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), f"B4 标注 ID 重复：{ids}"
    queries = [e["query"] for e in entries]
    assert len(queries) == len(set(queries)), "B4 查询文本不得重复"


def test_b4_labels_cover_five_precincts_and_scam_vs_night():
    entries = _entries()
    precincts = {int(e["precinct"]) for e in entries}
    covered = set(config_loader.load_config().covered_precincts)
    assert precincts == covered, f"必须覆盖配置中的核心警区，实际 {sorted(precincts)}"
    themes = {e["theme"] for e in entries}
    assert "scam" in themes, "必须覆盖诈骗主题差"
    assert "overview" in themes, "必须覆盖概况/夜间注意事项所在主题（overview）"
    night_queries = [
        e for e in entries if any(tok in e["query"] for tok in ("晚上", "夜里", "夜间", "凌晨"))
    ]
    assert night_queries, "必须含夜间问法（晚上/夜里/夜间/凌晨），不能只靠非夜间 overview"


def test_b4_expected_doc_ids_exist_in_index_and_knowledge():
    """改名单写不存在的文档标识 → 本测试红。"""
    meta = json.loads(INDEX_META_PATH.read_text(encoding="utf-8"))
    known = {d["doc_id"] for d in meta["docs"]}
    missing: list[str] = []
    for entry in _entries():
        expected = entry["expected_doc_ids"]
        assert expected, f"{entry['id']} 缺应命中文档标识"
        for doc_id in expected:
            if doc_id not in known:
                missing.append(f"{entry['id']}:{doc_id}")
            path = KNOWLEDGE_DIR / f"{doc_id}.md"
            assert path.exists(), f"知识文档缺失：{path.name}（{entry['id']}）"
    assert not missing, f"应命中文档不在索引元数据中：{missing}"


# ---------------------------------------------------------------------------
# 2. 混合检索 top-3 命中（接缝 = intel_agent.search）
# ---------------------------------------------------------------------------


_B4_ENTRIES = _entries()


@pytest.mark.parametrize(
    "entry",
    _B4_ENTRIES,
    ids=[e["id"] for e in _B4_ENTRIES],
)
def test_b4_hybrid_top3_hits_expected_docs(entry, monkeypatch):
    _block_network(monkeypatch)
    top = intel_agent.search(entry["query"])
    assert len(top) == intel_agent.TOP_K
    doc_ids = [doc_id for doc_id, _ in top]
    expected = set(entry["expected_doc_ids"])
    assert set(doc_ids) & expected, (
        f"{entry['id']} 查询 {entry['query']!r} 的 top-{intel_agent.TOP_K} "
        f"未命中 {sorted(expected)}：{doc_ids}"
    )
    scores = [score for _, score in top]
    assert scores == sorted(scores, reverse=True), "融合分必须降序"


def test_b4_search_does_not_use_community_info(monkeypatch):
    """community_info 只走警区锚定装配，不得进入混合检索排序。"""
    _block_network(monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("community_info 不得参与检索排序")

    monkeypatch.setattr(intel_agent, "build_community_info", _boom)
    top = intel_agent.search("法拉盛 换汇诈骗")
    assert top, "混合检索在不装配 community_info 时仍须返回文档"
    search_src = inspect.getsource(intel_agent.search)
    assert "community_info" not in search_src
    assert "build_community_info" not in search_src
    meta = json.loads(INDEX_META_PATH.read_text(encoding="utf-8"))
    known = {d["doc_id"] for d in meta["docs"]}
    assert {doc_id for doc_id, _ in top} <= known


# ---------------------------------------------------------------------------
# 3. BM25-only vs 混合检索对照表（静态文档，测试不重算 embedding）
# ---------------------------------------------------------------------------


def test_b4_bm25_vs_hybrid_comparison_table_in_repo():
    """对照表写一次进仓库；断言存在且含可核对结论，不必每次重算 embedding。"""
    assert COMPARISON_DOC.exists(), f"缺少对照表 {COMPARISON_DOC.as_posix()}"
    text = COMPARISON_DOC.read_text(encoding="utf-8")
    assert "BM25" in text and ("混合检索" in text or "hybrid" in text.lower())
    # 至少一行三列表（查询 | BM25 | 混合检索）或含可核对数字
    table_rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and line.count("|") >= 4
    ]
    assert len(table_rows) >= 4, "对照表须含表头与数据行"
    has_numbers = bool(re.search(r"\d+(?:\.\d+)?%|\d+/\d+", text))
    has_boolean_claim = bool(
        re.search(r"hybrid\s*[≥>=]\s*BM25|混合检索.+(不低于|优于|≥|>=).+BM25", text, re.I)
    )
    assert has_numbers or has_boolean_claim, (
        "对照表须含可核对数字（如命中率 18/20）或「hybrid ≥ BM25」类布尔结论"
    )
