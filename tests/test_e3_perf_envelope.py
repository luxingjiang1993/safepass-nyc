"""issue 47 / E3 性能信封：可复跑表 + 超阈红 + README 投影同源。

对应 .scratch/safepass-wave2-third-knife/issues/12-e3-perf-envelope.md：
    1. 既有性能标记可跑；阈值在配置；
    2. 表含查询 / 紧急 / 无 LLM / 有 Skill / 索引内存粗值；
    3. README 投影与测试口径同源或注明来源；
    4. 超阈红；
    5. python -m pytest tests/ -q 全绿。

接缝：pytest -m perf 实测；单一事实源 = config/app.yaml 的 perf 节；
README 只投影预算数字，不另存录制工件。
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Callable

import pytest

from safepass import config_loader, contracts
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"

# README 表行标签 ↔ config.perf.budgets 键（投影对账）
_README_BUDGET_ROWS: tuple[tuple[str, str], ...] = (
    ("查询 P95", "query_p95_seconds"),
    ("紧急 P95", "emergency_p95_seconds"),
    ("无 LLM 路径 P95", "no_llm_p95_seconds"),
    ("有 Skill 路径 P95", "skill_p95_seconds"),
    ("索引内存粗值", "index_memory_mb_max"),
)


class _ScriptedFakeLLM:
    """按剧本返回的 fake；每次接缝调用新建实例，避免剧本耗尽。"""

    def __init__(self, script: list[str]):
        self._script = list(script)

    def chat(self, messages, *, model=None, **kwargs):
        if not self._script:
            raise AssertionError("fake LLM 剧本耗尽")
        return ChatResponse(content=self._script.pop(0), model="fake")


def _skill_script() -> list[str]:
    return [
        json.dumps({"route": "area_safety_query"}),
        json.dumps({"area": "上东区", "crowd": None, "time": "晚上"}),
        json.dumps(
            {
                "suggestions": [
                    "夜间出行选择照明好的主干道",
                    "随身包放在身前视线范围内",
                    "提前告知朋友行程并保持联系",
                ],
                "suggestion_grounds": [],
            },
            ensure_ascii=False,
        ),
    ]


def _p95(durations: list[float]) -> float:
    ordered = sorted(durations)
    return ordered[int(math.ceil(0.95 * len(ordered))) - 1]


def _effective_budget(budget_seconds: float, margin: float) -> float:
    return budget_seconds * margin


def _measure_p95(n: int, once: Callable[[], None], *, warmup: bool = True) -> float:
    """稳态 P95：可选丢弃一次预热（embedding / 索引冷加载不进信封）。"""
    if warmup:
        once()
    durations: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        once()
        durations.append(time.perf_counter() - start)
    return _p95(durations)


def _index_memory_mb(index_dir: Path) -> float:
    total = sum(f.stat().st_size for f in index_dir.iterdir() if f.is_file())
    return total / (1024 * 1024)


def _readme_perf_cell(label: str) -> str:
    text = README_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == label:
            assert len(cells) > 1 and cells[1], f"README 性能信封行缺预算列：{line!r}"
            return cells[1]
    raise AssertionError(f"README 性能信封表缺少行：{label}")


def test_perf_config_loaded_from_yaml():
    """结构不变量：阈值存在且为正；具体 UX 秒数不在测试里钉死（红线 1）。"""
    cfg = config_loader.load_config()
    perf = cfg.perf
    assert 0 < perf.margin <= 1.0
    assert perf.samples.query >= 5
    assert perf.samples.emergency >= 5
    assert perf.samples.no_llm >= 5
    assert perf.samples.skill >= 5
    assert perf.budgets.query_p95_seconds > 0
    assert perf.budgets.emergency_p95_seconds > 0
    assert perf.budgets.no_llm_p95_seconds > 0
    assert perf.budgets.skill_p95_seconds > 0
    assert perf.budgets.index_memory_mb_max > 0
    assert perf.index_dir.strip()


@pytest.mark.perf
def test_query_and_skill_path_latency_p95_within_budget():
    """查询 P95（UX-001）与有 Skill 路径同源：一次实测，分别对两档预算。"""
    cfg = config_loader.load_config()
    perf = cfg.perf
    n = max(perf.samples.query, perf.samples.skill)

    def once() -> None:
        result = execute_query(
            "上东区晚上安全吗？", llm_client=_ScriptedFakeLLM(_skill_script())
        )
        assert isinstance(result, contracts.SafetyQueryResult)
        assert result.suggestions_source == "skill"

    p95 = _measure_p95(n, once)
    for label, budget in (
        ("查询", perf.budgets.query_p95_seconds),
        ("有 Skill", perf.budgets.skill_p95_seconds),
    ):
        limit = _effective_budget(budget, perf.margin)
        assert p95 < limit, (
            f"{label} P95 {p95:.2f}s 超出预算（{budget}s × {perf.margin}）"
        )


@pytest.mark.perf
def test_emergency_latency_p95_uses_config_budget():
    cfg = config_loader.load_config()
    perf = cfg.perf

    def once() -> None:
        execute_query("救命，有人持刀！")

    p95 = _measure_p95(perf.samples.emergency, once, warmup=False)
    limit = _effective_budget(perf.budgets.emergency_p95_seconds, perf.margin)
    assert p95 < limit, (
        f"紧急组装 P95 {p95:.3f}s 超出预算"
        f"（{perf.budgets.emergency_p95_seconds}s × {perf.margin}）"
    )


@pytest.mark.perf
def test_no_llm_path_latency_p95_within_budget():
    cfg = config_loader.load_config()
    perf = cfg.perf

    def once() -> None:
        result = execute_query("上东区晚上安全吗？", llm_client=None)
        assert isinstance(result, contracts.SafetyQueryResult)
        assert result.suggestions_source == "template"

    p95 = _measure_p95(perf.samples.no_llm, once)
    limit = _effective_budget(perf.budgets.no_llm_p95_seconds, perf.margin)
    assert p95 < limit, (
        f"无 LLM 路径 P95 {p95:.2f}s 超出预算"
        f"（{perf.budgets.no_llm_p95_seconds}s × {perf.margin}）"
    )


@pytest.mark.perf
def test_index_memory_within_budget():
    cfg = config_loader.load_config()
    perf = cfg.perf
    index_dir = REPO_ROOT / perf.index_dir
    assert index_dir.is_dir(), f"索引目录不存在：{perf.index_dir}"
    mb = _index_memory_mb(index_dir)
    assert mb < perf.budgets.index_memory_mb_max, (
        f"索引内存粗值 {mb:.3f} MB 超出预算 {perf.budgets.index_memory_mb_max} MB"
    )


def test_readme_perf_envelope_projects_config_budgets():
    """README 性能信封表预算列 = config.perf.budgets（投影不漂移）。"""
    cfg = config_loader.load_config()
    budgets = cfg.perf.budgets
    text = README_PATH.read_text(encoding="utf-8")
    assert "性能信封" in text
    assert "config/app.yaml" in text or "config `perf`" in text or "perf 节" in text
    assert "pytest" in text and "perf" in text

    for label, key in _README_BUDGET_ROWS:
        cell = _readme_perf_cell(label)
        expected = getattr(budgets, key)
        if key == "index_memory_mb_max":
            match = re.search(r"([\d.]+)\s*MB", cell, re.I)
            assert match, f"索引内存行须含 MB 数字，实际 {cell!r}"
            assert float(match.group(1)) == pytest.approx(expected)
        else:
            match = re.search(r"([\d.]+)\s*s", cell, re.I)
            assert match, f"{label} 行须含秒数字，实际 {cell!r}"
            assert float(match.group(1)) == pytest.approx(expected)


def test_readme_perf_envelope_cites_recompute_command():
    text = README_PATH.read_text(encoding="utf-8")
    assert "pytest tests/ -q -m perf" in text or "pytest tests/ -m perf" in text
