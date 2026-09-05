"""L2 LLM-as-judge 评估器（issue 03 / M1，spec v2「L2」节）。

改写自参考代码 `可用来参考的代码案例/CASE-openevals使用/`（逐组件来源标注）：

- judge 调用形态（feedback_key + judge=注入 LLM + temperature=0 考官）
  ← `CASE-openevals使用/5-rag_groundedness.py:18-26`（create_llm_as_judge 参数面）
  ← `CASE-openevals使用/8-hallucination.py:18-26`、`3-answer_relevance.py:18-26`
- groundedness 评估维度（回答逐句对照证据支持度）
  ← `CASE-openevals使用/5-rag_groundedness.py`（openevals RAG_GROUNDEDNESS_PROMPT 语义）
- hallucination 评估维度（inputs/outputs/evidence/reference 四输入对照）
  ← `CASE-openevals使用/8-hallucination.py`（openevals HALLUCINATION_PROMPT 语义）
- relevance 评估维度（outputs 对 inputs 的直接相关度）
  ← `CASE-openevals使用/3-answer_relevance.py`（openevals ANSWER_RELEVANCE_PROMPT 语义）

改写要点（openevals/langchain 依赖未引入，Karpathy 宪法①：std_lib + 既有依赖可解
决的绝不引框架）：

1. 提示词模板中文化 + SafePass 域改写；模板版本字符串锁定进
   `config/app.yaml` 的 `eval.prompt_versions`（spec：评估基准不随依赖漂移）；
2. 评分输出统一为结构化 JSON（`{"score", "reason"}` 等），解析走既有
   `json_repair`（与 `safepass/output_pipeline.py` 同一修复依赖，不新增）；
3. judge 客户端走可注入 `LLMClient` 协议（`safepass/llm_client.py`），
   测试与录制经 `chat_with_cassette` 回放（prior art：tests/test_emergency.py）；
4. 考官模型名 + 通过分数线全部经 `config_loader` 读取，本模块零业务字面量。

红线条款：judge 只评估生成质量，不参与安全评级/可信度/越界判定
（LLM 不掺和确定性后置，D12）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import json_repair

from safepass import config_loader
from safepass.llm_client import LLMClient, chat_with_cassette

# 三类 evaluator 的 feedback_key（spec v2 指标：groundedness / 幻觉率 / 建议相关性）。
# 键名是标识符不是阈值；每键的版本字符串单一事实源在 config eval.prompt_versions。
FEEDBACK_GROUNDEDNESS = "groundedness"
FEEDBACK_HALLUCINATION = "hallucination"
FEEDBACK_RELEVANCE = "relevance"
LEGAL_FEEDBACK_KEYS = frozenset(
    {FEEDBACK_GROUNDEDNESS, FEEDBACK_HALLUCINATION, FEEDBACK_RELEVANCE}
)

# ---------------------------------------------------------------------------
# 提示词模板（改写来源逐条见各模板上方标注；{inputs}/{outputs}/{evidence}/
# {reference} 为渲染占位，judge 只见填充后的单条 user message）
# ---------------------------------------------------------------------------

# ← CASE-openevals使用/5-rag_groundedness.py（RAG_GROUNDEDNESS 语义：逐句核对
#   回答是否被上下文支持；中文化 + 区分事实性陈述与模板话术。
#   v2：明确豁免项——三维提取继承自用户查询本身，图表数据由证据中的聚合
#   统计派生，「证据未逐字给出但可由证据推出」视为有依据（v1 实测 qwen-turbo
#   把这类声明误判为无支撑，groundedness_mean 被压到 0.51））
GROUNDEDNESS_TEMPLATE = """你是 SafePass NYC（纽约公共安全情报产品）的生成质量考官。判断【回答】中的事实性陈述是否被【证据】支持。

【用户查询】
{inputs}

【证据】（系统从公开犯罪数据聚合的真实结果，是回答唯一允许依赖的事实来源）
{evidence}

【回答】（系统产出的结构化响应）
{outputs}

判定规则：
1. 逐条核对回答中的事实性陈述（安全评级、样本量、倍数、占比、案件数、警区号、top5 案件类型、昼夜分布、时间范围等）是否能在【证据】中找到依据；
2. 【证据】不支持或与【证据】矛盾的声明，每条都显著降分；
3. 以下声明永不参与 groundedness 判定（系统其他确定性来源，无事实主张）：
   - 建议类、安抚类、流程性话术（规则模板生成）；
   - 回答中 extracted 字段（区域/人群/时间）：继承自【用户查询】本身，不是事实声明；
   - 回答中的画像时间提示与个性化建议（来自用户画像，不是数据结论）；
   - 图表细分数据（top5 类型/昼夜分布）：由【证据】中的聚合统计派生，证据给出聚合统计即视为有依据；
4. 【证据】标注为降级/越界（无数据支撑）时，回答中允许出现的内容（出现均不扣分、不构成矛盾）：
   - 警区号识别与「不在覆盖范围」说明（地址别名表与覆盖清单的产物，非犯罪数据）；
   - 替代信息中给出的覆盖内区域真实评级（见证据的 alternative_data 字段）；
   - 通用建议、紧急资源、覆盖区域重选邀请、免责声明。
   除此之外的犯罪数据性结论（评级/案件数/犯罪率/占比/趋势/路径）出现即矛盾；
5. score：1.0 = 全部事实性陈述有证据支持；0.0 = 存在与证据矛盾的声明；部分支持按比例扣分。

只输出 JSON，不要输出其他内容：{{"score": <0.0~1.0 的数字>, "reason": "<逐条核对说明，中文>"}}"""

# ← CASE-openevals使用/8-hallucination.py（HALLUCINATION 语义：context/inputs/
#   outputs/reference_outputs 四输入；reference 此处 = 金标 must_not_claim。
#   v2：禁止声明按完整命题语义匹配——只出现命题中的个别词语不构成违规
#   （v1 实测 qwen-turbo 把回答里的「女生」「晚上」等查询原词当成禁止声明命中，
#   幻觉率虚高到 0.80））
HALLUCINATION_TEMPLATE = """你是 SafePass NYC（纽约公共安全情报产品）的生成质量考官。判断【回答】是否包含幻觉声明。

【用户查询】
{inputs}

【证据】（系统数据聚合结果；降级/越界查询标注为无数据支撑）
{evidence}

【回答】（系统产出的结构化响应）
{outputs}

【禁止声明与必答要求】（人工金标 JSON：must_not_claim = 禁止断言；must_mention = 必须覆盖的关键信息，与它们一致的内容绝不违规）
{reference}

判定规则：
1. 回答出现与【证据】矛盾的事实性声明 → hallucinated=true；
2. 【禁止声明】是人工摘录的禁止断言（完整命题或命题片段）。先理解它禁止的断言是什么，再在【回答】中找出表达该断言的具体文本（含近义改写）：找得出具体断言文本才判 true；
3. 仅出现禁止声明里的个别词语（地名、人群词、时间词、警区号）不构成违规；复述【用户查询】原词、承接上文出现的维度/提示字段同样不构成幻觉；
4. 回答中 extracted 字段（区域/人群/时间）继承自【用户查询】本身；画像时间提示与个性化建议来自用户画像；这些字段永不构成幻觉；
5. 【必须覆盖的关键信息】（reference 的 must_mention 字段）是人工金标要求回答必须覆盖的内容：与它们一致的内容绝不可能是违规内容；
6. 【证据】标注为降级/越界（无数据支撑）时：给出犯罪数据性结论（评级/案件数/犯罪率/占比/趋势/路径）即 hallucinated=true；警区号识别与「不在覆盖范围」说明来自地址别名表，属合规内容；
7. 回答以否定/声明不提供的方式提及某信息（如「长期趋势对比维度仍在开发中，暂不提供」）不构成对该信息的声称，不违规；
8. 建议类、安抚类、流程性话术永不构成幻觉；
9. score：hallucinated=false → 1.0；hallucinated=true → 0.0。

只输出 JSON，不要输出其他内容：{{"hallucinated": <true 或 false>, "reason": "<说明，中文>"}}"""

# ← CASE-openevals使用/3-answer_relevance.py（ANSWER_RELEVANCE 语义：outputs 对
#   inputs 的直接相关度；reference 此处 = 金标 must_mention 关键信息）
RELEVANCE_TEMPLATE = """你是 SafePass NYC（纽约公共安全情报产品）的生成质量考官。判断【回答】是否直接回应了【用户查询】。

【用户查询】
{inputs}

【回答】（系统产出的结构化响应）
{outputs}

【必须覆盖的关键信息】（人工金标；空列表表示无额外要求）
{reference}

判定规则：
1. 回答应直接针对查询意图（问 A 答 A，不答非所问）；
2. 【必须覆盖的关键信息】逐条核对是否被回答覆盖（语义等价即可，不要求字面一致），每条缺失显著降分；
3. 降级/越界查询的诚实说明（告知无数据 + 通用建议）视为对相关查询的合格回应；
4. score：1.0 = 完全相关且关键信息全覆盖；0.0 = 与查询无关。

只输出 JSON，不要输出其他内容：{{"score": <0.0~1.0 的数字>, "reason": "<说明，中文>"}}"""

PROMPT_TEMPLATES: dict[str, str] = {
    FEEDBACK_GROUNDEDNESS: GROUNDEDNESS_TEMPLATE,
    FEEDBACK_HALLUCINATION: HALLUCINATION_TEMPLATE,
    FEEDBACK_RELEVANCE: RELEVANCE_TEMPLATE,
}

# 渲染占位符：每个 evaluator 统一四个槽位（对齐改写来源
# CASE-openevals使用/8-hallucination.py 的 evaluator(context=..., inputs=...,
# outputs=..., reference_outputs=...) 调用面）。
_TEMPLATE_SLOTS = ("inputs", "outputs", "evidence", "reference")


class JudgeError(RuntimeError):
    """judge 输出不可解析或违反评分契约时抛出（明确失败，不静默兜底）。"""


@dataclass(frozen=True)
class JudgeVerdict:
    """一次 L2 判定的结构化结果（可序列化进结果工件与指标聚合）。"""

    feedback_key: str
    score: float  # 0.0~1.0（hallucination 为二元 0.0/1.0，1.0 = 无幻觉）
    reason: str
    prompt_version: str
    judge_model: str


def _check_config(cfg: config_loader.AppConfig) -> None:
    """配置不变量：三个 feedback_key 的提示词与版本锁定齐备。"""
    versions = cfg.eval.prompt_versions
    missing = LEGAL_FEEDBACK_KEYS - set(versions)
    if missing:
        raise JudgeError(f"eval.prompt_versions 缺少版本锁定：{sorted(missing)}")
    for key, version in versions.items():
        if key not in PROMPT_TEMPLATES:
            raise JudgeError(f"eval.prompt_versions 出现未知 feedback_key：{key}")
        if not str(version).strip():
            raise JudgeError(f"eval.prompt_versions[{key}] 为空（提示词版本必须锁定）")


def _render(template: str, slots: dict[str, str]) -> str:
    try:
        return template.format(**slots)
    except KeyError as exc:  # 防御：模板与槽位漂移立即失败
        raise JudgeError(f"提示词模板槽位缺失：{exc}") from exc


def _parse_score(payload: Any, feedback_key: str) -> float:
    """连续分 evaluator 的分数契约：数值、有限、落在 [0, 1]（越界即明确失败）。"""
    try:
        score = float(payload)
    except (TypeError, ValueError) as exc:
        raise JudgeError(f"judge[{feedback_key}] 的 score 非数值：{payload!r}") from exc
    if not math.isfinite(score):
        raise JudgeError(f"judge[{feedback_key}] 的 score 非有限数：{payload!r}")
    if not 0.0 <= score <= 1.0:
        raise JudgeError(
            f"judge[{feedback_key}] 的 score 越界：{score}（契约区间 [0, 1]，"
            "考官输出不守契约时明确失败，不静默 clamp）"
        )
    return score


def _parse_verdict(feedback_key: str, content: str, cfg: config_loader.AppConfig) -> JudgeVerdict:
    """judge 原始输出 → 结构化判定（json_repair 修复后契约校验，不过不静默）。"""
    payload = json_repair.loads(content)
    if not isinstance(payload, dict):
        raise JudgeError(f"judge[{feedback_key}] 输出非 JSON 对象：{content[:120]!r}")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise JudgeError(f"judge[{feedback_key}] 缺 reason（判定必须给出说明）")
    if feedback_key == FEEDBACK_HALLUCINATION:
        # 幻觉判定的权威字段是布尔 hallucinated；score 由它派生（二元契约），
        # judge 自填的分数不采信（对齐 0/1 幻觉率口径）。
        hallucinated = payload.get("hallucinated")
        if not isinstance(hallucinated, bool):
            raise JudgeError(f"judge[{feedback_key}] 缺布尔 hallucinated：{content[:120]!r}")
        score = 0.0 if hallucinated else 1.0
    else:
        score = _parse_score(payload.get("score"), feedback_key)
    return JudgeVerdict(
        feedback_key=feedback_key,
        score=score,
        reason=reason.strip(),
        prompt_version=cfg.eval.prompt_versions[feedback_key],
        judge_model=cfg.eval.judge_model,
    )


def build_evaluator(
    feedback_key: str,
    *,
    judge_client: LLMClient,
    cfg: config_loader.AppConfig,
    cassette_path: str | None = None,
    record: bool = False,
) -> Callable[..., JudgeVerdict]:
    """构造单类 evaluator（改写自 CASE-openevals使用 create_llm_as_judge 调用面）。

    返回的 evaluator 以关键字参数接收 ``inputs`` / ``outputs`` / ``evidence`` /
    ``reference`` 四槽位（对齐改写来源 8-hallucination.py 的
    evaluator(context=..., inputs=..., outputs=..., reference_outputs=...)），
    渲染模板 → 单次 judge 调用 → 结构化判定。

    cassette_path 非空时 judge 调用经 ``chat_with_cassette``：默认严格回放
    （离线零调用），record=True 显式切录制（一次性在线真实 DashScope）。
    录制与回放共用本函数，保证两侧请求指纹严格一致。
    """
    if feedback_key not in PROMPT_TEMPLATES:
        raise JudgeError(f"未知 feedback_key：{feedback_key}（合法：{sorted(LEGAL_FEEDBACK_KEYS)}）")
    _check_config(cfg)
    template = PROMPT_TEMPLATES[feedback_key]

    def evaluator(
        *,
        inputs: str,
        outputs: str,
        evidence: str = "",
        reference: str = "",
    ) -> JudgeVerdict:
        slots = {
            "inputs": inputs,
            "outputs": outputs,
            "evidence": evidence,
            "reference": reference,
        }
        messages: Sequence[dict[str, Any]] = [
            {"role": "user", "content": _render(template, slots)}
        ]
        # 考官调用形态（对齐改写来源 temperature=0）：模型名走 config 锁定，
        # 录制与回放共用同一份 kwargs，指纹两侧严格一致。
        call_kwargs: dict[str, Any] = {
            "model": cfg.eval.judge_model,
            "temperature": 0,
        }
        if cassette_path is not None:
            response = chat_with_cassette(
                judge_client,
                cassette_path,
                messages,
                record=record,
                **call_kwargs,
            )
        else:
            response = judge_client.chat(messages, **call_kwargs)
        return _parse_verdict(feedback_key, response.content, cfg)

    return evaluator


def dumps_slot(value: Any) -> str:
    """槽位值序列化：结构化证据/标签统一 JSON 文本进模板（确定性、可复现）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def aggregate(
    verdicts: Sequence[JudgeVerdict],
    *,
    pass_threshold: float,
) -> dict[str, Any]:
    """L2 三项指标聚合（spec v2：groundedness / 幻觉率 / 建议相关性）。

    幻觉率 = hallucination 判定 score < pass_threshold 的条目占比（score 二元
    0/1，等价于 hallucinated=true 占比）；另报 groundedness / relevance 的
    平均分与通过率，供 README 基线（票 04）对账。
    """
    _check_keys = {v.feedback_key for v in verdicts}
    if not _check_keys <= LEGAL_FEEDBACK_KEYS:
        raise JudgeError(f"aggregate 收到未知判定键：{_check_keys - LEGAL_FEEDBACK_KEYS}")
    by_key: dict[str, list[float]] = {k: [] for k in LEGAL_FEEDBACK_KEYS}
    for v in verdicts:
        by_key[v.feedback_key].append(v.score)

    def _mean(key: str) -> float | None:
        xs = by_key[key]
        return None if not xs else sum(xs) / len(xs)

    def _pass_rate(key: str) -> float | None:
        xs = by_key[key]
        return None if not xs else sum(1 for s in xs if s >= pass_threshold) / len(xs)

    hallucination_scores = by_key[FEEDBACK_HALLUCINATION]
    hallucination_rate = (
        None
        if not hallucination_scores
        else sum(1 for s in hallucination_scores if s < pass_threshold) / len(hallucination_scores)
    )
    return {
        "judge_model": verdicts[0].judge_model if verdicts else None,
        "prompt_versions": {v.feedback_key: v.prompt_version for v in verdicts},
        "groundedness_mean": _mean(FEEDBACK_GROUNDEDNESS),
        "groundedness_pass_rate": _pass_rate(FEEDBACK_GROUNDEDNESS),
        "relevance_mean": _mean(FEEDBACK_RELEVANCE),
        "relevance_pass_rate": _pass_rate(FEEDBACK_RELEVANCE),
        "hallucination_rate": hallucination_rate,
        "pass_threshold": pass_threshold,
    }
