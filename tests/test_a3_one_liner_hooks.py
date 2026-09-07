"""issue 18 / A3 验收：one_liner 确定性数据钩子金标断言（ADR-0003 定案）。

DoD：金标断言 one_liner 含至少一类允许的数据钩子且与 charts/ratio 不矛盾；
LLM 调用路径零参与 one_liner。

期望值的钉法沿 L1 同款哲学（不手填空中楼阁）：先从 mock fixture 数据集
权威复算（aggregate + build_charts + rate_precinct，探针输出 = 数据依据，
见本文件底部注释表），把每警区期望 one_liner 钉死为字面量；再对全量金标
语料（golden_set_v1 safety new-query 条目，打唯一接缝 execute_query）逐条
断言精确相等——同一警区的不同查询共享同一 one_liner（其输入只依赖
聚合数据，不依赖查询措辞，这是确定性的一部分）。

不矛盾性单独复验：one_liner 的钩子尾句含的倍数与结果字段
rating_explainable_basis（同源 float）保留一位小数逐字一致；⚪ 数据不足
（charts=None）时零钩子，退回「区域：⚪ 数据不足」纯前缀——不基于不可见
数据编造断言。夜间/类型钩子分支由合成 charts 单测覆盖（mock 语料是
低信号合成数据，day>night、无主导类型——两钩子按阈值诚实不发言，语料
只压到数值锚点 city_relative 上，见注释表）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safepass import config_loader, contracts
from safepass.pipeline import _one_liner, execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
# 权威复算数据依据（mock fixture 数据集探针输出，2026-09-08）：
#   P5  : sample=138 day=91 night=47 top1=CRIMINAL MISCHIEF:27 ratio=1.590234  red
#   P19 : sample=105 day=62 night=43 top1=CRIMINAL MISCHIEF:21 ratio=0.604980  green
#   P84 : sample=6  charts=None                                     ratio=0.043668 insufficient
#   P90 : sample=101 day=58 night=43 top1=CRIMINAL MISCHIEF:17 ratio=0.698320  green
#   P109: sample=94  day=58 night=36 top1=PETIT LARCENY:20   ratio=1.299843  yellow
# 判定：day>night 全警区 → 夜间钩子（night ≥ day×1.2）不命中；top1 占比
# 16.8–21.3% < 40% → 类型钩子不命中；全部落到 city_relative 数值锚点。
# 期望值由 _one_liner 同源公式手算：{ratio:.1f} = 0.6 / 1.6 / 0.7 / 1.3。
EXPECTED_BY_PRECINCT: dict[int, str] = {
    5: "唐人街：🔴 高风险，约为全市均值1.6倍",
    19: "上东区：🟢 相对安全，约为全市均值0.6倍",
    84: "布鲁克林高地：⚪ 数据不足",
    90: "威廉斯堡：🟢 相对安全，约为全市均值0.7倍",
    109: "法拉盛：🟡 需注意，约为全市均值1.3倍",
}

GOLDEN: dict = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
ENTRIES: list[dict] = GOLDEN["entries"]


def _safety_new_query_entries() -> list[dict]:
    """金标语料中直接新查询的 safety 条目（无追问上下文，打唯一接缝零 stub）。"""
    return [
        e
        for e in ENTRIES
        if e.get("context") is None and e["expect"]["type"] == "safety"
    ]


@pytest.mark.parametrize("entry_id", [e["id"] for e in _safety_new_query_entries()])
def test_golden_one_liner_matches_recomputed_expectation(entry_id):
    """金标断言：每条 safety 新查询的 one_liner 与该警区权威复算期望精确相等。"""
    entry = next(e for e in ENTRIES if e["id"] == entry_id)
    result = execute_query(entry["query"], profile=entry.get("profile"))
    assert isinstance(result, contracts.SafetyQueryResult)
    assert result.one_liner == EXPECTED_BY_PRECINCT[result.precinct], (
        f"{entry_id} one_liner 与金标期望不符（确定性模板 + 数据钩子填空）"
    )


def test_golden_rated_one_liners_carry_allowed_data_hook():
    """DoD 正面断言：数据充足的 safety 结果，one_liner 必含至少一类允许的
    数据钩子短语（不再是「区域：黄灯」裸标签）——允许集合 = 钩子词典按结果
    字段填充后的全部合法形态，按结果字段独立复算，不依赖查询措辞。"""
    cfg = config_loader.load_config()
    for entry in _safety_new_query_entries():
        result = execute_query(entry["query"], profile=entry.get("profile"))
        if result.charts is None:
            continue  # ⚪ 无钩子数据源：由 test_golden_insufficient_has_no_hook 覆盖
        assert "，" in result.one_liner, (
            f"{entry['id']} 数据充足的 one_liner 不得是裸标签（A3 目标反面）"
        )
        tail = result.one_liner.split("，", 1)[1]
        basis = result.rating_explainable_basis
        top1_display = cfg.one_liner.type_names.get(result.charts.top5_types[0].offense_type)
        allowed_tails = {
            hook.text.format(type=top1_display or "", ratio=f"{basis:.1f}")
            for hook in cfg.one_liner.hooks
            if ("{type}" not in hook.text or top1_display is not None)
            and ("{ratio}" not in hook.text or basis is not None)
        }
        assert tail in allowed_tails, (
            f"{entry['id']} one_liner 钩子不属于允许词典（未收录/占位缺失）：{tail!r}"
        )


def test_golden_one_liner_ratio_not_contradicts_basis():
    """DoD 不矛盾断言：one_liner 的全市倍数与 rating_explainable_basis
    （同一 float 源）保留一位小数逐字一致；评级与倍数带同源（评级档 =
    阈值带，倍数数字 = 阈值判定的同一 ratio）。"""
    for entry in _safety_new_query_entries():
        result = execute_query(entry["query"], profile=entry.get("profile"))
        if result.rating == contracts.RATING_INSUFFICIENT:
            assert result.rating_explainable_basis is None, entry["id"]
            continue
        assert result.rating_explainable_basis is not None
        assert f"{result.rating_explainable_basis:.1f}倍" in result.one_liner, (
            f"{entry['id']} 钩子倍数与评级依据不一致"
        )
        assert len(result.one_liner) <= 30, f"{entry['id']} 超出 30 字上限（AC-005）"


def test_golden_insufficient_has_no_hook():
    """⚪ 数据不足：charts=None → 零数据钩子，退回纯前缀（诚实不编造），
    无逗号、无倍数断言。"""
    for entry in _safety_new_query_entries():
        result = execute_query(entry["query"], profile=entry.get("profile"))
        if result.charts is not None:
            continue
        assert result.one_liner == f"{result.area}：⚪ 数据不足", entry["id"]
        assert "，" not in result.one_liner, f"{entry['id']} ⚪ 不得带钩子断言"
        assert "倍" not in result.one_liner, f"{entry['id']} ⚪ 不得给数值倍数"


def test_direct_queries_all_five_precincts_pinned():
    """最小查询集逐警区钉死（含词面：区域名/评级标签/钩子短语完整金标）。"""
    queries = {
        5: "唐人街安全吗？",
        19: "上东区安全吗？",
        84: "布鲁克林高地安全吗？",
        90: "威廉斯堡安全吗？",
        109: "法拉盛晚上安全吗？",
    }
    for precinct, query in queries.items():
        result = execute_query(query)
        assert isinstance(result, contracts.SafetyQueryResult)
        assert result.precinct == precinct
        assert result.one_liner == EXPECTED_BY_PRECINCT[precinct]


# ---------------------------------------------------------------------------
# 合成单测：钩子词典三条分支 + 兜底（mock 语料低信号压不出的路径）
# ---------------------------------------------------------------------------

_GREEN_LABEL = "🟢 相对安全"


def _charts(day: int, night: int, top5: tuple[tuple[str, int], ...]) -> contracts.Charts:
    return contracts.Charts(
        top5_types=[contracts.OffenseCount(offense_type=t, count=c) for t, c in top5],
        day_night=contracts.DayNight(day=day, night=night),
    )


def test_hook_night_higher_beats_city_when_night_significant():
    cfg = config_loader.load_config()
    charts = _charts(day=10, night=20, top5=(("ROBBERY", 14), ("BURGLARY", 6)))
    out = _one_liner("测试区", _GREEN_LABEL, charts, ratio_to_city_mean=1.9, cfg=cfg)
    assert out == "测试区：🟢 相对安全，夜间案件偏高"


def test_hook_top_type_dominant_beats_city_when_type_dominant():
    cfg = config_loader.load_config()
    charts = _charts(day=20, night=10, top5=(("ROBBERY", 15), ("BURGLARY", 5)))
    out = _one_liner("测试区", _GREEN_LABEL, charts, ratio_to_city_mean=1.9, cfg=cfg)
    assert out == "测试区：🟢 相对安全，以抢劫为主"


def test_hook_top_type_suppressed_for_unmapped_code():
    """类型代码不在 type_names 词典 → 该钩子不发言（诚实不编造），落数值锚点。"""
    cfg = config_loader.load_config()
    charts = _charts(day=1, night=1, top5=(("NO SUCH CODE", 19), ("BURGLARY", 1)))
    out = _one_liner("测试区", _GREEN_LABEL, charts, ratio_to_city_mean=0.55, cfg=cfg)
    assert out == "测试区：🟢 相对安全，约为全市均值0.6倍"


def test_hook_city_anchor_formats_one_decimal():
    cfg = config_loader.load_config()
    charts = _charts(day=10, night=10, top5=(("BURGLARY", 5),))
    assert "约为全市均值0.6倍" in _one_liner("测试区", _GREEN_LABEL, charts, 0.6049803364105514, cfg)
    assert "约为全市均值1.6倍" in _one_liner("测试区", _GREEN_LABEL, charts, 1.5902340271363065, cfg)


def test_hook_charts_none_returns_bare_prefix():
    cfg = config_loader.load_config()
    assert _one_liner("测试区", "⚪ 数据不足", None, 0.04, cfg) == "测试区：⚪ 数据不足"


def test_hook_length_guard_falls_back_to_prefix():
    """区域名超长导致超 30 字上限 → 退回纯前缀，不截断不编造（防御不可达）。"""
    cfg = config_loader.load_config()
    charts = _charts(day=10, night=10, top5=(("BURGLARY", 5),))
    out = _one_liner("超长区域名" * 3, _GREEN_LABEL, charts, 1.9, cfg)
    assert out == "超长区域名" * 3 + "：🟢 相对安全"
    assert len(out) <= 30
