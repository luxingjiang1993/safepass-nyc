"""issue 10 / RALPH T8 验收测试：情报 Agent 混合检索 + RAG 知识库（检索集）。

对应 .scratch/safepass-nyc-mvp/issues/10-hybrid-retrieval-rag.md 五条勾选：
    1. 检索集全绿：专名查询（精确地名/犯罪术语）+ 语义查询共 ≥10 条，
       对应报告全部出现在 RRF 融合 top-3
    2. community_info 字段断言：知识库未记载的中文警员项输出统一标注（"未核实到"）
    3. 无官方来源的机构不出现在社区资源列表
    4. 向量侧本地 embedding 模型，测试离线可跑、零 API 依赖
    5. 词汇遵循 CONTEXT.md（混合检索，不用"双路检索"）

community_info 装配走唯一接缝（execute_query → SafetyQueryInfo.community_info），
未记载标注的措辞单一事实源在 config intel.unverified_label。
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from safepass import config_loader, intel_agent
from safepass.llm_client import chat_with_cassette, reset_cassette_cursor
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = REPO_ROOT / "fixtures" / "index"
CASSETTE_SEAM = REPO_ROOT / "tests" / "cassettes" / "fc_routing_seam.json"


def _block_network(monkeypatch):
    """封锁网络：检索/装配必须全程本地离线（本地 embedding，零 API 依赖）。"""

    def _no_connect(*args, **kwargs):
        raise AssertionError("情报 Agent 不得访问网络（必须为本地离线路径）")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: _no_connect())


# ---------------------------------------------------------------------------
# 1. 检索集：专名 + 语义查询 ≥10 条，对应报告全部出现在 RRF 融合 top-3
#    （查询按"地名+主题词"格式设计：BM25 承载专名区分度，向量侧宽泛召回）
# ---------------------------------------------------------------------------

RETRIEVAL_CASES = [
    # 专名查询（精确地名/犯罪术语）
    ("法拉盛 换汇诈骗", "p109_scam", "专名"),
    ("唐人街 冒充使领馆诈骗", "p5_scam", "专名"),
    ("上东区 仇恨犯罪", "p19_overview", "专名"),
    ("威廉斯堡 自行车盗窃", "p90_overview", "专名"),
    ("布鲁克林高地 急诊 医院", "p84_emergency", "专名"),
    # 语义查询（自然问法，不要求专名逐字出现）
    ("flushing 缅街 商业区 扒窃", "p109_overview", "语义"),
    ("中央公园附近 独行女性 注意什么", "p19_overview", "语义"),
    ("布鲁克林 大桥公园 走散 集合点", "p84_emergency", "语义"),
    ("williamsburg 夜间 娱乐场所 纠纷", "p90_emergency", "语义"),
    ("新移民 需要 中文翻译 报警", "p5_emergency", "语义"),
    ("唐人街 老人 孙辈急难 电话骗局", "p5_scam", "语义"),
    ("威廉斯堡 租房 押金 诈骗", "p90_scam", "语义"),
    ("布鲁克林高地 租房 押金 骗局", "p84_scam", "语义"),
    ("上东区 钓鱼短信 银行账户冻结", "p19_scam", "语义"),
]


def test_retrieval_set_covers_named_and_semantic_queries():
    kinds = {kind for _, _, kind in RETRIEVAL_CASES}
    assert kinds == {"专名", "语义"}, "检索集必须同时覆盖专名查询与语义查询"
    assert len(RETRIEVAL_CASES) >= 10, f"检索集查询数不足 10：{len(RETRIEVAL_CASES)}"


@pytest.mark.parametrize("query,expected", [(q, e) for q, e, _ in RETRIEVAL_CASES])
def test_hybrid_retrieval_top3_hits_expected_report(query, expected, monkeypatch):
    _block_network(monkeypatch)
    top = intel_agent.search(query)
    assert len(top) == intel_agent.TOP_K, f"混合检索应恰好返回 top-{intel_agent.TOP_K}"
    doc_ids = [doc_id for doc_id, _ in top]
    assert expected in doc_ids, (
        f"查询 {query!r} 的 top-{intel_agent.TOP_K} 未命中 {expected}：{doc_ids}"
    )
    scores = [score for _, score in top]
    assert scores == sorted(scores, reverse=True), "RRF 融合分必须降序"


def test_search_result_doc_ids_exist_in_index_meta(monkeypatch):
    _block_network(monkeypatch)
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    known = {d["doc_id"] for d in meta["docs"]}
    top = intel_agent.search("法拉盛 换汇诈骗")
    assert {doc_id for doc_id, _ in top} <= known


# ---------------------------------------------------------------------------
# 2. community_info 字段断言（AC-015 / F7-3 诚实路径：未记载项统一标注）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("precinct", sorted(config_loader.load_config().covered_precincts))
def test_community_info_unrecorded_items_marked(precinct, monkeypatch):
    _block_network(monkeypatch)
    cfg = config_loader.load_config()
    info = intel_agent.build_community_info(precinct, cfg)
    # 知识库未记载的事实（某警区中文警员/逐警区仇恨犯罪明细）→ 统一标注，绝不编造
    assert info["chinese_officer"] == cfg.intel.unverified_label, (
        f"P{precinct} 中文警员项未按 F7-3 标注：{info['chinese_officer']!r}"
    )
    assert info["hate_crime"] == cfg.intel.unverified_label, (
        f"P{precinct} 仇恨犯罪项未按 F7-3 标注：{info['hate_crime']!r}"
    )


@pytest.mark.parametrize("precinct", sorted(config_loader.load_config().covered_precincts))
def test_community_info_structure(precinct, monkeypatch):
    _block_network(monkeypatch)
    info = intel_agent.build_community_info(precinct)
    # 诈骗提醒逐条透出（scam 篇 "### " 小节标题）
    assert len(info["scam_alerts"]) >= 1, "诈骗提醒不得为空"
    assert all(isinstance(a, str) and a.strip() for a in info["scam_alerts"])
    assert any("诈骗" in a for a in info["scam_alerts"]), "诈骗提醒须围绕诈骗主题"
    # 来源：该警区三篇文档 frontmatter 来源 URL 并集
    assert info["sources"], "community_info.sources 不得为空"
    assert all(s.startswith("http") for s in info["sources"])


# ---------------------------------------------------------------------------
# 3. 无官方来源的机构不出现在社区资源列表（F7-4）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("precinct", sorted(config_loader.load_config().covered_precincts))
def test_community_resources_only_official_sources(precinct, monkeypatch):
    _block_network(monkeypatch)
    info = intel_agent.build_community_info(precinct)
    assert info["community_resources"], "社区资源列表不得为空（知识库载有官方机构）"
    for r in info["community_resources"]:
        assert r["name"].strip(), f"资源缺机构名：{r}"
        assert r["source"].startswith("http"), f"资源缺官方来源 URL：{r}"
        assert "phone" not in r, "未核实机构不列电话（不编造未核实字段）"


def test_resource_parser_excludes_orgs_without_official_source():
    """解析级防线：无来源 URL 的机构条目一律跳过，只留有官方来源的。"""
    text = (
        "## 法律援助（只列有官方来源的机构）\n"
        "\n"
        "- 某某华人互助会（无官方来源可核实）。\n"
        "- The Legal Aid Society（官方机构，提供免费法律援助）：https://www.legalaid.org/ 。\n"
    )
    resources = intel_agent._community_resources(text)
    assert [r["name"] for r in resources] == ["The Legal Aid Society"]
    assert resources[0]["source"] == "https://www.legalaid.org/"


# ---------------------------------------------------------------------------
# 4. 未记载/有记载的解析分支与格式漂移防线
# ---------------------------------------------------------------------------


def test_unrecorded_vs_recorded_parsing_branches():
    """未记载 → 统一标注；有记载 → 透出原文（两条分支都不得编造）。"""
    cfg = config_loader.load_config()
    unrecorded = (
        "## 中文服务记载情况（F7-3 诚实路径）\n"
        "\n"
        "- 本警区是否有专职中文警员：**未记载**（录入时无官方来源可核实）。\n"
    )
    assert intel_agent._chinese_officer_status(unrecorded, cfg) == cfg.intel.unverified_label
    recorded = (
        "## 中文服务记载情况\n"
        "\n"
        "- 本警区设有专职中文警员两名（来源：NYPD 官网警局页）。\n"
    )
    status = intel_agent._chinese_officer_status(recorded, cfg)
    assert "未记载" not in status and status, "有记载时应透出原文条目"


def test_hate_crime_unrecorded_branch():
    cfg = config_loader.load_config()
    text = (
        "## 仇恨犯罪记录记载情况\n"
        "\n"
        "- 本知识库未逐警区核对仇恨犯罪逐条记录：**逐警区仇恨犯罪明细：未记载**。\n"
    )
    assert intel_agent._hate_crime_status(text, cfg) == cfg.intel.unverified_label


def test_format_drift_fails_explicitly():
    """知识文档格式漂移（缺小节/缺来源清单）→ IntelFormatError，不静默解析。"""
    with pytest.raises(intel_agent.IntelFormatError):
        intel_agent._section("# 只有标题没有小节\n", "法律援助")
    with pytest.raises(intel_agent.IntelFormatError):
        intel_agent._frontmatter_sources("# 没有 frontmatter\n")
    with pytest.raises(intel_agent.IntelFormatError):
        intel_agent._scam_alert_titles("# 没有小标题\n")


# ---------------------------------------------------------------------------
# 5. 向量侧本地 embedding 模型（离线可跑、零 API 依赖）
# ---------------------------------------------------------------------------


def test_embedding_model_is_local_sentence_transformers():
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["embedding_model"].startswith("sentence-transformers/"), (
        "embedding 必须是本地 sentence-transformers 级模型（禁 API 依赖）"
    )
    assert meta["doc_count"] == 15
    themes = {(d["precinct"], d["theme"]) for d in meta["docs"]}
    cfg = config_loader.load_config()
    assert themes == {(p, t) for p in cfg.covered_precincts for t in ("overview", "scam", "emergency")}


def test_search_is_offline_zero_api(monkeypatch):
    _block_network(monkeypatch)
    top = intel_agent.search("法拉盛 换汇诈骗")
    assert top, "离线混合检索必须有结果"


# ---------------------------------------------------------------------------
# 6. 词汇遵循 CONTEXT.md（混合检索，不用"双路检索"）
# ---------------------------------------------------------------------------


def test_vocabulary_hybrid_retrieval_not_double_channel():
    for path in sorted((REPO_ROOT / "safepass").rglob("*.py")) + sorted(
        (REPO_ROOT / "scripts").rglob("*.py")
    ):
        text = path.read_text(encoding="utf-8")
        assert "双路检索" not in text, f"{path.name} 出现禁用词汇「双路检索」（CONTEXT.md）"
        assert "混合搜索" not in text, f"{path.name} 出现禁用词汇「混合搜索」（CONTEXT.md）"
    assert "混合检索" in (intel_agent.__doc__ or ""), "情报 Agent 模块 docstring 应使用「混合检索」"


# ---------------------------------------------------------------------------
# 7. 唯一接缝集成：SafetyQueryResult 携带 community_info（cassette 固定 LLM 行为）
# ---------------------------------------------------------------------------


class _FailIfCalled:
    """回放路径的底座客户端：被调用即失败（证明 cassette 真的零底层调用）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        raise AssertionError("cassette 回放不应触发任何底层客户端调用")


class _CassetteClient:
    """把调用转发到 chat_with_cassette 的客户端（fc_routing_seam.json：路由+提取）。"""

    def __init__(self, inner, path: Path):
        self._inner = inner
        self._path = path
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return chat_with_cassette(self._inner, self._path, messages, model=model, **kwargs)


def test_execute_query_safety_result_carries_community_info():
    cfg = config_loader.load_config()
    inner = _FailIfCalled()
    client = _CassetteClient(inner, CASSETTE_SEAM)
    reset_cassette_cursor(CASSETTE_SEAM)

    result = execute_query("上东区晚上安全吗？", llm_client=client)

    assert inner.calls == 0, "cassette 回放必须零底层调用（离线可重复）"
    assert client.calls == 2, "接缝 LLM 路径 = 路由 1 次 + 三维提取 1 次"
    assert result.type == "safety"
    info = result.community_info
    assert info is not None, "覆盖区内安全查询必须携带 community_info（AC-015）"
    # 知识库未记载的中文警员项输出统一标注（F7-3 诚实路径）
    assert info["chinese_officer"] == cfg.intel.unverified_label
    assert info["hate_crime"] == cfg.intel.unverified_label
    assert info["scam_alerts"], "诈骗提醒不得为空"
    assert all(r["source"].startswith("http") for r in info["community_resources"])
    assert info["sources"], "来源清单不得为空"

