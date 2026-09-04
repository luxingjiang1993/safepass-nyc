"""情报 Agent（spec D2 / CONTEXT.md 混合检索）。

混合检索 = FAISS 向量检索（语义，本地 embedding 模型）+ BM25 关键词检索
（专名/犯罪术语兜底），RRF 融合取 top-3（非对称常数与融合逻辑的单一事实源
在 scripts.build_index），MVP 不引入重排层。检索 15 篇预计算安全报告
（含华人特定注意事项），为 community_info 提供语境。

两个对外入口：
    search(query, k=TOP_K)             — 混合检索，返回 ((doc_id, rrf_score), ...)
                                           按融合分降序（检索集的断言对象）
    build_community_info(precinct, cfg) — 警区锚定的 community_info 装配：
                                           该警区三主题知识文档（overview/scam/
                                           emergency）确定性解析，零 LLM、零编造。

community_info 结构（SafetyQueryResult 横切字段，dict）：
    hate_crime          反亚裔仇恨犯罪记载（overview 篇"仇恨犯罪记录记载情况"节；
                        未记载 → 统一标注，不编造数字或逐条记录）
    scam_alerts         华人常见诈骗提醒（scam 篇 "### " 小节标题逐条透出）
    chinese_officer     中文警员/中文报案协助记载（emergency 篇"中文服务记载情况"节，
                        F7-3 诚实路径：未记载 → 统一标注）
    community_resources 社区组织/法律援助/移民服务资源——只收录带来源 URL 的条目
                        （无官方来源的机构一律不列出，F7-4；不附带未核实字段）
    sources             该警区三篇文档 frontmatter 来源 URL 的并集（排序去重）

统一标注的措辞（默认"未核实到"）是集中配置 intel.unverified_label（F7-3 诚实
路径话术单一事实源）。装配自检：四个信息面非空、每条资源必须带 http(s) 官方
来源、未记载标注非空——违反即明确失败（同 output_pipeline 装配自检思路），
绝不带病透出契约。

向量侧全程本地 sentence-transformers 模型（HF_HUB_OFFLINE，模型名以落盘索引
meta 为准），测试离线可跑、零 API 依赖。知识文档的 frontmatter/小节形态由
tests/test_fixtures.py 锁定，格式漂移在此处抛 IntelFormatError 明确失败。
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from safepass import config_loader
from scripts import build_index as bi

# fixtures 相对本文件：safepass/intel_agent.py -> 项目根/fixtures/
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_DIR = _REPO_ROOT / "fixtures" / "index"
KNOWLEDGE_DIR = _REPO_ROOT / "fixtures" / "knowledge"

# RRF 融合取 top-3（spec D2，MVP 不引入重排层；spec 固定结构常量，非业务数字，
# 不进集中配置——同 output_pipeline.SUGGESTIONS_MIN/MAX 的处理）
TOP_K = 3

# 知识文档的 frontmatter sources 清单与小节形态（fixture 格式由 test_fixtures 锁定）
_FRONTMATTER_SOURCES = re.compile(r"^sources:\s*\n((?:\s*-\s*\S.*\n?)+)", re.M)
_URL = re.compile(r'https?://[^\s）)。"\']+')


class IntelFormatError(RuntimeError):
    """知识文档/索引与锁定形态不一致（fixture 损坏，明确失败不静默）。"""


@functools.lru_cache(maxsize=4)
def _index_bundle(index_dir: str) -> tuple[Any, Any, dict[str, Any]]:
    """已落盘索引三件套（FAISS + BM25 + meta），按索引目录缓存。"""
    return bi.load_index(Path(index_dir))


@functools.lru_cache(maxsize=1)
def _embedding_model() -> Any:
    """本地 embedding 模型（禁 API 依赖，离线加载，进程内缓存一次性冷启动）。"""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(bi.EMBEDDING_MODEL)


def search(
    query: str, index_dir: Path | None = None, k: int = TOP_K
) -> tuple[tuple[str, float], ...]:
    """混合检索（CONTEXT.md 词汇）：FAISS 向量 + BM25 关键词，RRF 融合取 top-k。

    返回 ((doc_id, rrf_score), ...)，按融合分降序。向量侧用本地 embedding 模型
    （离线、零 API 依赖），RRF 融合与 scripts.build_index 共用同一纯函数
    rrf_fuse（非对称常数 K_VEC/K_BM25 只此一份）。
    """
    import numpy as np

    index, bm25, meta = _index_bundle(str(index_dir or DEFAULT_INDEX_DIR))
    q_vec = np.asarray(
        _embedding_model().encode([query], normalize_embeddings=True, convert_to_numpy=True),
        dtype="float32",
    )
    _, faiss_rank = index.search(q_vec, index.ntotal)
    bm25_scores = bm25.get_scores(bi.tokenize(query))
    bm25_rank = sorted(range(len(bm25_scores)), key=lambda i: -bm25_scores[i])
    doc_ids = [d["doc_id"] for d in meta["docs"]]
    return tuple(bi.rrf_fuse(list(faiss_rank[0]), bm25_rank, doc_ids, k))


def build_community_info(
    precinct: int, cfg: config_loader.AppConfig | None = None
) -> dict[str, Any]:
    """警区锚定的 community_info 装配（AC-015，F7-3/F7-4 诚实路径）。

    该警区三主题知识文档确定性解析，零 LLM、零编造：未记载事实 → 统一标注
    （intel.unverified_label）；社区资源只收录带官方来源 URL 的机构。
    缺主题文档/小节/来源清单 = 索引或 knowledge 漂移，抛 IntelFormatError。
    """
    if cfg is None:
        cfg = config_loader.get_config()
    meta = _index_bundle(str(DEFAULT_INDEX_DIR))[2]
    themes = _doc_ids_for_precinct(meta, precinct)
    overview = _doc_text(themes["overview"])
    scam = _doc_text(themes["scam"])
    emergency = _doc_text(themes["emergency"])
    info: dict[str, Any] = {
        "hate_crime": _hate_crime_status(overview, cfg),
        "scam_alerts": list(_scam_alert_titles(scam)),
        "chinese_officer": _chinese_officer_status(emergency, cfg),
        "community_resources": [dict(r) for r in _community_resources(emergency)],
        "sources": sorted(
            set(
                _frontmatter_sources(overview)
                + _frontmatter_sources(scam)
                + _frontmatter_sources(emergency)
            )
        ),
    }
    _validate(info)
    return info


# ---------------------------------------------------------------------------
# 知识文档确定性解析（fixture 格式由 tests/test_fixtures.py 锁定）
# ---------------------------------------------------------------------------


def _doc_ids_for_precinct(meta: dict[str, Any], precinct: int) -> dict[str, str]:
    """该警区的 {theme: doc_id}；缺任一主题 = 索引/knowledge 漂移，明确失败。"""
    themes = {d["theme"]: d["doc_id"] for d in meta["docs"] if d["precinct"] == precinct}
    missing = {"overview", "scam", "emergency"} - themes.keys()
    if missing:
        raise IntelFormatError(f"警区 {precinct} 缺知识文档主题：{sorted(missing)}")
    return themes


def _doc_text(doc_id: str) -> str:
    path = KNOWLEDGE_DIR / f"{doc_id}.md"
    if not path.exists():
        raise IntelFormatError(f"知识文档缺失：{path}")
    return path.read_text(encoding="utf-8")


def _section(text: str, heading_keyword: str) -> str:
    """提取「## <含 heading_keyword>」小节正文（到下一个「## 」标题为止）。"""
    lines = text.splitlines()
    start = next(
        (
            i + 1
            for i, line in enumerate(lines)
            if line.startswith("## ") and heading_keyword in line
        ),
        None,
    )
    if start is None:
        raise IntelFormatError(f"知识文档缺「## …{heading_keyword}…」小节")
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _bullets(section_text: str) -> list[str]:
    return [line[2:].strip() for line in section_text.splitlines() if line.startswith("- ")]


def _clean_inline(text: str) -> str:
    return text.replace("**", "").strip()


def _hate_crime_status(overview_text: str, cfg: config_loader.AppConfig) -> str:
    """反亚裔仇恨犯罪记载（overview 篇"仇恨犯罪记录记载情况"节）。

    未记载 → 统一标注（绝不编造逐警区数字或逐条记录）；有记载时逐条透出
    该节记载内容（原文 bullet 拼接，不加任何推断）。
    """
    body = _section(overview_text, "仇恨犯罪")
    if "未记载" in body:
        return cfg.intel.unverified_label
    recorded = [b for b in _bullets(body) if b and "未记载" not in b]
    if not recorded:
        raise IntelFormatError("仇恨犯罪记载情况小节既无记载也无「未记载」标注")
    return "；".join(_clean_inline(b) for b in recorded)


def _scam_alert_titles(scam_text: str) -> tuple[str, ...]:
    """华人常见诈骗提醒（scam 篇 "### " 小节标题逐条透出，原文不加推断）。"""
    alerts = tuple(
        line.lstrip("#").strip() for line in scam_text.splitlines() if line.startswith("### ")
    )
    if not alerts:
        raise IntelFormatError("诈骗提醒篇缺「### 」小节标题")
    return alerts


def _chinese_officer_status(emergency_text: str, cfg: config_loader.AppConfig) -> str:
    """中文警员/中文报案协助记载（emergency 篇"中文服务记载情况"节，F7-3）。

    未记载 → 统一标注（绝不编造中文警员信息）；有记载时透出原文条目。
    """
    body = _section(emergency_text, "中文服务")
    line = next((b for b in _bullets(body) if "中文警员" in b), None)
    if line is None:
        raise IntelFormatError("中文服务记载情况小节缺中文警员条目")
    if "未记载" in line:
        return cfg.intel.unverified_label
    return _clean_inline(line)


def _community_resources(emergency_text: str) -> tuple[dict[str, str], ...]:
    """社区组织/法律援助/移民服务资源——只收录带来源 URL 的条目（F7-4）。

    无官方来源的机构一律跳过、不出现在列表；条目只有机构名与来源，
    不附带未核实字段（电话等），绝不编造。
    """
    body = _section(emergency_text, "法律援助")
    resources: list[dict[str, str]] = []
    for bullet in _bullets(body):
        url_m = _URL.search(bullet)
        if url_m is None:
            continue  # 无官方来源的机构不出现在社区资源列表
        url = url_m.group(0)
        before = _clean_inline(bullet).split(url, 1)[0]
        name = re.split(r"[（(:：]", before, maxsplit=1)[0].strip(" ，。、·")
        if not name:
            raise IntelFormatError(f"资源条目缺机构名：{bullet}")
        resources.append({"name": name, "source": url})
    return tuple(resources)


def _frontmatter_sources(text: str) -> tuple[str, ...]:
    """知识文档 frontmatter sources 清单中的 URL（缺清单/URL = 漂移，明确失败）。"""
    m = _FRONTMATTER_SOURCES.search(text)
    if m is None:
        raise IntelFormatError("知识文档缺 frontmatter sources 清单")
    urls = tuple(u.group(0) for u in _URL.finditer(m.group(1)))
    if not urls:
        raise IntelFormatError("sources 清单缺来源 URL")
    return urls


# ---------------------------------------------------------------------------
# 装配自检（违反即明确失败，绝不带病透出契约）
# ---------------------------------------------------------------------------


def _validate(info: dict[str, Any]) -> None:
    """community_info 装配自检（AC-015 结构断言的装配侧防线）。"""
    if not str(info["hate_crime"]).strip():
        raise IntelFormatError("community_info.hate_crime 为空")
    if not str(info["chinese_officer"]).strip():
        raise IntelFormatError("community_info.chinese_officer 为空")
    if not info["scam_alerts"] or any(not str(a).strip() for a in info["scam_alerts"]):
        raise IntelFormatError("community_info.scam_alerts 为空或含空条目")
    for r in info["community_resources"]:
        if not str(r.get("name", "")).strip() or not str(r.get("source", "")).startswith(
            "http"
        ):
            raise IntelFormatError(f"社区资源缺机构名或官方来源：{r}")
    if not info["sources"]:
        raise IntelFormatError("community_info.sources 为空")
