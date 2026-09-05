"""成本三件套（票 06 / M2）：日预算熔断 + 请求级限流 + 成本 JSONL 上报。

包装器模式：`BudgetFusedClient` 包装任意 ``LLMClient``，挂在协议注入点
（`pipeline.execute_query` 的 llm_client 参数），三重职责：

1.  **限流**：进程级滑动窗口（窗口/阈值在 config cost_control.rate_limit），
    窗口内调用超限抛 ``RateLimitedError``（瞬时限流，不动当日预算）；
2.  **熔断**：日累计估算成本 ≥ token-budget.json 的 daily_cost_budget_usd
    后拒绝一切 LLM 调用（抛 ``BudgetFusedError``）。管线把熔断中的客户端
    视同未注入：路由走确定性默认、三维提取走确定性 fallback——结构化数据
    照出、建议降级为模板文本、响应带明示标记（config degraded_notice）；
3.  **上报**：每次真实调用按确定性近似估算成本并追加一行 JSONL
    （模型/调用数/输入输出估算 token/估算成本/当日累计）。
    当日累计 = 当日 JSONL 行求和——上报文件即累计事实源，重启不丢
    （红线：持久化 = 文件，禁服务型数据库）。

成本估算（ChatResponse 无 token 计数，确定性近似）：
``tokens ≈ ceil(chars / chars_per_token)``（系数在 config），
``cost = (in·input价 + out·output价) / 1000``（单价 USD/1K tokens，在
config cost_control.estimation.prices_per_1k_tokens；未列出的模型按
default 条目估算）。估算是上界近似，宁可高估不低估，保证熔断提前于破产。
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from safepass import config_loader
from safepass.llm_client import ChatResponse, LLMClient

# token-budget.json / 默认上报路径相对项目根（与 config_loader 同锚点）
PROJECT_ROOT = config_loader.PROJECT_ROOT
DEFAULT_BUDGET_PATH = PROJECT_ROOT / "token-budget.json"


class CostControlError(RuntimeError):
    """成本控制的明确失败基类（限流/熔断）；管线据此走确定性降级。"""


class RateLimitedError(CostControlError):
    """请求级限流：滑动窗口内 LLM 调用超上限（瞬时限流，非当日熔断）。"""


class BudgetFusedError(CostControlError):
    """日预算熔断：当日累计估算成本已达 token-budget.json 预算上限。"""


def load_daily_budget_usd(budget_path: str | Path = DEFAULT_BUDGET_PATH) -> float | None:
    """读取 token-budget.json 的 daily_cost_budget_usd；null/缺失文件 = 不熔断。"""
    path = Path(budget_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CostControlError(f"预算文件损坏：{path}（{exc}）") from exc
    raw = data.get("daily_cost_budget_usd")
    return None if raw is None else float(raw)


def is_fused_blocked(client: LLMClient | None) -> bool:
    """管线判定：注入的客户端是否处于日预算熔断中（只认本模块包装器）。"""
    return isinstance(client, BudgetFusedClient) and client.blocked()


class BudgetFusedClient:
    """LLMClient 包装器：限流 → 熔断 → 调用底层 → 估算成本并上报 JSONL。

    参数全部显式注入（生产经 ``from_config`` 从集中配置读取，测试直注），
    本模块不内置任何阈值字面量（红线 1）。
    """

    def __init__(
        self,
        inner: LLMClient,
        *,
        budget_path: str | Path,
        report_path: str | Path,
        rate_window_seconds: float,
        rate_max_requests: int,
        chars_per_token: int,
        prices_per_1k_tokens: dict[str, dict[str, float]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._inner = inner
        self._budget_path = Path(budget_path)
        self._report_path = Path(report_path)
        self._rate_window_seconds = float(rate_window_seconds)
        self._rate_max_requests = int(rate_max_requests)
        self._chars_per_token = int(chars_per_token)
        self._prices = prices_per_1k_tokens
        self._clock = clock
        # 限流窗口是进程级内存态（天然瞬时限流语义）；日累计从上报文件求和
        self._window: deque[float] = deque()

    @property
    def inner(self) -> LLMClient:
        """被包装的真实客户端（只读；票 12 接线测试据此断言"必经熔断器"结构）。"""
        return self._inner

    # -- 配置接线 -----------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        inner: LLMClient,
        cfg: config_loader.AppConfig,
        *,
        budget_path: str | Path = DEFAULT_BUDGET_PATH,
        report_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> "BudgetFusedClient":
        """生产接线：限流窗口/估算参数读集中配置，日预算读 token-budget.json。"""
        cc = cfg.cost_control
        resolved_report = (
            Path(report_path)
            if report_path is not None
            else PROJECT_ROOT / cc.report_path
        )
        return cls(
            inner,
            budget_path=budget_path,
            report_path=resolved_report,
            rate_window_seconds=cc.rate_window_seconds,
            rate_max_requests=cc.rate_max_requests,
            chars_per_token=cc.chars_per_token,
            prices_per_1k_tokens=cc.prices_per_1k_tokens,
            clock=clock,
        )

    # -- 熔断判定 -----------------------------------------------------------

    def _today(self) -> str:
        return datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d")

    def _daily_spend(self, date: str) -> float:
        """当日累计估算成本 = 上报文件当日行求和（文件即事实源，重启不丢）。

        损坏行按 0 计并跳过：熔断器必须 resilient，单行损坏不拖垮全部 LLM 流量；
        代价是极端情况下低估，方向安全（配合估算是上界近似）。
        """
        path = self._report_path
        if not path.exists():
            return 0.0
        total = 0.0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0.0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("date") == date:
                total += float(entry.get("est_cost_usd") or 0.0)
        return total

    def blocked(self) -> bool:
        """日预算熔断判定：预算为 null（未配置）永不熔断；超限后当日恒熔断。"""
        budget = load_daily_budget_usd(self._budget_path)
        return budget is not None and self._daily_spend(self._today()) >= budget

    # -- 限流 ---------------------------------------------------------------

    def _check_rate_limit(self, now: float) -> None:
        window = self._window
        cutoff = now - self._rate_window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= self._rate_max_requests:
            raise RateLimitedError(
                f"请求级限流：{self._rate_window_seconds:g}s 窗口内已达 "
                f"{self._rate_max_requests} 次 LLM 调用上限，请稍后重试"
            )
        window.append(now)

    # -- 成本估算与上报 -----------------------------------------------------

    def _estimate_tokens_from_chars(self, chars: int) -> int:
        if chars <= 0:
            return 0
        return -(-chars // self._chars_per_token)  # ceil 除法，确定性

    def _price_for(self, model: str) -> dict[str, float]:
        # 直取键（缺键即 KeyError 明确失败）：config_loader 已校验 input/output
        # 齐备，缺键计价 = 免费调用，违反"宁可高估不低估"不变量，禁止静默兜底。
        return self._prices.get(model) or self._prices["default"]

    def _record(
        self,
        messages: Sequence[dict[str, Any]],
        response: ChatResponse,
        model: str | None,
        now: float,
    ) -> None:
        """估算本次调用成本并追加一行 JSONL（字段：模型/调用数/估算成本/累计）。"""
        in_chars = sum(len(str(m.get("content", ""))) for m in messages)
        est_in = self._estimate_tokens_from_chars(in_chars)
        est_out = self._estimate_tokens_from_chars(len(response.content or ""))
        billed_model = response.model or model or "unknown"
        price = self._price_for(billed_model)
        cost = (est_in * price["input"] + est_out * price["output"]) / 1000.0
        date = self._today()
        cumulative = self._daily_spend(date) + cost
        entry = {
            "ts": now,
            "date": date,
            "model": billed_model,
            "calls": 1,
            "est_input_tokens": est_in,
            "est_output_tokens": est_out,
            "est_cost_usd": cost,
            "daily_cumulative_usd": cumulative,
        }
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        with self._report_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    # -- LLMClient 协议 -----------------------------------------------------

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """协议注入点：熔断 → 限流 → 底层调用 → 成本上报。明确失败，不静默。"""
        now = self._clock()
        if self.blocked():
            raise BudgetFusedError(
                "日预算熔断：当日估算成本已达 token-budget.json 上限，"
                "本次及当日剩余请求走无 LLM 降级"
            )
        self._check_rate_limit(now)
        response = self._inner.chat(messages, model=model, **kwargs)
        self._record(messages, response, model, now)
        return response
