"""成本三件套测试（票 06 / M2）：日预算熔断 + 请求级限流 + 成本 JSONL 上报。

覆盖票据勾选项：
- 熔断包装器就位：fake client 断言超限后 LLM 调用数停增、降级响应带明示
  标记、结构化数据照出（评级/图表/community_info 不受熔断影响）；
- 限流行为：窗口内超限抛 RateLimitedError，滑出窗口后恢复；
- 成本 JSONL 上报：字段含模型/调用数/估算成本/当日累计；
- token-budget.json 的 daily_cost_budget_usd = 5；
- 窗口/阈值字面量在 config/app.yaml（factory 从集中配置读取，测试直注参数）。

LLM 调用全程 fake，离线可跑（红线 5）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safepass import config_loader, contracts, cost_control
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 直注参数与集中配置同源（红线 1：字面量单一事实源在 config/app.yaml）；
# 限流测试里的窗口/上限是刻意注入的测试剧本参数（fixture 例外），非生产值。
_CC = config_loader.load_config().cost_control
PRICES = _CC.prices_per_1k_tokens
CHARS_PER_TOKEN = _CC.chars_per_token


class _ScriptedFake:
    """剧本 fake：按系统提示词区分路由调用与三维提取调用（T5/T6/T7 同款先例）。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        system = messages[0]["content"]
        if "路由助手" in system:
            return ChatResponse(
                content=json.dumps({"route": "area_safety_query"}, ensure_ascii=False),
                model="deepseek-chat",
            )
        return ChatResponse(
            content=json.dumps({"area": None, "crowd": None, "time": None}, ensure_ascii=False),
            model="deepseek-chat",
        )


class _ManualClock:
    """可拨时钟：限流窗口测试确定性推进时间。"""

    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _write_budget(tmp_path: Path, usd: float | None) -> Path:
    budget_path = tmp_path / "token-budget.json"
    budget_path.write_text(json.dumps({"daily_cost_budget_usd": usd}), encoding="utf-8")
    return budget_path


def _make_client(
    tmp_path: Path,
    fake: _ScriptedFake,
    *,
    budget_usd: float | None = 5.0,
    window_seconds: float | None = None,
    max_requests: int | None = None,
    report_name: str = "cost_report.jsonl",
    clock=None,
) -> cost_control.BudgetFusedClient:
    return cost_control.BudgetFusedClient(
        fake,
        budget_path=_write_budget(tmp_path, budget_usd),
        report_path=tmp_path / report_name,
        rate_window_seconds=_CC.rate_window_seconds if window_seconds is None else window_seconds,
        rate_max_requests=_CC.rate_max_requests if max_requests is None else max_requests,
        chars_per_token=CHARS_PER_TOKEN,
        prices_per_1k_tokens=PRICES,
        clock=clock or _ManualClock(),
    )


def _report_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. token-budget.json：日预算 = 5（生产 $5/日熔断）
# ---------------------------------------------------------------------------


def test_daily_cost_budget_is_five():
    """票据勾选：token-budget.json 的 daily_cost_budget_usd 设为 5。"""
    data = json.loads((PROJECT_ROOT / "token-budget.json").read_text(encoding="utf-8"))
    assert data["daily_cost_budget_usd"] == 5


def test_load_daily_budget_null_means_no_fuse(tmp_path: Path):
    """预算 null（未配置）= 永不熔断；缺失文件同样不熔断。"""
    assert cost_control.load_daily_budget_usd(_write_budget(tmp_path, None)) is None
    assert cost_control.load_daily_budget_usd(tmp_path / "missing.json") is None
    assert cost_control.load_daily_budget_usd(_write_budget(tmp_path, 5)) == 5.0


# ---------------------------------------------------------------------------
# 2. 配置接线：窗口/阈值字面量在 config/app.yaml（红线 1）
# ---------------------------------------------------------------------------


def test_cost_control_config_loaded_from_app_yaml():
    """限流窗口/估算系数/单价/降级话术全部经 config_loader 读取（不在代码）。"""
    cc = config_loader.load_config().cost_control
    assert cc.rate_window_seconds > 0
    assert cc.rate_max_requests > 0
    assert cc.chars_per_token > 0
    assert "default" in cc.prices_per_1k_tokens  # 未列出模型的兜底估算
    assert all(p >= 0 for entry in cc.prices_per_1k_tokens.values() for p in entry.values())
    assert cc.degraded_notice.strip()
    assert cc.report_path.strip()


def test_from_config_factory_reads_central_config(tmp_path: Path):
    """生产接线 factory：窗口/阈值/单价从集中配置读取，行为与直注一致。"""
    cfg = config_loader.load_config()
    fake = _ScriptedFake()
    client = cost_control.BudgetFusedClient.from_config(
        fake,
        cfg,
        budget_path=_write_budget(tmp_path, 5.0),
        report_path=tmp_path / "factory_report.jsonl",
        clock=_ManualClock(),
    )
    assert client._rate_window_seconds == cfg.cost_control.rate_window_seconds
    assert client._rate_max_requests == cfg.cost_control.rate_max_requests
    assert client._prices == cfg.cost_control.prices_per_1k_tokens
    client.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 1
    assert not client.blocked()


# ---------------------------------------------------------------------------
# 3. 请求级限流：滑动窗口（窗口/阈值直注；生产值在 config）
# ---------------------------------------------------------------------------


def test_rate_limit_window_enforced_and_recovers(tmp_path: Path):
    """窗口内第 N+1 次调用抛 RateLimitedError；滑出窗口后恢复。"""
    clock = _ManualClock()
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, window_seconds=60.0, max_requests=2, clock=clock)
    messages = [{"role": "user", "content": "hi"}]

    client.chat(messages)
    client.chat(messages)
    with pytest.raises(cost_control.RateLimitedError):
        client.chat(messages)

    clock.advance(61.0)  # 滑出窗口：全部旧记录失效
    client.chat(messages)
    assert fake.calls == 3


def test_rate_limited_call_not_charged_and_not_reported(tmp_path: Path):
    """限流是瞬时的：被限流的调用既不碰底层客户端也不产生上报行（零成本）。"""
    clock = _ManualClock()
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, max_requests=1, clock=clock)
    messages = [{"role": "user", "content": "hi"}]

    client.chat(messages)
    with pytest.raises(cost_control.RateLimitedError):
        client.chat(messages)

    assert fake.calls == 1
    lines = _report_lines(tmp_path / "cost_report.jsonl")
    assert len(lines) == 1, "限流调用不得计入成本上报"


# ---------------------------------------------------------------------------
# 4. 日预算熔断：超限后调用拒绝、当日恒熔断
# ---------------------------------------------------------------------------


def test_budget_fuse_blocks_calls_after_exhaustion(tmp_path: Path):
    """超限后 chat 抛 BudgetFusedError、blocked() 恒真、底层调用数停增。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, budget_usd=0.0)  # 预算 0：即刻熔断
    assert client.blocked()
    with pytest.raises(cost_control.BudgetFusedError):
        client.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 0, "熔断后底层 LLM 调用数必须停增"


def test_budget_fuse_resets_by_date(tmp_path: Path):
    """当日累计按日期键：换日（时钟推进）后熔断解除，跨日累计不串。"""
    clock = _ManualClock()
    fake = _ScriptedFake()
    report = tmp_path / "cost_report.jsonl"
    today = cost_control.datetime.fromtimestamp(clock()).strftime("%Y-%m-%d")
    # 预置当日累计 1.0（预算 1.0）→ 今天已熔断
    report.write_text(
        json.dumps({"date": today, "est_cost_usd": 1.0}) + "\n", encoding="utf-8"
    )
    client = cost_control.BudgetFusedClient(
        fake,
        budget_path=_write_budget(tmp_path, 1.0),
        report_path=report,
        rate_window_seconds=_CC.rate_window_seconds,
        rate_max_requests=_CC.rate_max_requests,
        chars_per_token=CHARS_PER_TOKEN,
        prices_per_1k_tokens=PRICES,
        clock=clock,
    )
    assert client.blocked()
    with pytest.raises(cost_control.BudgetFusedError):
        client.chat([{"role": "user", "content": "hi"}])

    clock.advance(24 * 3600)  # 推进 24h：新的一天，当日累计重新从当日行求和
    assert not client.blocked()
    client.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 1
    lines = _report_lines(report)
    assert sum(l["est_cost_usd"] for l in lines if l["date"] != today) > 0, "新调用计入新的一天"


# ---------------------------------------------------------------------------
# 5. 成本 JSONL 上报：字段含模型/调用数/估算成本/当日累计
# ---------------------------------------------------------------------------


def test_cost_report_jsonl_fields_and_cumulative(tmp_path: Path):
    """每行含模型/调用数/估算成本；当日累计逐行单调递增；估算为确定性正数。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake)
    messages = [{"role": "user", "content": "唐人街晚上安全吗"}]
    client.chat(messages)
    client.chat(messages)

    lines = _report_lines(tmp_path / "cost_report.jsonl")
    assert len(lines) == 2
    for line in lines:
        assert line["model"] == "deepseek-chat"
        assert line["calls"] == 1
        assert line["est_cost_usd"] > 0
        assert line["est_input_tokens"] > 0 and line["est_output_tokens"] > 0
        assert line["date"] and line["ts"]
    assert lines[1]["daily_cumulative_usd"] > lines[0]["daily_cumulative_usd"]


def test_unknown_model_priced_by_default_entry(tmp_path: Path):
    """未列出的模型按 default 单价估算（不报错、不免费）。"""

    class _OddModel:
        def chat(self, messages, *, model=None, **kwargs):
            return ChatResponse(content="ok", model="some-future-model")

    clock = _ManualClock()
    client = cost_control.BudgetFusedClient(
        _OddModel(),
        budget_path=_write_budget(tmp_path, 5.0),
        report_path=tmp_path / "cost_report.jsonl",
        rate_window_seconds=_CC.rate_window_seconds,
        rate_max_requests=_CC.rate_max_requests,
        chars_per_token=CHARS_PER_TOKEN,
        prices_per_1k_tokens=PRICES,
        clock=clock,
    )
    client.chat([{"role": "user", "content": "abcd"}])  # 4 chars in; 2 chars out ("ok")
    (line,) = _report_lines(tmp_path / "cost_report.jsonl")
    assert line["model"] == "some-future-model"
    est_in = -(-4 // CHARS_PER_TOKEN)
    est_out = -(-2 // CHARS_PER_TOKEN)
    default_price = PRICES["default"]
    assert line["est_cost_usd"] == pytest.approx(
        (est_in * default_price["input"] + est_out * default_price["output"]) / 1000.0
    )


def test_corrupt_report_lines_skipped_not_fatal(tmp_path: Path):
    """单行损坏按 0 计并跳过：熔断器 resilient，不拖垮全部 LLM 流量。"""
    report = tmp_path / "cost_report.jsonl"
    today = cost_control.datetime.fromtimestamp(_ManualClock()()).strftime("%Y-%m-%d")
    report.write_text(
        '{"date": "%s", "est_cost_usd": 0.5}\nnot-json\n{"date": "1999-01-01", "est_cost_usd": 99}\n'
        % today,
        encoding="utf-8",
    )
    client = _make_client(tmp_path, _ScriptedFake())
    assert client._daily_spend(today) == pytest.approx(0.5), "只累计当日完好行"
    assert not client.blocked(), "预算 5 >> 0.5：不熔断"


# ---------------------------------------------------------------------------
# 6. 管线集成：熔断降级不静默，结构化数据照出
# ---------------------------------------------------------------------------


def test_pipeline_prefused_degrades_explicitly_and_keeps_data(tmp_path: Path):
    """票据勾选：预熔断状态下整链路走无 LLM 降级——LLM 调用数停增（0）、
    响应带明示标记与话术、评级/图表/community_info 照出、建议为模板文本。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, budget_usd=0.0)

    first = execute_query("唐人街晚上安全吗", llm_client=client)
    second = execute_query("上东区安全吗", llm_client=client)

    assert fake.calls == 0, "熔断后 LLM 调用数必须停增"
    for result in (first, second):
        assert result.type == "safety"
        assert result.llm_degraded, "降级必须明示，不静默"
        assert result.degradation_notice == config_loader.load_config().cost_control.degraded_notice
        assert result.rating in contracts.LEGAL_RATINGS, "结构化评级照出"
        assert result.charts is not None, "图表数据照出"
        assert result.community_info is not None, "community_info 照出（零 LLM 装配）"
        assert 3 <= len(result.suggestions) <= 5, "建议降级为配置模板文本"


def test_pipeline_mid_query_fuse_falls_back_to_deterministic(tmp_path: Path):
    """查询中途熔断（路由调用恰好耗尽预算）：三维提取退确定性 fallback，
    响应仍完整且带明示标记。"""
    fake_probe = _ScriptedFake()
    probe = _make_client(tmp_path, fake_probe)
    execute_query("唐人街晚上安全吗", llm_client=probe)
    probe_lines = _report_lines(tmp_path / "cost_report.jsonl")
    routing_cost = probe_lines[0]["daily_cumulative_usd"]  # 首行 = 路由调用

    # 预算 = 路由调用成本：路由放行（spend 0 < budget），提取被拒（熔断）。
    # 独立的报告文件：新客户端当日累计从 0 起，不受 probe 上报影响。
    fake = _ScriptedFake()
    client = _make_client(
        tmp_path, fake, budget_usd=routing_cost, report_name="mid_query_report.jsonl"
    )
    result = execute_query("上东区晚上安全吗", llm_client=client)

    assert fake.calls == 1, "路由 1 次后提取被熔断"
    assert result.type == "safety"
    assert result.llm_degraded
    assert result.degradation_notice
    assert result.rating in contracts.LEGAL_RATINGS


def test_pipeline_rate_limited_mid_query_degrades(tmp_path: Path):
    """限流命中在提取阶段：退确定性 fallback + 明示标记（瞬时不熔断当日）。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, max_requests=1)  # 窗口内只允许 1 次（路由用掉）
    result = execute_query("唐人街晚上安全吗", llm_client=client)

    assert fake.calls == 1, "路由放行 1 次，提取被限流"
    assert result.type == "safety"
    assert result.llm_degraded
    assert result.degradation_notice
    assert result.rating in contracts.LEGAL_RATINGS
    assert not client.blocked(), "限流不动当日预算"


def test_pipeline_comparison_carries_degradation_marker(tmp_path: Path):
    """双区对比（本就不用 LLM）：预熔断时对比结果同样带明示标记。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, budget_usd=0.0)
    result = execute_query("上东区和法拉盛哪个更安全", llm_client=client)

    assert result.type == "comparison"
    assert result.llm_degraded
    assert result.degradation_notice
    assert len(result.areas) == 2, "对比数据照出（终局权威在数据，不在 LLM）"


def test_pipeline_degraded_result_carries_degradation_marker(tmp_path: Path):
    """路径降级查询：预熔断时 DegradedResult 同样明示降级（不静默），
    替代信息（真实评级）照出。"""
    fake = _ScriptedFake()
    client = _make_client(tmp_path, fake, budget_usd=0.0)
    result = execute_query("从唐人街到上东区怎么走", llm_client=client)

    assert result.type == "degraded"
    assert result.llm_degraded
    assert result.degradation_notice
    assert fake.calls == 0
    assert result.alternative_info is not None, "覆盖区内替代信息（真实评级）照出"


def test_corrupt_budget_file_fails_safe_not_fatal(tmp_path: Path):
    """预算文件损坏：fail-safe 视同熔断（LLM 降级 + 明示标记），
    零 LLM 的紧急静态分支照常出契约，不 500。"""
    budget_path = tmp_path / "token-budget.json"
    budget_path.write_text("{corrupt", encoding="utf-8")
    fake = _ScriptedFake()
    client = cost_control.BudgetFusedClient(
        fake,
        budget_path=budget_path,
        report_path=tmp_path / "cost_report.jsonl",
        rate_window_seconds=_CC.rate_window_seconds,
        rate_max_requests=_CC.rate_max_requests,
        chars_per_token=CHARS_PER_TOKEN,
        prices_per_1k_tokens=PRICES,
        clock=_ManualClock(),
    )
    safety = execute_query("唐人街晚上安全吗", llm_client=client)
    assert safety.llm_degraded and safety.degradation_notice
    assert fake.calls == 0
    # 紧急第一层是零 LLM 静态分支：预算文件损坏绝不影响紧急响应
    emergency_result = execute_query("救命！有人跟踪我", llm_client=client)
    assert emergency_result.type == "emergency"
    assert not getattr(emergency_result, "llm_degraded", False), "紧急静态分支无 LLM 降级语义"
