"""B3 对抗金标 runner 与专表报表（issue 37 / 波 2 第三刀）。

夹具单一事实源：fixtures/eval/adversarial_goldens_v1.json——与 N1
injection_attacks_v1.json、主金标 golden_set_v1.json 三份独立文件。
拦截判定复用 tests/injection_report.py::run_case（同一接缝、同一判定口径），
本模块只负责：加载 B3 夹具、按类放松防线、渲染 docs/b3-adversarial-report.md。

独立重生成报表：``python tests/adversarial_report.py``
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_MOCK_DATASET = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"
os.environ["SAFEPASS_DATASET_PATH"] = str(_MOCK_DATASET)

import injection_report  # noqa: E402
from safepass import config_loader  # noqa: E402

CASES_PATH = REPO_ROOT / "fixtures" / "eval" / "adversarial_goldens_v1.json"
REPORT_PATH = REPO_ROOT / "docs" / "b3-adversarial-report.md"
CaseOutcome = injection_report.CaseOutcome

CATEGORY_LABELS: dict[str, str] = {
    "bias": "偏见诱导",
    "weapon": "武器/器械建议",
    "panic": "恐慌性夸大",
    "coverage_evasion": "越界编造评级",
    "platitude": "套话/空话建议",
}


def load_cases(path: Path = CASES_PATH) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(payload["cases"])
    if not cases:
        raise ValueError(f"对抗金标为空：{path}")
    return cases


def run_suite(
    cases: tuple[dict[str, Any], ...] | None = None,
    *,
    cfg_override: config_loader.AppConfig | None = None,
) -> tuple[injection_report.CaseOutcome, ...]:
    """整套 B3 金标经 injection_report.run_case 打一遍。"""
    case_list = load_cases() if cases is None else cases
    return injection_report.run_suite(case_list, cfg_override=cfg_override)


def loosened_cfg(category: str, cfg: config_loader.AppConfig) -> config_loader.AppConfig:
    """按类放松对应防线（只用于负向验证，生产配置不得此形态）。

    bias / weapon：清空静态守卫词表；
    panic：清空恐慌黑名单（Skill 校验 + 装配层同源表一并失效）；
    platitude：清空空话黑名单（建议结构校验失效）；
    coverage_evasion：把别名表里「可识别但不在覆盖清单」的单警区临时并入覆盖
    （人口估算从既有表抄一个正值，避免评级分母缺键）——D12 对该警区不再降级。
    """
    if category == "bias":
        return dataclasses.replace(
            cfg, guardrails=dataclasses.replace(cfg.guardrails, bias_markers=())
        )
    if category == "weapon":
        return dataclasses.replace(
            cfg, guardrails=dataclasses.replace(cfg.guardrails, weapon_markers=())
        )
    if category == "panic":
        return dataclasses.replace(
            cfg, guardrails=dataclasses.replace(cfg.guardrails, panic_blacklist=())
        )
    if category == "platitude":
        return dataclasses.replace(
            cfg,
            suggestions=dataclasses.replace(cfg.suggestions, empty_talk_blacklist=()),
        )
    if category == "coverage_evasion":
        extra: dict[int, int] = {}
        seed_pop = next(iter(cfg.precinct_populations.values()))
        for precincts in cfg.addressing.aliases.values():
            if len(precincts) == 1 and precincts[0] not in cfg.covered_precincts:
                extra[precincts[0]] = seed_pop
        if not extra:
            raise ValueError("别名表没有可并入的越界单警区，负向验证无法放松 D12")
        pops = dict(cfg.precinct_populations)
        pops.update(extra)
        return dataclasses.replace(
            cfg,
            covered_precincts=cfg.covered_precincts | frozenset(extra),
            precinct_populations=pops,
        )
    raise ValueError(f"未知对抗类别：{category!r}")


def build_report(outcomes: tuple[injection_report.CaseOutcome, ...]) -> dict[str, Any]:
    return injection_report.build_report(outcomes)


def headline_normal(report: dict[str, Any]) -> str:
    return f"总体拦截率（正常配置）：{report['rate'] * 100:.1f}%（{report['blocked']}/{report['total']}）"


def render_markdown(
    normal: dict[str, Any],
    loosened_by_category: dict[str, dict[str, Any]],
) -> str:
    cases = {c["id"]: c for c in load_cases()}
    today = datetime.date.today().isoformat()
    lines: list[str] = []
    lines.append("# B3 对抗金标专表（偏见 / 武器 / 恐慌 / 越界编造 / 套话）")
    lines.append("")
    lines.append(
        f"- 生成：{today}，`python tests/adversarial_report.py`（本页由 runner 重生成，数字与测试断言对账，漂移即红）"
    )
    lines.append("- 票：issue 37 / B3 对抗金标五类每类十条（波 2 第三刀）")
    lines.append(
        "- 夹具：`fixtures/eval/adversarial_goldens_v1.json`（与 N1 `injection_attacks_v1.json`、主金标 `golden_set_v1.json` 分表，禁止合并）"
    )
    lines.append("- 金标断言：`tests/test_b3_adversarial_goldens.py`")
    lines.append("- 复现：全程离线——攻陷脚本 fake + 钉死检索层，零 API / 零 cassette")
    lines.append("- 链接：[N1 注入拦截率报表](n1-injection-report.md)（可链、数据源各自独立）")
    lines.append("")
    lines.append("## 覆盖矩阵")
    lines.append("")
    lines.append(f"**{headline_normal(normal)}**")
    lines.append("")
    lines.append("| 类别 | 中文名 | 拦截率 | 金标 ID |")
    lines.append("|---|---|---|---|")
    ids_by_cat: dict[str, list[str]] = {}
    for case in normal["cases"]:
        ids_by_cat.setdefault(case["category"], []).append(case["id"])
    for category in CATEGORY_LABELS:
        agg = normal["by_category"][category]
        ids = "、".join(ids_by_cat[category])
        lines.append(
            f"| `{category}` | {CATEGORY_LABELS[category]} | "
            f"{agg['rate'] * 100:.1f}%（{agg['blocked']}/{agg['total']}） | {ids} |"
        )
    lines.append("")
    lines.append("## 负向验证（放松对应防线 → 该类至少一条红）")
    lines.append("")
    lines.append("| 类别 | 放松方式 | 透出（会红） | 该类拦截率 |")
    lines.append("|---|---|---|---|")
    loosen_how = {
        "bias": "guardrails.bias_markers 清空",
        "weapon": "guardrails.weapon_markers 清空",
        "panic": "guardrails.panic_blacklist 清空",
        "coverage_evasion": "别名表越界单警区临时并入 covered_precincts",
        "platitude": "suggestions.empty_talk_blacklist 清空",
    }
    for category in CATEGORY_LABELS:
        report = loosened_by_category[category]
        normal_ids = {c["id"]: c["blocked"] for c in normal["cases"] if c["category"] == category}
        loose_ids = {c["id"]: c["blocked"] for c in report["cases"]}
        flipped = sorted(i for i, ok in normal_ids.items() if ok and not loose_ids.get(i, True))
        lines.append(
            f"| `{category}` | {loosen_how[category]} | "
            f"{('、'.join(flipped)) or '（无）'} | "
            f"{report['rate'] * 100:.1f}%（{report['blocked']}/{report['total']}） |"
        )
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    lines.append("| ID | 对抗 | 类别 | 拦截 | 期望形态 | 防线 |")
    lines.append("|---|---|---|---|---|---|")
    for case in normal["cases"]:
        spec = cases[case["id"]]
        mark = "拦截" if case["blocked"] else "透出"
        lines.append(
            f"| {case['id']} | {spec['title']} | `{case['category']}` | {mark} | "
            f"`{spec['expect']['form']}` | {spec['expect']['defense']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    cases = load_cases()
    cfg = config_loader.get_config()
    normal = build_report(run_suite(cases))
    loosened_by_category: dict[str, dict[str, Any]] = {}
    for category in CATEGORY_LABELS:
        subset = tuple(c for c in cases if c["category"] == category)
        loosened_by_category[category] = build_report(
            run_suite(subset, cfg_override=loosened_cfg(category, cfg))
        )
    REPORT_PATH.write_text(render_markdown(normal, loosened_by_category), encoding="utf-8")
    print(
        f"报表已写入 {REPORT_PATH}：正常 {normal['blocked']}/{normal['total']}"
        f"（{normal['rate'] * 100:.1f}%）"
    )
    if normal["blocked"] != normal["total"]:
        failed = [c["id"] for c in normal["cases"] if not c["blocked"]]
        print(f"警告：正常配置下未全拦截：{failed}")


if __name__ == "__main__":
    main()
