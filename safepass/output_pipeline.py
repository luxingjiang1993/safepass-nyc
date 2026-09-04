"""输出控制管线（spec D2，Skill 的运行时；issue 06 / RALPH T4）。

所有 LLM 结构化输出的统一运行时，四段式（D10 参考代码改写）：
    消费者契约 → JSON mode 生成 → 解析/修复 → 结构 + 业务规则校验
    → 有限重试（有上界，读集中配置）→ 明确失败。

改写来源（D10「输出控制管线」行）：
- `11_实战课/examples/helper_planning.py`：validate_* 宿主侧确定性校验 +
  失败反馈回灌下一轮（`_FEEDBACK_TEMPLATE`）；
- `RAG-cy/src/prompts.py`：AnswerSchemaFixPrompt 的修复思路——解析失败先
  json_repair 修复（requirements: json_repair），修复不了才记为解析失败；
- `CASE-智能投研助手（深思熟虑）`：每阶段一个 Pydantic 输出模型（本运行时
  的 contract_model 参数即消费者契约）。

语义约定：
- 尝试次数 = 1 次初始生成 + 配置 `output_pipeline.max_retries` 次重试（上界）；
- 解析失败、结构校验失败、业务校验失败都消耗一次尝试；失败原因回灌进
  下一轮消息（JSON mode 重新生成），不是盲目原样重试；
- 全部尝试耗尽仍不合法 → 抛 OutputPipelineError（明确失败，绝不静默兜底
  出半成品契约）。
"""

from __future__ import annotations

import json
import json_repair
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from safepass import config_loader, contracts
from safepass.llm_client import LLMClient

# 建议条数结构边界（AC-006；spec 决策，非业务阈值系数）
SUGGESTIONS_MIN = 3
SUGGESTIONS_MAX = 5
# one_liner 字数上限（AC-005）
ONE_LINER_MAX_CHARS = 30

_FEEDBACK_TEMPLATE = (
    "你上一次的输出未通过校验：{reason}。"
    "请重新输出，仅输出一个符合契约的 JSON 对象，不要附加任何解释文字。"
)


class OutputPipelineError(RuntimeError):
    """输出控制管线的明确失败：重试耗尽后契约仍不合法，绝不静默兜底。"""


class BusinessValidationError(OutputPipelineError):
    """业务规则校验失败（结构合法但违反业务规则，如 rating 自由文本）。"""


Validator = Callable[[BaseModel], None]


def repair_json_object(raw: str) -> dict[str, Any] | None:
    """解析/修复段：先严格 json.loads，失败则 json_repair 修复（去围栏/补全）。

    只接受 JSON 对象（dict）；数组/标量/修复无果返回 None（记为解析失败）。
    """
    text = raw.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            obj = json_repair.repair_json(text, return_objects=True)
        except Exception:
            return None
    return obj if isinstance(obj, dict) else None


def run_pipeline(
    client: LLMClient,
    messages: Sequence[dict[str, Any]],
    contract_model: type[BaseModel],
    cfg: config_loader.AppConfig,
    *,
    validators: Sequence[Validator] = (),
    model: str | None = None,
    **chat_kwargs: Any,
) -> BaseModel:
    """统一输出控制管线：JSON mode 生成 → 解析/修复 → 结构+业务校验
    → 有限重试（≤ cfg.max_retries）→ 明确失败。

    参数:
        client:      可注入 LLM 客户端（fake/stub/cassette 包装/生产 SDK）。
        messages:    初始消息列表（每轮失败会把反馈追加为新的 user 消息）。
        contract_model: 消费者契约（Pydantic 模型），结构校验的权威。
        validators:  业务规则校验器（见本模块 validate_* / make_*_validator）。
        chat_kwargs: 额外生成参数（默认带 response_format=json_object，可被覆盖）。

    返回:
        通过全部校验的契约实例。

    抛出:
        OutputPipelineError: 1 + max_retries 次尝试后仍不合法（明确失败）。
    """
    max_retries = cfg.max_retries
    total_attempts = max_retries + 1
    current = [dict(m) for m in messages]
    kwargs = {"response_format": {"type": "json_object"}, **chat_kwargs}
    last_reason = "未进行任何尝试"

    for attempt in range(1, total_attempts + 1):
        response = client.chat(current, model=model, **kwargs)
        raw = response.content if isinstance(response.content, str) else str(response.content)

        payload = repair_json_object(raw)
        if payload is None:
            last_reason = f"第 {attempt} 次输出无法解析为 JSON 对象"
        else:
            try:
                obj = contract_model.model_validate(payload)
            except ValidationError as exc:
                last_reason = f"第 {attempt} 次输出未通过结构校验（{contract_model.__name__}）"
            else:
                try:
                    _run_validators(obj, validators)
                except BusinessValidationError as exc:
                    last_reason = f"第 {attempt} 次输出未通过业务校验：{exc}"
                else:
                    return obj
        if attempt < total_attempts:
            current = [*current, {"role": "user", "content": _FEEDBACK_TEMPLATE.format(reason=last_reason)}]

    raise OutputPipelineError(
        f"输出控制管线在 {total_attempts} 次尝试"
        f"（1 次初始生成 + {max_retries} 次重试，配置 output_pipeline.max_retries 上界）"
        f"后仍无法产出合法 {contract_model.__name__}；最后原因：{last_reason}"
    )


def _run_validators(obj: BaseModel, validators: Sequence[Validator]) -> None:
    for validator in validators:
        validator(obj)


def validate_contract(obj: BaseModel, validators: Sequence[Validator]) -> None:
    """对已装配的契约跑同一套业务校验器（装配层的确定性自检，失败即明确抛错）。"""
    _run_validators(obj, validators)


# ---------------------------------------------------------------------------
# 内建业务校验器（可组合；装配层与管线共用同一套）
# ---------------------------------------------------------------------------


def validate_legal_rating(model: BaseModel) -> None:
    """评级字段必须是合法枚举，不出现自由文本（spec D3 / issue 06 勾选 2）。"""
    rating = getattr(model, "rating", None)
    if rating not in contracts.LEGAL_RATINGS:
        raise BusinessValidationError(
            f"rating 必须是合法枚举 {sorted(contracts.LEGAL_RATINGS)}，收到自由文本 {rating!r}"
        )


def validate_one_liner(model: BaseModel, *, max_chars: int = ONE_LINER_MAX_CHARS) -> None:
    """one_liner 必须存在且不超过字数上限（AC-005 结构断言）。"""
    one_liner = getattr(model, "one_liner", None)
    if not isinstance(one_liner, str) or not (0 < len(one_liner) <= max_chars):
        raise BusinessValidationError(f"one_liner 必须存在且 ≤{max_chars} 字，收到 {one_liner!r}")


def make_suggestions_validator(cfg: config_loader.AppConfig) -> Validator:
    """建议结构校验（AC-006）：3-5 条、非空、空话黑名单词（配置）不得单独成条。

    具体性与温暖度是人工抽查项，不在本校验范围。
    """
    blacklist = {w.strip() for w in cfg.suggestions.empty_talk_blacklist if w.strip()}

    def _validate(model: BaseModel) -> None:
        suggestions = getattr(model, "suggestions", None)
        if suggestions is None:
            suggestions = getattr(model, "general_suggestions", None)
        if suggestions is None:
            return  # 该契约无建议字段，不校验
        if not (SUGGESTIONS_MIN <= len(suggestions) <= SUGGESTIONS_MAX):
            raise BusinessValidationError(
                f"建议必须 {SUGGESTIONS_MIN}-{SUGGESTIONS_MAX} 条，收到 {len(suggestions)} 条"
            )
        for suggestion in suggestions:
            stripped = suggestion.strip() if isinstance(suggestion, str) else ""
            if not stripped:
                raise BusinessValidationError("建议不得为空条目")
            if stripped in blacklist:
                raise BusinessValidationError(f"空话黑名单词不得单独成条：{stripped!r}")

    return _validate


def validate_non_empty_disclaimer(model: BaseModel) -> None:
    """免责声明是全部响应形态（spec D3 四种 + issue 09 guardrail）共有的必填横切字段（AC-010）。"""
    disclaimer = getattr(model, "disclaimer", None)
    if not isinstance(disclaimer, str) or not disclaimer.strip():
        raise BusinessValidationError(f"disclaimer 不得为空，收到 {disclaimer!r}")
