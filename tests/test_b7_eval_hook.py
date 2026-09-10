"""B7 建议变更回归门壳：文档强制命令 + 默认基线仍不收集 L2。

本票不做「故意改坏 prompt → 红」满门闩（第 3 波）。只锁挂钩存在：
标记名、强制命令字面量、collect_ignore、L2 文件带标且 N2 不带标。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
L2_CMD = "python -m pytest tests/eval -m l2 -q"


def test_default_baseline_still_ignores_eval_dir():
    """默认 python -m pytest tests/ -q 因 collect_ignore 不收集 L2。"""
    text = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'collect_ignore = ["eval"]' in text


def test_pytest_ini_declares_l2_marker():
    """eval 标记命令的挂钩 = pytest.ini 的 l2 marker。"""
    text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "l2:" in text
    assert "tests/eval -m l2" in text


def test_docs_mandate_l2_subset_command():
    """宪法 / agent 入口 / README 都写明强制命令，且写清默认基线不收集 L2。"""
    for rel in ("CLAUDE.md", "AGENTS.md", "README.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert L2_CMD in text, f"{rel} 缺少 B7 强制命令 {L2_CMD}"
        assert "collect_ignore" in text, f"{rel} 须写明默认基线仍不收集 L2"


def test_l2_marker_covers_l2_files_not_n2():
    """-m l2 是子集：L2 金标/evaluator 带标，N2 对照不带标。"""
    l2_files = (
        REPO_ROOT / "tests" / "eval" / "test_l2_golden_set.py",
        REPO_ROOT / "tests" / "eval" / "test_evaluators.py",
    )
    n2_files = (
        REPO_ROOT / "tests" / "eval" / "test_n2_three_column.py",
        REPO_ROOT / "tests" / "eval" / "test_n2a_subset_and_scorers.py",
    )
    for path in l2_files:
        text = path.read_text(encoding="utf-8")
        assert "pytest.mark.l2" in text, f"{path.name} 应带 l2 标记"
    for path in n2_files:
        text = path.read_text(encoding="utf-8")
        assert "pytest.mark.l2" not in text, f"{path.name} 不得带 l2 标记（N2 不是 B7 子集）"
