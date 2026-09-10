"""票 08 / E4：熔断演示态（有 Skill 后）。

接缝（与用户确认 defaults）：
    1. execute_query + 预熔断 BudgetFusedClient → suggestions_source=template、
       rating 在、llm_degraded + degradation_notice、底层 calls 不增；
    2. 熔断 Safety 结果 → render 首屏可见 notice（header 后、建议前）；
    3. 熔断下紧急查询 → emergency 形态，HTML 无熔断横幅、不变资料页；
    4. A5 双次 execute_query（有画像 + 空画像）在熔断下 calls 仍为 0。
先验：票 06 预算熔断包装器；全程 fake LLM，离线可跑。
"""

from __future__ import annotations

import json
from pathlib import Path

from frontend import render
from safepass import config_loader, contracts, cost_control
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query

CFG = config_loader.get_config()
NOTICE = CFG.cost_control.degraded_notice
PRICES = CFG.cost_control.prices_per_1k_tokens
CHARS_PER_TOKEN = CFG.cost_control.chars_per_token


class _ScriptedFake:
    """剧本 fake：区分路由 / 提取 / 建议；调用次数供熔断断言。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        system = messages[0]["content"]
        if "路由助手" in system:
            return ChatResponse(
                content=json.dumps(
                    {"route": "area_safety_query"}, ensure_ascii=False
                ),
                model="qwen-flash",
            )
        if "三维" in system or "提取" in system:
            return ChatResponse(
                content=json.dumps(
                    {"area": None, "crowd": None, "time": None}, ensure_ascii=False
                ),
                model="qwen-flash",
            )
        return ChatResponse(
            content=json.dumps(
                {
                    "suggestions": ["夜间结伴出行", "保持手机有电", "走人流多的路"],
                    "suggestion_grounds": [],
                },
                ensure_ascii=False,
            ),
            model="qwen-flash",
        )


class _ManualClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _write_budget(tmp_path: Path, usd: float) -> Path:
    path = tmp_path / "token-budget.json"
    path.write_text(json.dumps({"daily_cost_budget_usd": usd}), encoding="utf-8")
    return path


def _prefused_client(tmp_path: Path, fake: _ScriptedFake) -> cost_control.BudgetFusedClient:
    """预算 0 = 即刻熔断：任何 chat 前即拒绝。"""
    return cost_control.BudgetFusedClient(
        fake,
        budget_path=_write_budget(tmp_path, 0.0),
        report_path=tmp_path / "cost_report.jsonl",
        rate_window_seconds=CFG.cost_control.rate_window_seconds,
        rate_max_requests=CFG.cost_control.rate_max_requests,
        chars_per_token=CHARS_PER_TOKEN,
        prices_per_1k_tokens=PRICES,
        clock=_ManualClock(),
    )


def test_prefused_safety_is_template_keeps_rating_and_freezes_calls(tmp_path: Path):
    """熔断后建议来源为模板，rating/数据仍在，底层 LLM 调用次数不增。"""
    fake = _ScriptedFake()
    client = _prefused_client(tmp_path, fake)

    first = execute_query("唐人街晚上安全吗", llm_client=client)
    second = execute_query("上东区安全吗", llm_client=client)

    assert fake.calls == 0, "熔断后不得新增模型调用"
    for result in (first, second):
        assert result.type == "safety"
        assert result.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
        assert result.rating in contracts.LEGAL_RATINGS
        assert result.charts is not None
        assert result.llm_degraded is True
        assert result.degradation_notice == NOTICE
        assert 3 <= len(result.suggestions) <= 5


def test_prefused_safety_notice_visible_on_first_screen(tmp_path: Path):
    """熔断 Safety 结果经渲染：degradation_notice 在 header 之后、建议之前。"""
    fake = _ScriptedFake()
    client = _prefused_client(tmp_path, fake)
    result = execute_query("上东区安全吗", llm_client=client)
    assert result.type == "safety"

    html = render.render_result(result, CFG)
    assert fake.calls == 0
    assert 'class="llm-degraded-banner"' in html
    assert NOTICE in html
    header_end = html.index("</header>")
    banner_at = html.index("llm-degraded-banner")
    suggestions_at = html.index('class="suggestions"')
    assert header_end < banner_at < suggestions_at


def test_prefused_emergency_not_turned_into_data_page(tmp_path: Path):
    """熔断下紧急查询仍是紧急页：无熔断横幅，无评级/图表资料页槽。"""
    fake = _ScriptedFake()
    client = _prefused_client(tmp_path, fake)
    result = execute_query("救命！有人跟踪我", llm_client=client)

    assert result.type == "emergency"
    assert fake.calls == 0
    assert not getattr(result, "llm_degraded", False)

    html = render.render_result(result, CFG)
    assert "theme-emergency" in html
    assert "llm-degraded-banner" not in html
    assert NOTICE not in html
    # 不被打乱成覆盖内资料页
    assert 'class="suggestions"' not in html
    assert 'class="charts"' not in html
    assert 'class="dimensions"' not in html
    assert "rating-" not in html
    assert 'href="tel:911"' in html


def test_a5_double_seam_under_fuse_adds_zero_calls(tmp_path: Path):
    """有画像时 A5 再跑空画像接缝：熔断下两次均模板，调用次数仍为 0。"""
    fake = _ScriptedFake()
    client = _prefused_client(tmp_path, fake)
    profile = {"scene": ["晚归"], "gender": "女生"}

    with_profile = execute_query(
        "上东区安全吗", profile=profile, llm_client=client
    )
    baseline = execute_query(
        "上东区安全吗", profile=None, llm_client=client
    )

    assert fake.calls == 0
    assert with_profile.type == baseline.type == "safety"
    assert with_profile.rating == baseline.rating
    assert with_profile.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert baseline.suggestions_source == contracts.SUGGESTIONS_SOURCE_TEMPLATE
    assert with_profile.llm_degraded and baseline.llm_degraded

    html = render.render_result(
        with_profile,
        CFG,
        profile,
        baseline_suggestions=baseline.suggestions,
    )
    assert 'class="llm-degraded-banner"' in html
    assert NOTICE in html
    assert "对比：无画像时的建议" in html
