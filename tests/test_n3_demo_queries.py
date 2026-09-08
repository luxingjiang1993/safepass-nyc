"""issue 25 / N3 一键复现审阅者路径：无 key 确定性 demo + README 三命令。

对应 .scratch/safepass-phase3-tickets/issues/10-n3-one-command-repro.md：
    1. 5 条固定 query 覆盖安全 + 越界 + 紧急，安全/越界与金标子集逐字对齐；
    2. 无 key 路径 = 确定性 one_liner + 模板建议，grounds 空态打印「通用建议」；
    3. README 写明装依赖 → 跑 demo → 开本地页；
    4. 5 条 query 不含 API key、不含非 fixture 数据。

全程离线：无 LLM 客户端、零网络。子进程断言剥掉全部 LLM 环境变量。
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from safepass import contracts

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo_queries.py"
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
README_PATH = REPO_ROOT / "README.md"
MOCK_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

GOLDEN_QUERIES = {
    e["id"]: e["query"]
    for e in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]
}

_LLM_ENV_KEYS = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "DASHSCOPE_API_KEY",
)


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_queries", DEMO_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _no_connect(*args, **kwargs):
        raise AssertionError("N3 无 key 路径不得访问网络")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: _no_connect())


@pytest.fixture(scope="module")
def demo():
    assert DEMO_SCRIPT.exists(), "缺少 scripts/demo_queries.py（N3 与 E7 合并入口）"
    return _load_demo()


# ---------------------------------------------------------------------------
# 1. 固定子集：5 条、P4 三种形态、金标对齐、无密钥
# ---------------------------------------------------------------------------


def test_demo_cases_are_five_and_cover_p4_kinds(demo):
    cases = demo.DEMO_CASES
    assert len(cases) == 5
    kinds = {c["kind"] for c in cases}
    assert kinds == {"safety", "degraded", "emergency"}


def test_demo_safety_and_ooc_queries_match_golden(demo):
    for case in demo.DEMO_CASES:
        if case["kind"] == "emergency":
            continue
        assert case["id"] in GOLDEN_QUERIES, f"{case['id']} 不在金标子集"
        assert case["query"] == GOLDEN_QUERIES[case["id"]]


def test_demo_queries_have_no_secrets_or_non_fixture_payloads(demo):
    blob = "\n".join(c["query"] for c in demo.DEMO_CASES)
    lowered = blob.lower()
    assert "sk-" not in lowered
    assert "api_key" not in lowered
    assert "dashscope" not in lowered
    for case in demo.DEMO_CASES:
        assert "http://" not in case["query"]
        assert "https://" not in case["query"]


# ---------------------------------------------------------------------------
# 2. 无 key 路径：契约摘要 + 模板建议 + grounds 空态「通用建议」
# ---------------------------------------------------------------------------


def test_no_key_path_prints_contract_summary_and_generic_grounds(demo):
    client = demo.resolve_llm_client(environ={})
    assert client is None

    lines = demo.run_demo(llm_client=None)
    text = "\n".join(lines)
    assert "path: template" in text
    assert demo.GROUNDS_EMPTY_LABEL in text

    results = demo.execute_demo_cases(llm_client=None)
    by_kind = {case["kind"]: result for case, result in results}
    assert set(by_kind) == {"safety", "degraded", "emergency"}

    safety = by_kind["safety"]
    assert isinstance(safety, contracts.SafetyQueryResult)
    assert safety.suggestions_source == "template"
    assert safety.suggestion_grounds == []
    assert safety.one_liner

    degraded = by_kind["degraded"]
    assert isinstance(degraded, contracts.DegradedResult)
    assert degraded.degraded_capability == "out_of_coverage"
    assert degraded.general_suggestions

    emergency = by_kind["emergency"]
    assert isinstance(emergency, contracts.EmergencyResult)
    assert emergency.is_emergency is True


def test_no_key_script_subprocess_prints_five_summaries():
    env = {k: v for k, v in os.environ.items() if k not in _LLM_ENV_KEYS}
    env["PYTHONIOENCODING"] = "utf-8"
    env["SAFEPASS_DATASET_PATH"] = str(MOCK_CSV)
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, out
    assert out.count("type:") == 5
    assert "path: template" in out
    assert "通用建议" in out
    assert "safety" in out
    assert "degraded" in out
    assert "emergency" in out


# ---------------------------------------------------------------------------
# 3. README 审阅者路径三命令
# ---------------------------------------------------------------------------


def test_readme_documents_three_local_commands():
    text = README_PATH.read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in text
    assert "python scripts/demo_queries.py" in text
    assert "python frontend/app.py" in text
    assert "无 key" in text
    assert "确定性" in text
    assert "Skill" in text
