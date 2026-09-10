"""issue 50 / G2 建议路径对照说明：模板 → Skill+检索，评级不变式。

对应 .scratch/safepass-wave2-third-knife/issues/15-g2-suggestion-path.md：
    1. 对照页存在且 README 可链到；
    2. 写清曾经配置模板建议，现在 Skill + 检索；
    3. 写明评级 / 可信度 / 越界仍零 LLM；
    4. 写明画像只本机加权。

接缝：文档页 docs/suggestion-path.md（约定关键词对账即可，不锁散文版式）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "suggestion-path.md"
README_PATH = REPO_ROOT / "README.md"


def _doc() -> str:
    assert DOC_PATH.is_file(), "缺少 docs/suggestion-path.md（G2 建议路径对照）"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert text.strip(), "G2 对照页不得为空"
    return text


def test_suggestion_path_page_exists():
    assert DOC_PATH.is_file()
    assert len(_doc()) > 200


def test_readme_links_to_suggestion_path_page():
    readme = README_PATH.read_text(encoding="utf-8")
    assert "docs/suggestion-path.md" in readme
    assert "建议路径" in readme or "模板" in readme


def test_page_covers_template_to_skill_and_retrieval():
    """曾用配置模板建议 → 现用 Skill + 检索。"""
    text = _doc()
    assert "模板" in text
    assert "Skill" in text
    assert "检索" in text
    # 成长路径：前后对照，不是只写现状（须点名「曾经/曾用」，不可仅靠「配置」过门）
    assert ("曾经" in text or "曾用" in text), "对照页须写清曾经/曾用模板路径"
    assert "配置" in text


def test_page_states_rating_invariants_zero_llm():
    """评级 / 可信度 / 越界仍零 LLM（安全评级不变式）。"""
    text = _doc()
    assert "评级" in text
    assert "可信度" in text
    assert "越界" in text
    assert "零 LLM" in text
    assert "纯函数" in text or "不参与" in text


def test_page_states_profile_local_weighting_only():
    """画像只本机加权，不进模型。"""
    text = _doc()
    assert "画像" in text
    assert "本机" in text
    assert "加权" in text
    assert "不进" in text or "不发送" in text or "永不离开" in text
    # 指针文件真实存在（与 N6 对账习惯对齐）
    assert "test_a5_profile_local" in text
    assert (REPO_ROOT / "tests" / "test_a5_profile_local.py").is_file()
    assert "adr/0003" in text.replace("\\", "/")
    assert (REPO_ROOT / "docs" / "adr" / "0003-suggestion-generation-architecture.md").is_file()
