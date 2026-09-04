"""三维提取（issue 09 / RALPH T7；spec F1-2 / AC-002）。

从查询文本提取三个维度：区域 / 人群 / 时间。两条路径，输出同一契约：

    注入 llm_client：单轮 JSON mode 询问，走统一输出控制管线
    （解析/修复 → 结构 + 业务校验 → 有限重试 → 明确失败）；
    测试经 cassette 固定模型响应，回放零真实调用（RALPH.md T7 三维提取）。

    未注入客户端（离线/零 LLM 场景）：确定性 fallback——区域走别名表
    （addressing.resolve_areas），人群/时间走配置标记表
    （followup.crowd_markers / time_markers），与追问细分同一事实源。

三维提取只作用于个性化表述（spec D5 / ADR-0002），永不进入评级输入；
未提到的维度输出 null（诚实，不编造）。
"""

from __future__ import annotations

from pydantic import BaseModel

from safepass import addressing, config_loader, followup, output_pipeline
from safepass.llm_client import LLMClient

_SYSTEM_PROMPT = (
    "你是 SafePass NYC 的查询维度提取器。从用户查询中提取三个维度，以 JSON 输出："
    '{"area": <提到的区域原文或 null>, "crowd": <人群描述原文或 null>, '
    "'time': <时间描述原文或 null>}。只提取查询中明确出现的信息，"
    "未提到的维度输出 null，不要推测。仅输出 JSON。"
)


class ExtractionContract(BaseModel):
    """三维提取的结构化输出契约（输出控制管线的消费者契约，AC-002）。"""

    area: str | None = None
    crowd: str | None = None
    time: str | None = None


def _validate_extraction(model: ExtractionContract) -> None:
    """提取业务规则：非空维度必须是去空白后非空的字符串（不允许 "" 这类伪提取）。"""
    for field_name in ("area", "crowd", "time"):
        value = getattr(model, field_name)
        if value is not None and not value.strip():
            raise output_pipeline.BusinessValidationError(
                f"提取维度 {field_name} 不得为空字符串（未提到应输出 null）"
            )


def _fallback(query_text: str, cfg: config_loader.AppConfig) -> ExtractionContract:
    """确定性 fallback（零 LLM）：别名表 + 配置标记表，与追问细分同一事实源。"""
    resolved = addressing.resolve_areas(query_text, cfg)
    crowd = next((m for m in cfg.followup.crowd_markers if m in query_text), None)
    time = next((m for m in cfg.followup.time_markers if m in query_text), None)
    return ExtractionContract(
        area=resolved[0].area if resolved else None,
        crowd=crowd,
        time=time,
    )


def extract(
    query_text: str,
    llm_client: LLMClient | None,
    cfg: config_loader.AppConfig,
) -> ExtractionContract:
    """三维提取入口：注入客户端走 LLM 管线；否则走确定性 fallback。"""
    if llm_client is None:
        return _fallback(query_text, cfg)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": query_text},
    ]
    return output_pipeline.run_pipeline(
        llm_client,
        messages,
        ExtractionContract,
        cfg,
        validators=[_validate_extraction],
    )
