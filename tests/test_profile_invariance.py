"""issue 09 / RALPH T7 验收测试：画像不变性集（NEG-009 / AC-011 / AC-012 / AC-023）。

对应 .scratch/safepass-nyc-mvp/issues/09-chinese-address-neg-guardrails.md 勾选：
    3. 同一区域 × 有/无画像 × 不同问法：评级字段完全一致，且与阈值规则复算一致
    5. 画像声明字段存在（"会话级、关闭即删除"；措辞易懂是人工项，不在本任务）

画像作用域（spec D5 / ADR-0002）只许落在两处：①时间风险提示的个性化表述与前置；
②建议的生成语境与排序。本集同时断言画像确实被消费（排序变化/时间提示出现），
证明"有作用但被关进笼子"——评级、样本量、图表、可信度与画像零相关。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from safepass import config_loader, contracts, data_agent, rating_engine
from safepass.pipeline import execute_query

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_CSV = REPO_ROOT / "fixtures" / "nypd" / "mock_nypd.csv"

# 同一区域的多种问法（含三维包裹问法，全部走确定性路径，零 LLM）
PHRASINGS = (
    "上东区安全吗？",
    "上东区晚上安全吗？",
    "Upper East Side 怎么样？",
    "我是女生，晚上10点从图书馆回家，Upper East Side安全吗？",
)

PROFILES = (
    None,
    {"crowd": ["带娃"], "scene": "接送孩子上学"},
    {"time": "经常加班晚归", "crowd": ["女生"]},
)

# 画像不变性要锁死的评级相关字段（ADR-0002：画像不进入评级输入）
RATING_FIELDS = ("rating", "rating_explainable_basis", "confidence_tier", "sample_size")


def _expected_rating(precinct: int) -> rating_engine.RatingResult:
    """Host 侧权威复算（与管线同一数据路径：rating_config 锚定数据集复算均值，票 07）。"""
    records = data_agent.load_dataset(NYPD_CSV)
    stats = data_agent.aggregate_precinct(records, precinct)
    return rating_engine.rate_precinct(stats, data_agent.rating_config(records, config_loader.load_config()))


def _rating_view(result) -> dict:
    return {f: getattr(result, f) for f in RATING_FIELDS}


def test_rating_identical_across_profiles_and_phrasings():
    """NEG-009/AC-012：同区域 × 有/无画像 × 不同问法，评级字段完全一致。"""
    expected = _expected_rating(19)
    views = []
    for phrasing in PHRASINGS:
        for profile in PROFILES:
            result = execute_query(phrasing, profile=profile)
            assert result.type == "safety" and result.precinct == 19, phrasing
            view = _rating_view(result)
            # 与阈值规则独立复算一致（评级引擎零画像参与的直接证据）
            assert view["rating"] == expected.rating
            assert view["sample_size"] == data_agent.aggregate_precinct(
                data_agent.load_dataset(NYPD_CSV), 19
            ).sample_size
            views.append(view)
    assert all(v == views[0] for v in views), (
        "画像或问法改变了评级相关字段：\n" + "\n".join(repr(v) for v in views)
    )
    base = execute_query("上东区安全吗？")
    assert base.charts is not None and result.charts is not None
    assert base.charts == result.charts, "图表数据同样与画像无关"


def test_insufficient_data_area_also_profile_invariant():
    """⚪ 档（84 警区样本量 <10）同样画像不变：强制数据不足不给评级。"""
    results = [
        execute_query("布鲁克林高地安全吗？", profile=p) for p in (None, {"crowd": ["带娃"]})
    ]
    for r in results:
        assert r.type == "safety"
        assert r.rating == contracts.RATING_INSUFFICIENT
        assert r.confidence_tier is None
        assert r.unknowns, "⚪ 档诚实缺口非空（AC-007）"
        assert r.charts is None, "⚪ 档图表模块隐藏（AC-022）"
    assert _rating_view(results[0]) == _rating_view(results[1])


def test_profile_consumed_only_in_suggestion_ordering():
    """AC-011/D5②：画像消费只在建议排序——带娃画像把人群相关建议前置，评级不动。"""
    cfg = config_loader.load_config()
    plain = execute_query("上东区安全吗？")
    with_kid = execute_query("上东区安全吗？", profile={"crowd": ["带娃"]})

    assert with_kid.rating == plain.rating == _expected_rating(19).rating
    crowd_tip = cfg.profile.crowd_suggestions["带娃"]
    assert with_kid.suggestions[0] == crowd_tip, "画像人群标签命中的建议应排在最前"
    assert crowd_tip not in plain.suggestions
    # 排序变化不改集合边界：仍是配置内建议、仍过 3-5 条结构校验
    assert 3 <= len(with_kid.suggestions) <= 5
    assert set(with_kid.suggestions) <= set(cfg.suggestions.safety_general) | {crowd_tip}


def test_profile_consumed_only_in_time_prompt():
    """D5①：晚归画像只做时间风险提示的个性化前置，评级与数据字段不动。"""
    plain = execute_query("上东区安全吗？")
    late = execute_query("上东区安全吗？", profile={"time": "经常加班晚归"})

    assert _rating_view(late) == _rating_view(plain)
    time_notes = [d for d in late.dimensions if d["dimension"] == "时间提示"]
    assert time_notes, "晚归画像应触发时间提示维度前置"
    assert cfg_note_in(late, time_notes)
    assert all(d["dimension"] != "时间提示" for d in plain.dimensions)


def cfg_note_in(result, notes) -> bool:
    cfg = config_loader.load_config()
    return any(n["value"] == cfg.profile.late_night_note for n in notes)


def test_profile_notice_field_present():
    """AC-023（结构层）：画像声明字段存在——会话级、关闭即删除。"""
    cfg = config_loader.load_config()
    assert "会话" in cfg.profile.notice and "删除" in cfg.profile.notice, (
        "配置里的画像声明必须是'会话级、关闭即删除'语义"
    )
    for profile in PROFILES:
        result = execute_query("上东区安全吗？", profile=profile)
        assert result.profile_notice.strip(), "契约中画像声明字段不得为空"
        assert result.profile_notice == cfg.profile.notice
