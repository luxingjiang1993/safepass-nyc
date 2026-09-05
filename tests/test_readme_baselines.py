"""issue 04 / M1 勾选一二：README 质量基线对账测试。

三项指标（路由准确率 L1 / groundedness L2 / 幻觉率 L2）已写入 README，
本测试把 README 里的数字与权威事实源对账，防"文档漂移"（文档说一套、
套件跑一套）：

- L2 两项：fixtures/eval/l2_results_v1.json（录制工件，回放对账的同一事实源）
- L1 路由准确率：分子/分母必须等于金标条目数（全绿基线 = 全部命中）

README 是唯一被解析的文档面：表格行以指标名开头、基线列为首个单元格，
格式由本测试锁定（改动格式 = 红灯 = 刻意事件）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
README_TEXT = README_PATH.read_text(encoding="utf-8")
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
RESULTS_PATH = REPO_ROOT / "fixtures" / "eval" / "l2_results_v1.json"


def _readme_baseline_cell(metric_label: str) -> str:
    """README 质量基线表格中某指标行的首个单元格（基线列）。"""
    for line in README_TEXT.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and cells[0] == metric_label:
            assert len(cells) >= 2 and cells[1], f"README 基线行缺基线列：{line!r}"
            return cells[1]
    raise AssertionError(f"README 质量基线表缺少指标行：{metric_label}")


def _load_results() -> dict[str, Any]:
    assert RESULTS_PATH.exists(), f"缺少 {RESULTS_PATH.name}（L2 录制工件）"
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def test_readme_l2_baselines_match_recorded_artifact():
    """README 的 groundedness / 幻觉率必须与录制工件一致（文档不漂移）。"""
    metrics = _load_results()["metrics"]
    for label, key in (("groundedness（L2）", "groundedness_mean"),
                       ("幻觉率（L2）", "hallucination_rate")):
        cell = _readme_baseline_cell(label)
        readme_value = float(cell)
        assert abs(readme_value - float(metrics[key])) < 1e-9, (
            f"README {label} 基线 {readme_value} 与录制工件 {metrics[key]} 不符："
            "套件重录后需同步 README（票 04 单一事实源 = 工件，README 是投影）"
        )


def test_readme_l1_routing_accuracy_covers_all_golden_entries():
    """README 路由准确率 = 100% 且分子分母恰等于金标条目总数。"""
    n_entries = len(json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"])
    cell = _readme_baseline_cell("路由准确率（L1）")
    match = re.fullmatch(r"100%（(\d+)/(\d+)）", cell)
    assert match, f"README 路由准确率基线列格式应为「100%（分子/分母）」，实际 {cell!r}"
    assert (int(match.group(1)), int(match.group(2))) == (n_entries, n_entries), (
        f"README 路由准确率分子分母 {match.groups()} 与金标条目数 {n_entries} 不符"
    )


def test_readme_baselines_cite_recompute_commands():
    """三项指标都必须带可复算路径（跑哪个套件、读哪份工件）。"""
    for needle in ("pytest tests/test_golden_set.py", "pytest tests/eval -q",
                   "l2_results_v1.json"):
        assert needle in README_TEXT, f"README 质量基线缺复算路径：{needle}"
