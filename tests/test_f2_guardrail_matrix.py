"""issue 48 / F2 Guardrail 覆盖矩阵：输入类型 → 形态，链真实测试/金标 ID。

对应 .scratch/safepass-wave2-third-knife/issues/13-f2-guardrail-matrix.md：
    1. 矩阵覆盖紧急、防线拒绝、越界降级、覆盖内安全；
    2. 链到真实测试或金标 ID（含 B3 五类与 N1 报表）；
    3. 不把 N1 与 B3 夹具合并成一份。

接缝：文档页 docs/f2-guardrail-matrix.md（约定小节与 ID 对账即可，不锁散文版式）。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "f2-guardrail-matrix.md"
N1_ATTACKS = REPO_ROOT / "fixtures" / "eval" / "injection_attacks_v1.json"
B3_CASES = REPO_ROOT / "fixtures" / "eval" / "adversarial_goldens_v1.json"
GOLDEN = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
TESTS_DIR = REPO_ROOT / "tests"

B3_CATEGORIES = ("bias", "weapon", "panic", "coverage_evasion", "platitude")
FORMS = ("emergency", "guardrail", "degraded", "safety")
_ID_RE = re.compile(r"\b(B3-\d+|N1-\d+|G\d{2})\b")
_TEST_RE = re.compile(r"\b(test_[a-z0-9_]+)\b(?!\.py)")


def _doc() -> str:
    assert DOC_PATH.is_file(), "缺少 docs/f2-guardrail-matrix.md（F2 覆盖矩阵）"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert text.strip(), "F2 矩阵页不得为空"
    return text


def _collect_test_names() -> set[str]:
    names: set[str] = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def test_matrix_page_exists():
    assert DOC_PATH.is_file()
    assert len(_doc()) > 200


def test_matrix_covers_four_forms():
    text = _doc()
    assert "## 约定" in text
    for form in FORMS:
        assert form in text, f"矩阵须覆盖形态 {form}"
    assert "紧急" in text
    assert "防线" in text
    assert "降级" in text
    assert "越界" in text
    assert "安全" in text


def test_links_n1_report_and_b3_fixture_without_merging():
    text = _doc()
    assert "n1-injection-report.md" in text
    assert "b3-adversarial-report.md" in text
    assert "injection_attacks_v1.json" in text
    assert "adversarial_goldens_v1.json" in text
    assert N1_ATTACKS.is_file() and B3_CASES.is_file()
    assert N1_ATTACKS.resolve() != B3_CASES.resolve()
    assert N1_ATTACKS.name != B3_CASES.name
    lowered = text.replace(" ", "")
    assert "injection_attacks_v1.json=adversarial_goldens_v1.json" not in lowered


def test_b3_five_categories_linked_to_real_ids():
    text = _doc()
    cases = json.loads(B3_CASES.read_text(encoding="utf-8"))["cases"]
    by_cat: dict[str, set[str]] = {c: set() for c in B3_CATEGORIES}
    for case in cases:
        by_cat[case["category"]].add(case["id"])
    for category in B3_CATEGORIES:
        assert category in text, f"矩阵须点名 B3 类别 {category}"
        linked = set(_ID_RE.findall(text)) & by_cat[category]
        assert linked, f"矩阵须链到 {category} 的真实 B3 ID，夹具有 {sorted(by_cat[category])[:3]}…"


def test_linked_golden_and_n1_ids_exist():
    text = _doc()
    linked = set(_ID_RE.findall(text))
    n1_ids = {a["id"] for a in json.loads(N1_ATTACKS.read_text(encoding="utf-8"))["attacks"]}
    b3_ids = {c["id"] for c in json.loads(B3_CASES.read_text(encoding="utf-8"))["cases"]}
    g_ids = {e["id"] for e in json.loads(GOLDEN.read_text(encoding="utf-8"))["entries"]}
    known = n1_ids | b3_ids | g_ids
    unknown = linked - known
    assert unknown == set(), f"矩阵链到不存在的金标 ID：{sorted(unknown)}"
    assert linked & n1_ids, "矩阵须至少链一条真实 N1 ID"
    assert linked & g_ids, "矩阵须至少链一条主金标 ID（覆盖内或越界）"


def test_linked_pytest_names_exist():
    text = _doc()
    mentioned = {n for n in _TEST_RE.findall(text) if n.startswith("test_")}
    assert mentioned, "矩阵须链到真实 pytest 函数名"
    existing = _collect_test_names()
    missing = mentioned - existing
    assert missing == set(), f"矩阵链到不存在的测试：{sorted(missing)}"


def test_each_form_has_an_anchor():
    """四形态各自至少有一条可核对的锚：测试名或金标 ID。"""
    text = _doc()
    linked_ids = set(_ID_RE.findall(text))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["entries"]
    b3 = json.loads(B3_CASES.read_text(encoding="utf-8"))["cases"]
    form_ids = {
        "guardrail": {c["id"] for c in b3 if c["expect"]["form"] == "guardrail"},
        "degraded": {e["id"] for e in golden if e["expect"]["type"] == "degraded"}
        | {c["id"] for c in b3 if c["expect"]["form"] == "degraded"},
        "safety": {e["id"] for e in golden if e["expect"]["type"] == "safety"}
        | {c["id"] for c in b3 if c["expect"]["form"] == "safety"},
    }
    n1 = json.loads(N1_ATTACKS.read_text(encoding="utf-8"))["attacks"]
    for attack in n1:
        kind = attack["category"]
        if kind == "harmful_advice":
            form_ids["guardrail"].add(attack["id"])
        elif kind == "coverage_evasion":
            form_ids["degraded"].add(attack["id"])

    tests = set(_TEST_RE.findall(text))
    assert "test_neg008_emergency_keywords_trigger_static_branch" in tests
    assert "test_emergency_layer2_not_shadowed_by_weapon_guardrail" in tests
    assert "test_neg003_bias_questions_refused_with_structural_pivot" in tests
    assert "test_neg004_weapon_questions_refused_with_legal_paths" in tests
    assert linked_ids & form_ids["degraded"], "降级行须链越界金标"
    assert linked_ids & form_ids["safety"], "安全行须链覆盖内金标"
