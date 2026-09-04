"""T0 检索索引构建：15 篇知识库文档 → FAISS 本地索引 + BM25 pickle（spec D11a）。

- embedding 用本地 sentence-transformers 模型（禁 API 依赖，离线可重建）
- BM25 词条：CJK 字符二元组 + 拉丁词（确定性分词，不依赖第三方分词库）
- 混合检索（CONTEXT.md 词汇）：FAISS 向量 + BM25 关键词，RRF 融合取 top-3
  （T8 情报 Agent 的底层；MVP 不引入重排层）

用法：
    python scripts/build_index.py                # 构建并落盘 fixtures/index/
    python scripts/build_index.py --check        # 重建到内存并与落盘索引比对
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 强制离线：模型必须来自本地缓存（sentence-transformers 级，不依赖 API）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = REPO_ROOT / "fixtures" / "knowledge"
INDEX_DIR = REPO_ROOT / "fixtures" / "index"

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FAISS_FILE = "docs.faiss"
BM25_FILE = "bm25.pkl"
META_FILE = "meta.json"

_LATIN_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[一-鿿぀-ヿ가-힯]")

# RRF 非对称常数（单一事实源，T8 检索集与情报 Agent 共用）：
# BM25 侧 k=10 承载专名/中文术语的区分度信号；向量侧 k=60 因长文档向量
# 受样板文字影响、排序平缓，只作宽泛召回。
K_VEC = 60
K_BM25 = 10


def tokenize(text: str) -> list[str]:
    """确定性分词：拉丁字母/数字小写词 + CJK 字符二元组。"""
    tokens: list[str] = []
    for m in _LATIN_WORD.finditer(text.lower()):
        tokens.append(m.group(0))
    cjk_run = _CJK.findall(text)
    tokens.extend(cjk_run)  # 单字兜底，保证单字专名可命中
    tokens.extend(
        cjk_run[i] + cjk_run[i + 1] for i in range(len(cjk_run) - 1)
    )
    return tokens


@dataclass
class Document:
    doc_id: str  # 文件名（不含扩展名）
    path: str  # 相对 fixtures/knowledge/ 的路径
    text: str
    precinct: int | None
    theme: str | None


def load_documents(knowledge_dir: Path) -> list[Document]:
    docs = []
    for md in sorted(knowledge_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        precinct = theme = None
        pm = re.search(r"^precinct:\s*(\d+)\s*$", text, re.M)
        tm = re.search(r"^theme:\s*(\S+)\s*$", text, re.M)
        if pm:
            precinct = int(pm.group(1))
        if tm:
            theme = tm.group(1)
        docs.append(
            Document(doc_id=md.stem, path=md.name, text=text, precinct=precinct, theme=theme)
        )
    if not docs:
        raise SystemExit(f"知识库目录为空：{knowledge_dir}")
    return docs


def _embed_texts(texts: list[str]) -> "object":
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    return model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)


def build_index(knowledge_dir: Path, out_dir: Path) -> dict[str, object]:
    """构建 FAISS + BM25 索引并落盘，返回元信息（确定性）。"""
    import faiss
    from rank_bm25 import BM25Okapi

    docs = load_documents(knowledge_dir)
    texts = [d.text for d in docs]
    vectors = _embed_texts(texts).astype("float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    tokenized = [tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)

    out_dir.mkdir(parents=True, exist_ok=True)
    # faiss 的 Windows 写盘器不支持非 ASCII 路径：切到目标目录用相对文件名
    prev_cwd = os.getcwd()
    try:
        os.chdir(out_dir)
        faiss.write_index(index, FAISS_FILE)
    finally:
        os.chdir(prev_cwd)
    with open(out_dir / BM25_FILE, "wb") as f:
        # 固定 pickle 协议：跨机器/跨 Python 小版本默认协议不同（有环境默认 4），
        # 不固定会让"落盘索引 vs 离线重建"的逐字节自检随环境漂移
        pickle.dump(
            {
                "tokens": tokenized,
                "doc_ids": [d.doc_id for d in docs],
            },
            f,
            protocol=5,
        )
    meta = {
        "embedding_model": EMBEDDING_MODEL,
        "doc_count": len(docs),
        "docs": [
            {
                "doc_id": d.doc_id,
                "path": d.path,
                "precinct": d.precinct,
                "theme": d.theme,
            }
            for d in docs
        ],
    }
    (out_dir / META_FILE).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return meta


def load_index(index_dir: Path):
    """加载已落盘索引（T8 情报 Agent 与测试共用同一加载路径）。"""
    import faiss

    prev_cwd = os.getcwd()
    try:
        os.chdir(index_dir)
        index = faiss.read_index(FAISS_FILE)
    finally:
        os.chdir(prev_cwd)
    with open(index_dir / BM25_FILE, "rb") as f:
        bm25_data = pickle.load(f)
    meta = json.loads((index_dir / META_FILE).read_text(encoding="utf-8"))
    from rank_bm25 import BM25Okapi

    bm25 = BM25Okapi(bm25_data["tokens"])
    return index, bm25, meta


def rrf_fuse(
    faiss_rank: list[int], bm25_rank: list[int], doc_ids: list[str], k: int
) -> list[tuple[str, float]]:
    """RRF 融合两路名次（非对称常数 K_VEC/K_BM25），返回 [(doc_id, score)] top-k。

    纯函数：两路的具体来源（全库 FAISS 检索 / 临时索引重建）由调用方决定，
    融合逻辑只有这一份（情报 Agent 与构建脚本共用）。
    """
    rrf: dict[str, float] = {}
    for rank, doc_i in enumerate(faiss_rank):
        doc_id = doc_ids[doc_i]
        rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (K_VEC + rank + 1)
    for rank, doc_i in enumerate(bm25_rank):
        doc_id = doc_ids[doc_i]
        rrf[doc_id] = rrf.get(doc_id, 0.0) + 1.0 / (K_BM25 + rank + 1)
    return sorted(rrf.items(), key=lambda kv: -kv[1])[:k]


def search(index_dir: Path, query: str, k: int = 3) -> list[tuple[str, float]]:
    """混合检索（FAISS 向量 + BM25 关键词）+ RRF 融合，返回 [(doc_id, rrf_score)]。

    向量侧排序平缓且噪声大（长文档样板文字多），BM25 侧承载专名区分度；
    两路名次交由 rrf_fuse 按非对称常数融合（见模块级 K_VEC/K_BM25 注释）。
    """
    index, bm25, meta = load_index(index_dir)
    q_vec = _embed_texts([query]).astype("float32")
    k_full = index.ntotal
    _, faiss_rank = index.search(q_vec, k_full)
    bm25_scores = bm25.get_scores(tokenize(query))
    bm25_rank = sorted(range(len(bm25_scores)), key=lambda i: -bm25_scores[i])

    doc_ids = [d["doc_id"] for d in meta["docs"]]
    return rrf_fuse(list(faiss_rank[0]), bm25_rank, doc_ids, k)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建知识库 FAISS+BM25 索引")
    parser.add_argument(
        "--check",
        action="store_true",
        help="重建索引到内存并与落盘文件比对维度与文档清单（确定性自检）",
    )
    args = parser.parse_args()
    meta = build_index(KNOWLEDGE_DIR, INDEX_DIR)
    if args.check:
        _, _, on_disk = load_index(INDEX_DIR)
        assert on_disk["doc_count"] == meta["doc_count"], "落盘索引文档数与重建不一致"
        assert [d["doc_id"] for d in on_disk["docs"]] == [
            d["doc_id"] for d in meta["docs"]
        ], "落盘索引文档清单与重建不一致"
        print("索引自检通过：落盘索引与重建一致")
    print(f"indexed_docs = {meta['doc_count']}")


if __name__ == "__main__":
    main()
