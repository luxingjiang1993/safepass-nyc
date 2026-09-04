"""FC 路由层（spec D2；issue 06 / RALPH T4 接入统一输出控制管线）。

LLM function calling，将查询路由到声明的工具集合：
    area_safety_query    覆盖区内安全查询
    area_comparison      双区对比
    follow_up            两种有限追问（对比追问 / 细节追问）
    degraded_response    路径/趋势/越界降级共用（意图细分区分文案）
    emergency_help       紧急兜底（第二层）

LLM 路径走统一输出控制管线（output_pipeline.run_pipeline）：
JSON mode 生成 → 解析/修复 → Pydantic 结构 + 业务规则校验
→ 有限重试（≤ 配置 output_pipeline.max_retries）→ 明确失败。
重试耗尽抛 OutputPipelineError，绝不静默兜底路由——诚实兜底在 D12
后置校验与评级引擎，不在"装作看懂了"。

注意：路由结果不具终局权威——越界判定由 D12 确定性后置在数据查询前强制改写
（pipeline.execute_query），即使 LLM 把越界查询误路由到 area_safety_query。

静态意图标记（path/trend，配置 degraded.path_pair_markers/path_markers/
trend_markers）优先、零 LLM 命中即返回；未注入客户端时回退
area_safety_query（离线场景，终局权威仍在 D12 后置校验）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from safepass import config_loader, output_pipeline
from safepass.llm_client import LLMClient

ROUTE_AREA_SAFETY = "area_safety_query"
ROUTE_AREA_COMPARISON = "area_comparison"
ROUTE_FOLLOW_UP = "follow_up"
ROUTE_DEGRADED = "degraded_response"
ROUTE_EMERGENCY = "emergency_help"
LEGAL_ROUTES = frozenset(
    {ROUTE_AREA_SAFETY, ROUTE_AREA_COMPARISON, ROUTE_FOLLOW_UP, ROUTE_DEGRADED, ROUTE_EMERGENCY}
)
LEGAL_DEGRADED_CAPABILITIES = frozenset({"path", "trend"})

_SYSTEM_PROMPT = (
    "你是 SafePass NYC 的查询路由助手。把用户查询路由到唯一工具，"
    "以 JSON 输出：{\"route\": <工具名>, \"degraded_capability\": <path|trend|null>}。"
    f"合法工具：{ROUTE_AREA_SAFETY}（覆盖区内安全查询）、{ROUTE_AREA_COMPARISON}（双区对比）、"
    f"{ROUTE_DEGRADED}（路径/趋势等开发中能力的降级响应）、{ROUTE_FOLLOW_UP}（承接上轮地点的追问）、"
    f"{ROUTE_EMERGENCY}（紧急求助）。仅输出 JSON。"
)


@dataclass(frozen=True)
class RouteDecision:
    """一次路由判定的最小结果。degraded_capability 非空表示命中降级意图细分。"""

    route: str
    degraded_capability: str | None = None


class RouteContract(BaseModel):
    """FC 路由的结构化输出契约（输出控制管线的消费者契约）。"""

    route: str
    degraded_capability: str | None = None


def _validate_route_contract(model: RouteContract) -> None:
    """路由业务规则：工具名必须合法；capability 细分只许挂在降级工具上。"""
    if model.route not in LEGAL_ROUTES:
        raise output_pipeline.BusinessValidationError(
            f"非法路由 {model.route!r}，合法工具集合：{sorted(LEGAL_ROUTES)}"
        )
    if model.route == ROUTE_DEGRADED:
        if (
            model.degraded_capability is not None
            and model.degraded_capability not in LEGAL_DEGRADED_CAPABILITIES
        ):
            raise output_pipeline.BusinessValidationError(
                f"degraded_capability 必须是 path|trend|null，收到 {model.degraded_capability!r}"
            )
    elif model.degraded_capability:
        raise output_pipeline.BusinessValidationError(
            f"route={model.route!r} 非降级工具，不得携带 degraded_capability"
        )


def _static_capability(query_text: str, cfg: config_loader.AppConfig) -> str | None:
    """确定性意图细分：成对标记（config degraded.path_pair_markers）全部出现
    或任一单标记 → path；趋势标记 → trend。"""
    markers = cfg.degraded
    paired = bool(markers.path_pair_markers) and all(
        m in query_text for m in markers.path_pair_markers
    )
    if paired or any(m in query_text for m in markers.path_markers):
        return "path"
    if any(m in query_text for m in markers.trend_markers):
        return "trend"
    return None


def _llm_decision(
    query_text: str, llm_client: LLMClient, cfg: config_loader.AppConfig
) -> RouteDecision:
    """单轮 JSON mode 路由询问，走统一输出控制管线：损坏/非法输出在有限重试
    内修复收敛，耗尽后抛 OutputPipelineError（明确失败，不静默兜底路由）。"""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": query_text},
    ]
    contract = output_pipeline.run_pipeline(
        llm_client,
        messages,
        RouteContract,
        cfg,
        validators=[_validate_route_contract],
    )
    capability = contract.degraded_capability if contract.route == ROUTE_DEGRADED else None
    return RouteDecision(route=contract.route, degraded_capability=capability)


def route_query(
    query_text: str,
    llm_client: LLMClient | None,
    cfg: config_loader.AppConfig,
) -> RouteDecision:
    """路由判定入口：静态标记优先（零 LLM），否则走注入客户端（可 fake/cassette）。"""
    capability = _static_capability(query_text, cfg)
    if capability is not None:
        return RouteDecision(route=ROUTE_DEGRADED, degraded_capability=capability)
    if llm_client is not None:
        return _llm_decision(query_text, llm_client, cfg)
    return RouteDecision(route=ROUTE_AREA_SAFETY)
