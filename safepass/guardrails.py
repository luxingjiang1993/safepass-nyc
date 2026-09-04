"""负例防线静态守卫（issue 09 / RALPH T7；NEG-003/004/006）。

零 LLM 确定性判定（D12 同款思路：LLM 之上不允许"装作看懂了"的自由裁量）：

    种族偏见诱导（NEG-003）  命中 bias_markers → GuardrailResult(bias_refusal)：
                            拒绝按族裔评判社区，话术转向结构性解释
                            （安全由可核实公开数据决定，与族裔构成无关）；
    武器防身建议（NEG-004）  命中 weapon_markers → GuardrailResult(weapon_refusal)：
                            拒绝器械建议，alternatives 引导合法途径
                            （话术不得包含任何被禁器械词）；
    恐慌性夸大（NEG-006）    panic_blacklist 不直接触发分支，而是安全查询装配层的
                            确定性自检：叙事文本命中黑名单词 → 明确失败，绝不带病透出。

管线执行顺序（pipeline.execute_query）：第一层紧急检测 → FC 路由 →
紧急第二层（emergency_help 兜底）→ 本守卫 → 追问承接/D12/数据查询。
紧急两层都优先于拒绝：用户用不含关键词的表述描述紧急情况时（如
"有人要袭击我，快告诉我怎么防身"）由路由层接住进紧急模式，不被守卫截胡；
守卫本身仍零 LLM、纯静态表判定。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from safepass import config_loader, contracts, output_pipeline

# 合法途径建议的结构边界（与贴心建议同宽；单一事实源借 output_pipeline 的边界常量）
_ALTERNATIVES_MIN = output_pipeline.SUGGESTIONS_MIN
_ALTERNATIVES_MAX = output_pipeline.SUGGESTIONS_MAX


def check(query_text: str, cfg: config_loader.AppConfig) -> str | None:
    """静态守卫判定：返回 guardrail_kind 或 None。

    偏见优先于武器（一句查询同时命中两类时，偏见转向是更根本的回应）。
    执行序由管线保证：本判定在 FC 路由与紧急第二层**之后**——紧急兜底
    （emergency_help）优先于拒绝，用户用不含关键词的表述描述紧急情况时
    不会被武器/偏见守卫截胡（spec D2/D7 的第二层不被遮蔽）。
    """
    g = cfg.guardrails
    if any(m in query_text for m in g.bias_markers):
        return contracts.GUARDRAIL_BIAS
    if any(m in query_text for m in g.weapon_markers):
        return contracts.GUARDRAIL_WEAPON
    return None


def _validate_alternatives(model: BaseModel) -> None:
    """转向建议结构校验：非空、条数有界。"""
    alternatives = getattr(model, "alternatives", None)
    if alternatives is None:
        return
    if not (_ALTERNATIVES_MIN <= len(alternatives) <= _ALTERNATIVES_MAX):
        raise output_pipeline.BusinessValidationError(
            f"转向建议必须 {_ALTERNATIVES_MIN}-{_ALTERNATIVES_MAX} 条，收到 {len(alternatives)} 条"
        )
    for item in alternatives:
        if not isinstance(item, str) or not item.strip():
            raise output_pipeline.BusinessValidationError("转向建议不得为空条目")


def _check_empty_talk(alternatives: list[str], cfg: config_loader.AppConfig) -> None:
    """空话黑名单词（配置）不得单独成条——与贴心建议同一防线。"""
    blacklist = {w.strip() for w in cfg.suggestions.empty_talk_blacklist if w.strip()}
    offender = next((a for a in alternatives if a.strip() in blacklist), None)
    if offender is not None:
        raise output_pipeline.BusinessValidationError(
            f"空话黑名单词不得单独成条：{offender!r}"
        )


def build_guardrail_result(
    kind: str, cfg: config_loader.AppConfig
) -> contracts.GuardrailResult:
    """装配 GuardrailResult：拒绝话术单一事实源在配置（bias_* / weapon_*）。

    拒绝形态不携带任何评级/区域分析字段——绝不"边拒绝边分析"（NEG-003/004）。
    """
    g = cfg.guardrails
    if kind == contracts.GUARDRAIL_BIAS:
        message, alternatives = g.bias_message, list(g.bias_alternatives)
    elif kind == contracts.GUARDRAIL_WEAPON:
        message, alternatives = g.weapon_message, list(g.weapon_alternatives)
        # 结构性保证：合法途径建议里绝不出现被禁器械词（配置被破坏时明确失败）
        offenders = [w for w in g.weapon_markers if any(w in a for a in alternatives)]
        if offenders:
            raise config_loader.ConfigError(
                f"guardrails.weapon_alternatives 不得包含器械词：{offenders}"
            )
    else:  # 防御：check 只产出合法 kind
        raise ValueError(f"非法负例防线形态：{kind!r}")

    result = contracts.GuardrailResult(
        guardrail_kind=kind,  # type: ignore[arg-type]
        message=message,
        alternatives=alternatives,
        sources=[],
        disclaimer=cfg.disclaimer,
    )
    # 装配层确定性自检：横切字段 + 转向建议结构过同一套业务校验器
    _check_empty_talk(alternatives, cfg)
    output_pipeline.validate_contract(
        result,
        validators=(
            _validate_alternatives,
            output_pipeline.validate_non_empty_disclaimer,
        ),
    )
    return result


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, (list, tuple)):
        return [s for v in node for s in _strings(v)]
    return []


def make_no_panic_validator(cfg: config_loader.AppConfig) -> output_pipeline.Validator:
    """恐慌词黑名单校验器（NEG-006）：安全查询叙事文本（排除静态紧急资源清单）
    命中 panic_blacklist 任一词汇 → 明确失败，绝不带病透出契约。"""
    blacklist = tuple(cfg.guardrails.panic_blacklist)

    def _validate(model: BaseModel) -> None:
        dump = model.model_dump(exclude={"emergency_resources"})
        text = "\n".join(_strings(dump))
        hit = next((w for w in blacklist if w in text), None)
        if hit is not None:
            raise output_pipeline.BusinessValidationError(
                f"安全查询叙事文本命中恐慌词黑名单：{hit!r}（NEG-006 不制造恐慌）"
            )

    return _validate
