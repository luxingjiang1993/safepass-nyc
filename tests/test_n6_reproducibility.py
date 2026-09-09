"""issue 38 / N6 版本钉一页：审阅者换机器不漂说明书。

对应 .scratch/safepass-wave2-third-knife/issues/03-n6-reproducibility.md：
    1. 独立页 docs/reproducibility.md 存在，README 链过去；
    2. 写清依赖锁定、pickle protocol=5、embedding 标识、FAISS ASCII、cassette/judge 指针；
    3. 不写生产密钥、不重做 N3 一键复现命令；
    4. 页内指针文件真实存在，钉值与独立事实源对账。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "reproducibility.md"
README_PATH = REPO_ROOT / "README.md"
META_PATH = REPO_ROOT / "fixtures" / "index" / "meta.json"
BUILD_INDEX = REPO_ROOT / "scripts" / "build_index.py"
CONFIG_PATH = REPO_ROOT / "config" / "app.yaml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"DASHSCOPE_API_KEY\s*=\s*\S+"),
    re.compile(r"LLM_API_KEY\s*=\s*\S+"),
)


def _doc_text() -> str:
    assert DOC_PATH.exists(), f"缺少独立复现说明页 {DOC_PATH.as_posix()}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_n6_reproducibility_page_exists():
    assert DOC_PATH.is_file()
    assert len(_doc_text()) > 200


def test_readme_links_to_reproducibility_page():
    readme = README_PATH.read_text(encoding="utf-8")
    assert "docs/reproducibility.md" in readme
    assert "换机器不漂" in readme or "版本钉" in readme or "可复现" in readme


def test_page_covers_required_pins():
    text = _doc_text()
    assert "requirements.txt" in text
    assert "protocol=5" in text
    assert "ASCII" in text
    assert "FAISS" in text
    assert "cassette" in text.lower()
    assert "judge" in text.lower()


def test_page_pins_match_independent_sources():
    """钉值来自索引 meta / 构建脚本 / 配置，不由本页自说自话。"""
    text = _doc_text()
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    model = meta["embedding_model"]
    assert model in text, f"页须钉死 embedding 标识 {model}"

    build = BUILD_INDEX.read_text(encoding="utf-8")
    assert "protocol=5" in build
    assert f'EMBEDDING_MODEL = "{model}"' in build or f"EMBEDDING_MODEL = '{model}'" in build

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    eval_cfg = cfg["eval"]
    assert eval_cfg["judge_model"] in text
    for key in ("cassette", "cassette_template", "cassette_skill"):
        rel = eval_cfg[key].replace("\\", "/")
        assert rel in text, f"页须指向 {rel}"
        assert (REPO_ROOT / rel).is_file(), f"指针文件不存在：{rel}"
    versions = eval_cfg["prompt_versions"]
    for name in versions.values():
        assert name in text, f"页须钉死 judge 提示词版本 {name}"

    req = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^sentence-transformers==", req, re.M)
    assert "sentence-transformers==" in text
    assert "faiss-cpu==" in text


def test_page_index_pointer_is_ascii_relative_path():
    text = _doc_text()
    assert "fixtures/index" in text
    index_dir = REPO_ROOT / "fixtures" / "index"
    assert index_dir.is_dir()
    rel = index_dir.relative_to(REPO_ROOT).as_posix()
    assert rel.isascii(), "索引目录相对仓库根必须是纯 ASCII"
    for name in ("docs.faiss", "bm25.pkl", "meta.json"):
        assert (index_dir / name).is_file()
        assert name.isascii()
        assert name in text


def test_page_has_no_secrets_and_does_not_replace_n3():
    text = _doc_text()
    for pat in _SECRET_PATTERNS:
        assert not pat.search(text), f"复现页不得写入密钥形态：{pat.pattern}"
    # N3 已收口：本页只指向既有审阅者路径，不另起 demo 入口
    assert "审阅者路径" in text
    assert "demo_queries.py" in text
    assert "scripts/one_command" not in text
    assert "afk-ralph" not in text
