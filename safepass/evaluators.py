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

import difflib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import json_repair

from safepass import config_loader, contracts
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
   - 安抚类、流程性话术；
   - 回答中 extracted 字段（区域/人群/时间）：继承自【用户查询】本身，不是事实声明；
   - 回答中的画像时间提示与个性化建议（来自用户画像，不是数据结论）；
   - 图表细分数据（top5 类型/昼夜分布）：由【证据】中的聚合统计派生，证据给出聚合统计即视为有依据；
4. 建议正文（suggestions 数组）按 suggestions_source 字段判定来源：
   - suggestions_source 为 template，或回答无该字段：建议是系统确定性模板文本，永不参与 groundedness 判定；
   - suggestions_source 为 skill：建议由 AI 生成，参与判定——其中的事实性声明（数字、案件类型与数量、昼夜分布、犯罪率、地点事实、社区机构与事件信息）必须被【证据】支持或可由【证据】推出（证据未逐字给出但可推出视为有依据）；与【证据】矛盾或凭空声称的声明，每条显著降分；纯动作建议（只讲怎么做、不含量化或事实主张）不扣分；
   - suggestion_grounds 的引文（quote）是建议的依据标注（系统已逐字校验出自本地检索摘要），引文本身不是回答的事实声明，不参与判定；建议正文复述引文中的事实时，按上一条正常判定；
5. 【证据】标注为降级/越界（无数据支撑）时，回答中允许出现的内容（出现均不扣分、不构成矛盾）：
   - 警区号识别与「不在覆盖范围」说明（地址别名表与覆盖清单的产物，非犯罪数据）；
   - 替代信息中给出的覆盖内区域真实评级（见证据的 alternative_data 字段）；
   - 通用建议、紧急资源、覆盖区域重选邀请、免责声明。
   除此之外的犯罪数据性结论（评级/案件数/犯罪率/占比/趋势/路径）出现即矛盾；
6. score：1.0 = 全部事实性陈述有证据支持；0.0 = 存在与证据矛盾的声明；部分支持按比例扣分。

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
8. 建议正文（suggestions 数组）按 suggestions_source 字段判定来源：
   - suggestions_source 为 template，或回答无该字段：建议是系统确定性模板文本，永不构成幻觉；
   - suggestions_source 为 skill：建议由 AI 生成，参与判定——其与【证据】矛盾的事实性声明（数字、案件类型与数量、昼夜分布、犯罪率、地点事实、社区机构与事件信息）→ hallucinated=true；纯动作建议不构成幻觉；suggestion_grounds 引文本身不构成幻觉（建议正文复述引文中的事实时按正文正常判定）；
   - 安抚类、流程性话术永不构成幻觉；
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


# ---------------------------------------------------------------------------
# B2 确定性质量维度（issue 05 / B2）：actionability + specificity + 矛盾检测
# ---------------------------------------------------------------------------
# 灵感改写自 ragas / deepeval 的质量维度说明（execution-plan §1.2.8 B1/B2 行：
# faithfulness / 矛盾维度），不引入其运行时（票 05 禁止项）。全部确定性实现
# （规则特征 + 算术核对），LLM 零参与——宪法①⑤（能用规则/查表/算术判定的
# 不经 LLM）；矛盾核对按 P6 定案 2：数据事实 vs 建议文本的确定性比对，
# 不许 LLM 判定。词表与阈值只活 config eval.quality（红线 1）。
#
# 口径（README 质量基线表同源）：
# - actionability（能照做）= 命中动作词表的建议条目占比（动作词 = 祈使/行为
#   动词；模板路径通用建议同款命中，此维度是下限护栏，不是两路径区分维度）；
# - specificity（提到本区数据）= 建议条目与任一 grounds 引文共享 ≥
#   anchor_min_chars 字公共子串的条目占比（grounds 是 top-3 注入的池对齐
#   而非逐条对齐，故 union 匹配）。实现是纯最长公共子串、不校验子串类别
#   （地名/作案手法/通用措辞都计命中）——保守的「本区情报锚定覆盖下限」，
#   模板路径无 grounds 恒 0；
# - 矛盾（不与 charts 矛盾）= 句子内夜间时间词 + 方向断言 → 与 charts
#   day/night 计数算术核对：声称更安全需 night ≤ day、更危险需 night ≥ day；
#   更安全/更危险同句 = 歧义跳过；方向词前带否定词（如「并非夜间更危险」）
#   或整句为疑问 = 非断言跳过。命中即矛盾记录，逐条进工件。


def _longest_common_len(a: str, b: str) -> int:
    """两字符串最长公共子串长度（difflib，autojunk=False 防长文本误判）。"""
    match = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)
    )
    return match.size


def actionability_scores(
    suggestions: Sequence[str], action_verbs: Sequence[str]
) -> tuple[bool, ...]:
    """能照做：每条建议是否命中 ≥1 个动作词（词表 = config eval.quality.action_verbs）。"""
    return tuple(any(verb in text for verb in action_verbs) for text in suggestions)


def specificity_scores(
    suggestions: Sequence[str],
    ground_quotes: Sequence[str],
    anchor_min_chars: int,
) -> tuple[bool, ...]:
    """提到本区数据：建议与任一 grounds 引文共享 ≥ anchor_min_chars 字的情报锚点。

    grounds 是检索 top-3 的池注入（A2），与建议条目不是逐条对齐——
    union 匹配：条目命中任一引文的锚点即视为本区数据锚定。无 grounds
    （模板路径 / 检索降级）恒 False。
    """
    scores: list[bool] = []
    for text in suggestions:
        anchored = any(
            quote and _longest_common_len(text, quote) >= anchor_min_chars
            for quote in ground_quotes
        )
        scores.append(anchored)
    return tuple(scores)


def _negated(segment: str, word: str, negation_words: Sequence[str]) -> bool:
    """方向词前 4 字窗口内出现否定词 = 否定表达（「并非夜间更危险」非断言）。"""
    pos = segment.find(word)
    return pos >= 0 and any(n in segment[max(0, pos - 4) : pos] for n in negation_words)


def detect_contradictions(
    suggestions: Sequence[str],
    day: int,
    night: int,
    *,
    quality_cfg: config_loader.EvalQualityConfig,
) -> list[str]:
    """矛盾检测（确定性算术核对）：夜间方向断言 vs charts 昼夜计数。

    句子为核对单元（方向断言只在其所在句内成立）：声称「夜间更安全」但
    night > day、声称「夜间更危险」但 night < day → 矛盾记录（含违规句子
    与两侧数字）。豁免：更安全/更危险同句 = 歧义跳过；方向词前 4 字窗口内
    带否定词（「并非夜间更危险」）或整句为疑问 = 非断言跳过。词表（夜间
    时间词/更安全/更危险/否定词）全部来自 config eval.quality。
    """
    contradictions: list[str] = []
    for i, text in enumerate(suggestions):
        # 问号不进分隔符：疑问句保留问号以在下方整句豁免（问号入句不影响词匹配）
        for sentence in re.split(r"[。；！!\n]", text):
            if "？" in sentence or "?" in sentence:
                continue  # 疑问句不是断言
            has_night = any(w in sentence for w in quality_cfg.night_time_words)
            has_safer = has_night and any(
                w in sentence and not _negated(sentence, w, quality_cfg.negation_words)
                for w in quality_cfg.safer_words
            )
            has_danger = has_night and any(
                w in sentence and not _negated(sentence, w, quality_cfg.negation_words)
                for w in quality_cfg.danger_words
            )
            if has_safer == has_danger:
                continue  # 无方向断言，或更安全/更危险同句（歧义跳过）
            if has_safer and night > day:
                contradictions.append(
                    f"建议[{i}]声称夜间更安全，但 charts 夜间 {night} 起 > 日间 {day} 起：{sentence}"
                )
            elif has_danger and night < day:
                contradictions.append(
                    f"建议[{i}]声称夜间更危险，但 charts 夜间 {night} 起 < 日间 {day} 起：{sentence}"
                )
    return contradictions


def quality_dimensions(
    result: Any,
    evidence: dict[str, Any],
    cfg: config_loader.AppConfig,
) -> dict[str, Any] | None:
    """B2 三维逐条计算（issue 05）：只有 safety 形态的覆盖内安全查询有质量面。

    evidence = l2_runner.build_evidence 的产物；非 safety 形态（对比/降级/
    越界）返回 None（质量维度只评估建议质量，不问契约形态）。
    """
    if not isinstance(result, contracts.SafetyQueryResult):
        return None
    if evidence.get("kind") != "safety":
        return None
    data = evidence["data"]
    quality_cfg = cfg.eval.quality
    suggestions = result.suggestions
    n = len(suggestions)
    action_hits = actionability_scores(suggestions, quality_cfg.action_verbs)
    specific_hits = specificity_scores(
        suggestions,
        [g.quote for g in result.suggestion_grounds],
        quality_cfg.anchor_min_chars,
    )
    contradictions = detect_contradictions(
        suggestions,
        data["day_night"]["day"],
        data["day_night"]["night"],
        quality_cfg=quality_cfg,
    )
    return {
        "actionability": (sum(action_hits) / n) if n else 0.0,
        "specificity": (sum(specific_hits) / n) if n else 0.0,
        "contradictions": contradictions,
        "n_suggestions": n,
    }
