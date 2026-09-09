"""N2 套件隔离：对照回放不得进入默认行为基线。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = REPO_ROOT / "tests" / "conftest.py"


def test_n2_three_column_suite_is_under_eval_collect_ignore():
    """默认 python -m pytest tests/ -q 不收集 tests/eval（含 N2 回放）。"""
    text = CONFTEST.read_text(encoding="utf-8")
    assert 'collect_ignore = ["eval"]' in text
    assert (REPO_ROOT / "tests" / "eval" / "test_n2_three_column.py").exists()
    assert (REPO_ROOT / "tests" / "eval" / "n2_runner.py").exists()
