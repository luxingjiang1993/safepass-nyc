"""issue 37 / B3 对抗金标专表：偏见、武器、恐慌、越界编造、套话。

对应 .scratch/safepass-wave2-third-knife/issues/02-b3-adversarial-goldens.md：
    1. 五类 × ≥10 条新建用例；ID 与 N1、主金标零交集；
    2. 期望形态为防线拒绝 / 诚实降级 / 紧急 / 合法安全结果之一；
    3. 安全路径上安全评级仍只由确定性引擎写出；
    4. 负向：放松对应防线 → 该类至少一条红；
    5. 独立报表链到本夹具，不把用例并进 N1 文件。

接缝：唯一接缝 execute_query（经 adversarial_report → injection_report.run_case）。
全程离线：攻击方 LLM = fixture 攻陷脚本 fake，零 API / 零 cassette。
"""

from __future__ import annotations

import json
import socket
from collections import Counter
from pathlib import Path

import pytest

import adversarial_report
from safepass import config_loader

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
N1_ATTACKS_PATH = REPO_ROOT / "fixtures" / "eval" / "injection_attacks_v1.json"

CASES = adversarial_report.load_cases()
LEGAL_FORMS = frozenset({"guardrail", "degraded", "emergency", "safety"})


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """对抗金标必须全程离线（N1 同口径）。"""

    def _no_connect(*args, **kwargs):
        raise AssertionError("B3 对抗金标不得访问网络（fake 客户端，零 API）")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: _no_connect())


@pytest.fixture(scope="module")
def normal_outcomes() -> dict[str, adversarial_report.CaseOutcome]:
    return {o.id: o for o in adversarial_report.run_suite(CASES)}


# ---------------------------------------------------------------------------
# 1. 规模、命名空间、分表
# ---------------------------------------------------------------------------


def test_five_categories_at_least_ten_each():
    counts = Counter(c["category"] for c in CASES)
    assert set(counts) == set(adversarial_report.CATEGORY_LABELS), (
        f"五类漂移：{set(counts) ^ set(adversarial_report.CATEGORY_LABELS)}"
    )
    for category, n in counts.items():
        assert n >= 10, f"{category} 仅 {n} 条，低于每类 10 条"


def test_ids_disjoint_from_n1_and_main_golden_set():
    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    n1 = json.loads(N1_ATTACKS_PATH.read_text(encoding="utf-8"))
    golden_ids = {e["id"] for e in golden["entries"]}
    n1_ids = {a["id"] for a in n1["attacks"]}
    b3_ids = {c["id"] for c in CASES}
    assert b3_ids and all(i.startswith("B3-") for i in b3_ids)
    assert not (b3_ids & golden_ids), "B3 与主金标 ID 相交"
    assert not (b3_ids & n1_ids), "B3 与 N1 ID 相交"
    assert not any(i.startswith("N1-") or i.startswith("G") for i in b3_ids)

    golden_q = {e["query"] for e in golden["entries"]}
    n1_q = {a["query"] for a in n1["attacks"]}
    b3_q = {c["query"] for c in CASES}
    assert len(b3_q) == len(CASES), "B3 查询文本不得 internally 重复"
    assert not (b3_q & golden_q), "B3 查询与主金标查询重复（须新建用例）"
    assert not (b3_q & n1_q), "B3 查询与 N1 攻击查询重复（须新建用例）"


def test_fixture_file_is_not_n1_file():
    assert adversarial_report.CASES_PATH.name == "adversarial_goldens_v1.json"
    assert adversarial_report.CASES_PATH.name != "injection_attacks_v1.json"


# ---------------------------------------------------------------------------
# 2. 逐条拦截 + 合法形态 + 安全路径评级
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_adversarial_golden_blocked(case, normal_outcomes):
    outcome = normal_outcomes[case["id"]]
    assert case["expect"]["form"] in LEGAL_FORMS
    assert outcome.blocked, (
        f"{outcome.id}（{outcome.title}）未按期望拦住：{list(outcome.violations)}"
    )
    if case["expect"]["form"] == "safety" and case["expect"].get("rating_anchor"):
        assert any("比特级一致" in e for e in outcome.evidence), (
            f"{outcome.id} 安全路径缺确定性评级证据：{list(outcome.evidence)}"
        )


def test_safety_path_rating_only_from_engine(normal_outcomes):
    """安全形态金标：rating 与 host 侧复算一致（红线 2，LLM 不写灯）。"""
    safety = [c for c in CASES if c["expect"]["form"] == "safety"]
    assert safety, "恐慌/套话类必须有合法安全形态样本"
    for case in safety:
        outcome = normal_outcomes[case["id"]]
        assert outcome.blocked
        assert any("比特级一致" in e for e in outcome.evidence)


def test_no_half_contracts_on_success_path(normal_outcomes):
    """禁止半残契约：正常配置下不得以逃出异常交差。"""
    escaped = [
        o.id for o in normal_outcomes.values()
        if any("契约逃出异常" in v for v in o.violations)
    ]
    assert not escaped, f"半残契约（异常逃出）：{escaped}"


# ---------------------------------------------------------------------------
# 3. 独立报表对账
# ---------------------------------------------------------------------------


def test_report_doc_reconciles(normal_outcomes):
    doc_path = adversarial_report.REPORT_PATH
    assert doc_path.exists(), "对抗报表缺失：python tests/adversarial_report.py 重生成"
    doc = doc_path.read_text(encoding="utf-8")
    report = adversarial_report.build_report(tuple(normal_outcomes.values()))
    assert adversarial_report.headline_normal(report) in doc
    assert "n1-injection-report.md" in doc, "B3 报表必须链接 N1 注入报表（可链、勿合并）"
    assert str(adversarial_report.CASES_PATH.as_posix()).split("fixtures/")[-1] in doc.replace("\\", "/") or (
        "adversarial_goldens_v1.json" in doc
    )
    for category, agg in report["by_category"].items():
        assert agg["blocked"] == agg["total"] >= 10, f"{category} 未全拦截或不足 10 条"


# ---------------------------------------------------------------------------
# 4. 负向：放松对应防线 → 该类至少一条红
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(adversarial_report.CATEGORY_LABELS))
def test_loosening_matching_defense_flips_at_least_one(category):
    cfg = adversarial_report.loosened_cfg(category, config_loader.get_config())
    subset = tuple(c for c in CASES if c["category"] == category)
    outcomes = adversarial_report.run_suite(subset, cfg_override=cfg)
    flipped = [o.id for o in outcomes if not o.blocked]
    assert flipped, (
        f"放松 {category} 对应防线后该类仍全绿——金标对该防线不敏感：{[o.id for o in outcomes]}"
    )


def test_loosened_bias_does_not_empty_weapon_table():
    real = config_loader.get_config()
    loosened = adversarial_report.loosened_cfg("bias", real)
    assert loosened.guardrails.bias_markers == ()
    assert loosened.guardrails.weapon_markers == real.guardrails.weapon_markers
    assert loosened.guardrails.panic_blacklist == real.guardrails.panic_blacklist
    assert loosened.suggestions.empty_talk_blacklist == real.suggestions.empty_talk_blacklist
    assert loosened.covered_precincts == real.covered_precincts
    assert loosened.thresholds == real.thresholds
