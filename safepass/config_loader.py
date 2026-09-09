"""集中配置加载（spec D4）。

唯一允许读取 config/app.yaml 的入口；向全库提供阈值系数、样本量档位、
覆盖警区清单、全市均值、重试上界等配置对象。

红线（RALPH.md）：阈值系数、样本量档位、警区号字面量只允许存在于
config/app.yaml，本模块只搬运与校验，不内置任何默认值兜底业务数字。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from safepass import contracts

# 项目根：safepass/config_loader.py -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# config/app.yaml 相对项目根
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"


class ConfigError(RuntimeError):
    """集中配置缺失、损坏或违反不变量时抛出（明确失败，不静默兜底）。"""


@dataclass(frozen=True)
class OneLinerHookSpec:
    """one_liner 数据钩子（issue 18 / A3，ADR-0003 定案）：判定阈值 + 填空话术。

    id 是装配分支的判别键（loader 校验其属于 KNOWN_HOOK_IDS，未知 id =
    配置损坏明确失败）；text 是拼进 one_liner 的固定人话（可能含 {type}/
    {ratio} 占位，由装配层按数据填充）；night_min_ratio/top_type_min_share
    是各自钩子的触发阈值（city_relative 复用 rating.thresholds 的评级带，
    不设自有阈值）。一切字面量只活在 config/app.yaml。
    """

    id: str
    text: str
    night_min_ratio: float | None = None
    top_type_min_share: float | None = None


@dataclass(frozen=True)
class OneLinerConfig:
    """one_liner 确定性钩子词典（issue 18 / A3）。

    hooks：按装配优先级声明的钩子列表（首个命中者胜，30 字上限只放一个）；
    type_names：犯罪类型代码 → 中文名展示词表（未收录代码不产类型钩子）。
    """

    hooks: tuple[OneLinerHookSpec, ...]
    type_names: dict[str, str]


@dataclass(frozen=True)
class RatingThresholds:
    """相对阈值：per-100k 犯罪率 / 全市均值（spec D4）。"""

    green_max_ratio: float
    red_min_ratio: float


@dataclass(frozen=True)
class SampleSizeTier:
    """样本量档位（评级与可信度同源，同一 sample_size 输入；spec D4）。

    rating 非空表示该档强制评级（如 <10 强制 ⚪ insufficient_data）；
    confidence 为可信度档（LOW/MODERATE/HIGH）或 None。
    """

    min: int
    max: int | None
    rating: str | None
    confidence: str | None


@dataclass(frozen=True)
class RatingRationaleConfig:
    """评级依据人话模板（C1a）：按灯色填空，字面量只活在配置。

    templates 键必须覆盖合法评级枚举；绿/黄/红含 {ratio}/{sample_tier}；
    ⚪ 含 {n}、禁止 {ratio}。sample_tier_labels 把可信度档映射为对外中文。
    """

    templates: dict[str, str]
    sample_tier_labels: dict[str, str]


@dataclass(frozen=True)
class AddressingConfig:
    """地址解析最小版（issue 05 / D12）：中文别名 → 警区号列表映射。

    别名命中返回的是警区列表（中城 → [14, 18]）；覆盖判定一律
    对照 covered_precincts，本模块不内置任何警区号。
    """

    aliases: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class DegradedConfig:
    """降级分支配置（issue 05 / T3）：意图静态标记 + 话术模板。

    模板里的 {area}/{precincts}/{covered} 占位由降级装配层动态填充；
    模板禁止出现路径级词汇（测试集有黑名单断言）。
    """

    path_pair_markers: tuple[str, ...]
    path_markers: tuple[str, ...]
    trend_markers: tuple[str, ...]
    explanation_templates: dict[str, str]
    reselection_invitation: str
    general_suggestions: tuple[str, ...]
    insufficient_data_message: str


@dataclass(frozen=True)
class SuggestionsConfig:
    """建议配置（issue 06 / T4）：空话黑名单 + 覆盖区内安全查询的通用建议。

    结构边界（3-5 条）由装配层业务校验执行；具体性/温暖度是人工抽查项。
    skill_enabled（issue 16 / A1）：建议 Skill 主路径开关。false = 强制模板
    路径——B1 两路径同台实测对照用同一开关跑双侧（对照不引入新接缝）。
    rating_disclaimer_rewrite_blacklist（issue 17 / A2）：评级/免责改写词表
    ——Skill 产出（建议正文 + grounds 引文）命中即业务校验失败（间接注入
    防线骨架，与 N1 交叉；只作用于 Skill 路径）。
    """

    empty_talk_blacklist: tuple[str, ...]
    safety_general: tuple[str, ...]
    skill_enabled: bool = True
    rating_disclaimer_rewrite_blacklist: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimeBucketSpec:
    """单个时段桶：含 start_hour 不含 end_hour；可跨日（start > end）。"""

    label: str
    start_hour: int
    end_hour: int


@dataclass(frozen=True)
class TimeBucketsConfig:
    """四时段桶（C2）：边界与样本门槛只活配置。"""

    buckets: tuple[TimeBucketSpec, ...]
    min_sample: int
    unknown_message: str
    hour12_add_12_markers: tuple[str, ...]
    midnight_12_markers: tuple[str, ...]


@dataclass(frozen=True)
class EmergencyConfig:
    """紧急检测与静态紧急组装配置（issue 07 / T5，spec D7）。

    keywords：第一层关键词静态表（命中即进无 LLM 静态分支，优先于一切 LLM 调用）；
    call_911_prompt / chinese_interpreter_phrase / info_checklist / comfort_message：
    EmergencyResult 的静态话术模板（经装配层业务校验断言非空）；
    proximity_blacklist：暗示定位的词（系统无定位能力，话术与清单一律禁止出现）。
    """

    keywords: tuple[str, ...]
    call_911_prompt: str
    chinese_interpreter_phrase: str
    info_checklist: tuple[str, ...]
    comfort_message: str
    proximity_blacklist: tuple[str, ...]


@dataclass(frozen=True)
class FollowUpConfig:
    """追问细分类标记（issue 08 / T6，spec D6 / F8）。

    FC 只把查询路由到 follow_up；对比追问/细节追问/换地点换话题重置
    由 followup.classify 用本表确定性判定（零 LLM，D12 同款后置思路）。
    """

    comparison_markers: tuple[str, ...]
    time_markers: tuple[str, ...]
    crowd_markers: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonConfig:
    """双区对比的决策辅助话术模板（issue 08 / T6，F3-4 结构层）。

    {area} 由装配层按两侧真实聚合数据填充；话术品味是人工抽查项。
    """

    decision_aid_rating: str
    decision_aid_rating_tie: str
    decision_aid_night: str
    decision_aid_night_tie: str
    decision_aid_trend_note: str


@dataclass(frozen=True)
class GuardrailsConfig:
    """负例防线静态表（issue 09 / T7，NEG-003/004/006；零 LLM，管线内确定性执行）。

    bias_*：种族偏见诱导 → 拒绝并转向结构性解释（数据决定安全，与族裔无关）；
    weapon_*：武器防身建议 → 拒绝并引导合法途径（alternatives 不得含器械词）；
    panic_blacklist：恐慌性夸大词汇黑名单（安全查询装配自检命中即明确失败）。
    """

    bias_markers: tuple[str, ...]
    bias_message: str
    bias_alternatives: tuple[str, ...]
    weapon_markers: tuple[str, ...]
    weapon_message: str
    weapon_alternatives: tuple[str, ...]
    panic_blacklist: tuple[str, ...]


@dataclass(frozen=True)
class ProfileConfig:
    """会话画像的合法作用域配置（issue 09 / T7，spec D5 / ADR-0002）。

    notice：画像隐私透明声明（AC-023 结构断言，"会话级、关闭即删除"语义）；
    crowd_suggestions：人群标签 → 个性化建议（命中时排序前置；评级零接触）；
    late_night_markers/late_night_note：晚归画像的时间风险提示前置。
    """

    notice: str
    crowd_suggestions: dict[str, str]
    late_night_markers: tuple[str, ...]
    late_night_note: str


@dataclass(frozen=True)
class IntelConfig:
    """情报 Agent 混合检索配置（issue 10 / T8，spec D2 / CONTEXT.md 混合检索）。

    unverified_label：知识库未记载事实的统一输出标注（F7-3 诚实路径），
    如某警区是否有中文警员——输出该标注，绝不编造。检索层参数
    （RRF 常数、top-3）是 spec 固定结构，单一事实源在 scripts.build_index
    与 safepass.intel_agent 的模块常量，不进配置。
    """

    unverified_label: str


@dataclass(frozen=True)
class DataSourceConfig:
    """真实数据 adapter 配置（issue 05 / M2，spec v2）：Socrata 单向管道。

    socrata_base_url / nypd_dataset_id：来源接入点（数据集 ID 以门户页面实际
    URL 为准，resource-manifest §D 核验规则）；output_dir：入库产物目录；
    recorded_response：Socrata 响应录制 fixture（测试离线回放，零真实调用）；
    request_timeout_seconds / page_limit：脚本级请求参数（page_limit 上限
    为 Socrata 单次请求的平台约束，单一事实源 = page_limit_max）。
    sources / time_range：覆盖内契约与免责页的来源、时间范围（F1），
    字面量只活在配置，两边必须同读。
    """

    socrata_base_url: str
    nypd_dataset_id: str
    output_dir: str
    recorded_response: str
    runtime_dataset_path: str
    request_timeout_seconds: int
    page_limit: int
    page_limit_max: int
    sources: tuple[str, ...]
    time_range: str


@dataclass(frozen=True)
class CostControlConfig:
    """成本三件套配置（票 06 / M2）：限流窗口 + 成本估算 + 降级话术。

    rate_limit：请求级限流滑动窗口（每包装器实例一个窗口；生产单实例接线，
    窗口/阈值只活在配置）；
    estimation：无 token 计数时的确定性成本近似（chars_per_token 系数 +
    各模型 USD/1K tokens 估算单价；default 条目兜底未列出模型）；
    degraded_notice：熔断降级时响应必须携带的明示话术（不静默）；
    report_path：成本 JSONL 上报落盘路径。日预算本身不在此处——
    单一事实源是 token-budget.json 的 daily_cost_budget_usd。
    """

    rate_window_seconds: float
    rate_max_requests: int
    chars_per_token: int
    prices_per_1k_tokens: dict[str, dict[str, float]]
    degraded_notice: str
    report_path: str


@dataclass(frozen=True)
class LLMConfig:
    """生产模型接线配置（票 12 / M4）：OpenAI 兼容端点客户端的请求超时。

    接入点/模型名/密钥不进配置——生产经 env（LLM_API_KEY/LLM_BASE_URL/
    LLM_MODEL）注入（spec v2「生产模型接线」）；客户端构造的唯一注入点在
    safepass/llm_wiring.py，产出必经 BudgetFusedClient 包装（票 06）。
    """

    request_timeout_seconds: float


@dataclass(frozen=True)
class SyntheticUserConfig:
    """合成用户预检配置（票 10 / M3，spec v2「合成用户」节）。

    dev-only 工具：LLM 扮演目标用户 persona 预戳访谈脚本。model/base_url 锁定
    dev 路由（DashScope Qwen）；interview_script 是被预戳的访谈脚本草稿路径；
    output_path 是预检报告落盘路径；dev_reference_label 是"永不冒充真人证据"
    标注的单一事实源（报告头 + 每条回答都盖此章）；reply_max_chars 是单条
    回答的字数结构校验上界。重试上界不在此处——单一事实源是
    output_pipeline.max_retries。
    """

    model: str
    base_url: str
    interview_script: str
    output_path: str
    dev_reference_label: str
    reply_max_chars: int


@dataclass(frozen=True)
class EvalConfig:
    """L2 LLM-as-judge 评估套件配置（issue 03 / M1，spec v2「L2」节）。

    judge_model/base_url：考官模型与接入点（dev = DashScope Qwen，考官考生同源）；
    cassette：主路径（Skill 建议）judge 调用录制回放文件（录制一次性在线，
    回放离线零调用）；
    cassette_template：对照路径（确定性模板）judge 录制回放文件（B1 两路径对照）；
    cassette_skill：Skill 路径管线 LLM 调用（三维提取 + 建议生成）录制回放文件
    （B1：主指标咬合 Skill 输出，回放同一事实源）；
    pass_threshold：判定通过分数下界（三项 L2 指标同口径）；
    skill_coverage_min：主指标分母护栏（B1）——Skill 覆盖子集中
    suggestions_source=skill 的条目数下界，低于即 Skill 系统性回归；
    quality：B2 确定性质量维度（actionability/specificity/矛盾检测）
    词表与回归门；
    prompt_versions：三类 evaluator 提示词模板版本锁定（键 = feedback_key，
    值 = 版本字符串；改模板必须升版本，否则 cassette 指纹校验直接拒放）。
    """

    judge_model: str
    base_url: str
    cassette: str
    cassette_template: str
    cassette_skill: str
    pass_threshold: float
    skill_coverage_min: int
    quality: EvalQualityConfig
    prompt_versions: dict[str, str]


@dataclass(frozen=True)
class EvalQualityConfig:
    """B2 确定性质量维度配置（issue 05，与 EvalConfig 平级的 eval.quality 节）。

    词表与阈值只活 config/app.yaml（红线 1）：action_verbs = actionability
    动作词表；anchor_min_chars = specificity 情报锚点最短公共子串长度；
    night_time_words/safer_words/danger_words = 矛盾检测的方向断言词表；
    min_actionability/min_specificity/max_contradiction_rate = 回归门。
    """

    action_verbs: tuple[str, ...]
    anchor_min_chars: int
    night_time_words: tuple[str, ...]
    safer_words: tuple[str, ...]
    danger_words: tuple[str, ...]
    negation_words: tuple[str, ...]
    min_actionability: float
    min_specificity: float
    max_contradiction_rate: float


@dataclass(frozen=True)
class AppConfig:
    thresholds: RatingThresholds
    sample_size_tiers: tuple[SampleSizeTier, ...]
    confidence_explanations: dict[str, str]
    rating_rationale: RatingRationaleConfig
    covered_precincts: frozenset[int]
    excluded_precincts: frozenset[int]
    precinct_populations: dict[int, int]
    city_mean_per_100k: float | None
    max_retries: int
    disclaimer: str
    # 免责页紧急资源提示行（验收审计 #5-④：号码字面量单一事实源在配置）
    disclaimer_emergency_line: str
    addressing: AddressingConfig
    degraded: DegradedConfig
    suggestions: SuggestionsConfig
    one_liner: OneLinerConfig
    time_buckets: TimeBucketsConfig
    emergency: EmergencyConfig
    followup: FollowUpConfig
    comparison: ComparisonConfig
    guardrails: GuardrailsConfig
    profile: ProfileConfig
    intel: IntelConfig
    data_source: DataSourceConfig
    cost_control: CostControlConfig
    synthetic_user: SyntheticUserConfig
    llm: LLMConfig
    eval: EvalConfig


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"配置缺少键 {where}.{key}（config/app.yaml）")
    return mapping[key]


def _parse_tiers(raw: list[dict[str, Any]]) -> tuple[SampleSizeTier, ...]:
    if not raw:
        raise ConfigError("rating.sample_size_tiers 不能为空")
    tiers = tuple(
        SampleSizeTier(
            min=int(_require(t, "min", "tier")),
            max=(None if t.get("max") is None else int(t["max"])),
            rating=t.get("rating"),
            confidence=t.get("confidence"),
        )
        for t in raw
    )
    # 不变量：按 min 升序、区间无缝衔接（评级可复算的前提）
    for prev, cur in zip(tiers, tiers[1:]):
        if cur.min <= prev.min:
            raise ConfigError("sample_size_tiers 必须按 min 升序")
        if prev.max is None or prev.max + 1 != cur.min:
            raise ConfigError("sample_size_tiers 区间必须无缝衔接（prev.max + 1 == cur.min）")
    if tiers[0].min != 0:
        raise ConfigError("sample_size_tiers 必须从 0 开始")
    return tiers


_REQUIRED_TIME_BUCKET_LABELS = frozenset({"清晨", "日间", "晚间", "深夜"})


def _parse_time_buckets(raw: dict[str, Any]) -> TimeBucketsConfig:
    """四时段桶：恰好四条、覆盖 24 小时、无重叠；门槛与话术只搬运校验。"""
    buckets_raw = _require(raw, "buckets", "time_buckets")
    if not isinstance(buckets_raw, list) or len(buckets_raw) != 4:
        raise ConfigError("time_buckets.buckets 必须恰好 4 条（清晨/日间/晚间/深夜）")
    buckets: list[TimeBucketSpec] = []
    for i, item in enumerate(buckets_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"time_buckets.buckets[{i}] 必须是映射")
        label = str(_require(item, "label", f"time_buckets.buckets[{i}]"))
        start = int(_require(item, "start_hour", f"time_buckets.buckets[{i}]"))
        end = int(_require(item, "end_hour", f"time_buckets.buckets[{i}]"))
        if not label.strip():
            raise ConfigError(f"time_buckets.buckets[{i}].label 不得为空")
        if start == end or not (0 <= start <= 23) or not (0 <= end <= 23):
            raise ConfigError(
                f"time_buckets.buckets[{i}] 的 start_hour/end_hour 须在 0-23 且不相等"
            )
        buckets.append(TimeBucketSpec(label=label, start_hour=start, end_hour=end))
    labels = [b.label for b in buckets]
    if set(labels) != _REQUIRED_TIME_BUCKET_LABELS:
        raise ConfigError("time_buckets.buckets 的 label 必须恰好是 清晨/日间/晚间/深夜")
    if len(set(labels)) != 4:
        raise ConfigError("time_buckets.buckets 的 label 不得重复")
    covered: list[str | None] = [None] * 24
    for bucket in buckets:
        hour = bucket.start_hour
        while True:
            if covered[hour] is not None:
                raise ConfigError(f"time_buckets 小时 {hour} 被多个桶覆盖")
            covered[hour] = bucket.label
            hour = (hour + 1) % 24
            if hour == bucket.end_hour:
                break
    if any(slot is None for slot in covered):
        raise ConfigError("time_buckets 必须覆盖 0-23 全部小时且无缺口")
    min_sample = int(_require(raw, "min_sample", "time_buckets"))
    if min_sample < 0:
        raise ConfigError("time_buckets.min_sample 不得为负")
    unknown_message = str(_require(raw, "unknown_message", "time_buckets"))
    if "{label}" not in unknown_message or "{n}" not in unknown_message:
        raise ConfigError("time_buckets.unknown_message 必须含 {label} 与 {n} 占位")
    add12 = tuple(str(m) for m in _require(raw, "hour12_add_12_markers", "time_buckets"))
    midnight = tuple(str(m) for m in _require(raw, "midnight_12_markers", "time_buckets"))
    if not add12 or any(not m.strip() for m in add12):
        raise ConfigError("time_buckets.hour12_add_12_markers 必须是非空词表")
    if not midnight or any(not m.strip() for m in midnight):
        raise ConfigError("time_buckets.midnight_12_markers 必须是非空词表")
    return TimeBucketsConfig(
        buckets=tuple(buckets),
        min_sample=min_sample,
        unknown_message=unknown_message,
        hour12_add_12_markers=add12,
        midnight_12_markers=midnight,
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取并校验集中配置。显式传 path 便于测试与多环境；否则用默认路径。"""
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"集中配置不存在：{cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"集中配置不是合法 YAML 映射：{cfg_path}")

    rating = _require(data, "rating", "root")
    thresholds_raw = _require(rating, "thresholds", "rating")
    thresholds = RatingThresholds(
        green_max_ratio=float(_require(thresholds_raw, "green_max_ratio", "rating.thresholds")),
        red_min_ratio=float(_require(thresholds_raw, "red_min_ratio", "rating.thresholds")),
    )
    if not (0 < thresholds.green_max_ratio < thresholds.red_min_ratio):
        raise ConfigError("阈值不变量 violated：需 0 < green_max_ratio < red_min_ratio")

    tiers = _parse_tiers(_require(rating, "sample_size_tiers", "rating"))

    explanations = _require(rating, "confidence_explanations", "rating")
    if not isinstance(explanations, dict) or not explanations:
        raise ConfigError("rating.confidence_explanations 必须是非空映射")

    rationale_raw = _require(rating, "rating_rationale", "rating")
    if not isinstance(rationale_raw, dict):
        raise ConfigError("rating.rating_rationale 必须是映射")
    templates_raw = _require(rationale_raw, "templates", "rating.rating_rationale")
    labels_raw = _require(rationale_raw, "sample_tier_labels", "rating.rating_rationale")
    if not isinstance(templates_raw, dict) or not isinstance(labels_raw, dict):
        raise ConfigError("rating.rating_rationale.templates / sample_tier_labels 必须是映射")
    templates = {str(k): str(v) for k, v in templates_raw.items()}
    sample_tier_labels = {str(k): str(v) for k, v in labels_raw.items()}
    expected_ratings = set(contracts.LEGAL_RATINGS)
    if set(templates) != expected_ratings:
        raise ConfigError(
            "rating.rating_rationale.templates 的键必须恰好等于合法评级枚举"
            f"（多配 {sorted(set(templates) - expected_ratings)}，"
            f"少配 {sorted(expected_ratings - set(templates))}）"
        )
    if any(not text.strip() for text in templates.values()):
        raise ConfigError("rating.rating_rationale.templates 的人话不得为空")
    for rating_key, text in templates.items():
        if rating_key == contracts.RATING_INSUFFICIENT:
            if "{ratio}" in text:
                raise ConfigError("insufficient_data 模板不得含 {ratio} 倍数占位")
            if "{n}" not in text:
                raise ConfigError("insufficient_data 模板必须含 {n} 命中数占位")
        else:
            if "{ratio}" not in text:
                raise ConfigError(f"{rating_key} 模板必须含 {{ratio}} 倍数占位")
            if "{sample_tier}" not in text:
                raise ConfigError(f"{rating_key} 模板必须含 {{sample_tier}} 样本档占位")
    expected_confidences = {t.confidence for t in tiers if t.confidence is not None}
    if set(sample_tier_labels) != expected_confidences:
        raise ConfigError(
            "rating.rating_rationale.sample_tier_labels 的键必须恰好等于样本量档的可信度"
        )
    if any(not label.strip() for label in sample_tier_labels.values()):
        raise ConfigError("rating.rating_rationale.sample_tier_labels 的中文不得为空")
    rating_rationale = RatingRationaleConfig(
        templates=templates, sample_tier_labels=sample_tier_labels
    )

    coverage = _require(data, "coverage", "root")
    covered = frozenset(int(p) for p in _require(coverage, "precincts", "coverage"))
    excluded = frozenset(int(p) for p in coverage.get("excluded_precincts", []))
    if not covered:
        raise ConfigError("coverage.precincts 不能为空")
    if covered & excluded:
        raise ConfigError("coverage.precincts 与 excluded_precincts 不得相交")

    # 警区常住人口估算（票 07 / M2）：真实数据无人口字段，运行时按警区号 join；
    # 键必须恰好覆盖 covered（多配少配都是配置损坏，明确失败不兜底）。
    populations_raw = _require(coverage, "precinct_populations", "coverage")
    if not isinstance(populations_raw, dict) or not populations_raw:
        raise ConfigError("coverage.precinct_populations 必须是非空映射（警区 → 人口估算）")
    precinct_populations = {int(p): int(v) for p, v in populations_raw.items()}
    if any(v <= 0 for v in precinct_populations.values()):
        raise ConfigError("coverage.precinct_populations 的人口估算必须为正")
    if set(precinct_populations) != set(covered):
        raise ConfigError(
            "coverage.precinct_populations 的键必须恰好等于 coverage.precincts"
            f"（多配 {sorted(set(precinct_populations) - set(covered))}，"
            f"少配 {sorted(set(covered) - set(precinct_populations))}）"
        )

    # 全市均值：T0 fixture 生成后填入；此前为 None（评级引擎在 T2 强制要求非空）
    city_mean_raw = data.get("city_mean_per_100k")
    city_mean = None if city_mean_raw is None else float(city_mean_raw)

    pipeline_cfg = _require(data, "output_pipeline", "root")
    max_retries = int(_require(pipeline_cfg, "max_retries", "output_pipeline"))
    if max_retries < 0:
        raise ConfigError("output_pipeline.max_retries 不得为负")

    addressing_raw = _require(data, "addressing", "root")
    aliases_raw = _require(addressing_raw, "aliases", "addressing")
    if not isinstance(aliases_raw, dict) or not aliases_raw:
        raise ConfigError("addressing.aliases 必须是非空映射（别名 → 警区列表）")
    aliases: dict[str, tuple[int, ...]] = {}
    for name, precincts in aliases_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("addressing.aliases 的键必须是非空字符串")
        if not isinstance(precincts, list) or not precincts:
            raise ConfigError(f"addressing.aliases[{name!r}] 必须是非空警区列表")
        aliases[name] = tuple(int(p) for p in precincts)

    degraded_raw = _require(data, "degraded", "root")
    explanation_raw = _require(degraded_raw, "explanation_templates", "degraded")
    if not isinstance(explanation_raw, dict):
        raise ConfigError("degraded.explanation_templates 必须是映射")
    degraded = DegradedConfig(
        path_pair_markers=tuple(
            str(m) for m in _require(degraded_raw, "path_pair_markers", "degraded")
        ),
        path_markers=tuple(str(m) for m in _require(degraded_raw, "path_markers", "degraded")),
        trend_markers=tuple(str(m) for m in _require(degraded_raw, "trend_markers", "degraded")),
        explanation_templates={str(k): str(v) for k, v in explanation_raw.items()},
        reselection_invitation=str(_require(degraded_raw, "reselection_invitation", "degraded")),
        general_suggestions=tuple(
            str(s) for s in _require(degraded_raw, "general_suggestions", "degraded")
        ),
        insufficient_data_message=str(_require(degraded_raw, "insufficient_data_message", "degraded")),
    )

    disclaimer = str(_require(data, "disclaimer", "root"))
    if not disclaimer.strip():
        raise ConfigError("disclaimer 不得为空")

    disclaimer_emergency_line = str(_require(data, "disclaimer_emergency_line", "root"))
    if not disclaimer_emergency_line.strip():
        raise ConfigError("disclaimer_emergency_line 不得为空")

    suggestions_raw = _require(data, "suggestions", "root")
    suggestions = SuggestionsConfig(
        empty_talk_blacklist=tuple(
            str(w) for w in _require(suggestions_raw, "empty_talk_blacklist", "suggestions")
        ),
        safety_general=tuple(
            str(s) for s in _require(suggestions_raw, "safety_general", "suggestions")
        ),
        rating_disclaimer_rewrite_blacklist=tuple(
            str(w)
            for w in _require(suggestions_raw, "rating_disclaimer_rewrite_blacklist", "suggestions")
        ),
        skill_enabled=bool(suggestions_raw.get("skill_enabled", True)),
    )
    if not suggestions.safety_general:
        raise ConfigError("suggestions.safety_general 不得为空")
    if not suggestions.empty_talk_blacklist:
        raise ConfigError("suggestions.empty_talk_blacklist 不得为空（AC-006 空话防线）")
    # 3-5 条结构边界不在此处重复定义：单一事实源在 output_pipeline 的
    # 业务校验器（装配时显式失败），避免两处常量漂移。

    followup_raw = _require(data, "followup", "root")
    followup = FollowUpConfig(
        comparison_markers=tuple(
            str(m) for m in _require(followup_raw, "comparison_markers", "followup")
        ),
        time_markers=tuple(str(m) for m in _require(followup_raw, "time_markers", "followup")),
        crowd_markers=tuple(str(m) for m in _require(followup_raw, "crowd_markers", "followup")),
    )
    for field_name, markers in (
        ("comparison_markers", followup.comparison_markers),
        ("time_markers", followup.time_markers),
        ("crowd_markers", followup.crowd_markers),
    ):
        if not markers or any(not m.strip() for m in markers):
            raise ConfigError(f"followup.{field_name} 必须是非空标记表（追问确定性细分）")

    comparison_raw = _require(data, "comparison", "root")
    comparison = ComparisonConfig(
        decision_aid_rating=str(_require(comparison_raw, "decision_aid_rating", "comparison")),
        decision_aid_rating_tie=str(
            _require(comparison_raw, "decision_aid_rating_tie", "comparison")
        ),
        decision_aid_night=str(_require(comparison_raw, "decision_aid_night", "comparison")),
        decision_aid_night_tie=str(
            _require(comparison_raw, "decision_aid_night_tie", "comparison")
        ),
        decision_aid_trend_note=str(
            _require(comparison_raw, "decision_aid_trend_note", "comparison")
        ),
    )
    for field_name, template in (
        ("decision_aid_rating", comparison.decision_aid_rating),
        ("decision_aid_rating_tie", comparison.decision_aid_rating_tie),
        ("decision_aid_night", comparison.decision_aid_night),
        ("decision_aid_night_tie", comparison.decision_aid_night_tie),
        ("decision_aid_trend_note", comparison.decision_aid_trend_note),
    ):
        if not template.strip():
            raise ConfigError(f"comparison.{field_name} 不得为空（F3-4 决策辅助结构断言）")

    emergency_raw = _require(data, "emergency", "root")
    keywords = tuple(str(k) for k in _require(emergency_raw, "keywords", "emergency"))
    if not keywords or any(not k.strip() for k in keywords):
        raise ConfigError("emergency.keywords 必须是非空关键词表（第一层静态检测）")
    call_911_prompt = str(_require(emergency_raw, "call_911_prompt", "emergency"))
    chinese_interpreter_phrase = str(
        _require(emergency_raw, "chinese_interpreter_phrase", "emergency")
    )
    info_checklist = tuple(
        str(i) for i in _require(emergency_raw, "info_checklist", "emergency")
    )
    comfort_message = str(_require(emergency_raw, "comfort_message", "emergency"))
    for field_name, field_value in (
        ("call_911_prompt", call_911_prompt),
        ("chinese_interpreter_phrase", chinese_interpreter_phrase),
        ("comfort_message", comfort_message),
    ):
        if not field_value.strip():
            raise ConfigError(f"emergency.{field_name} 不得为空（AC-014 字段断言）")
    if not info_checklist or any(not i.strip() for i in info_checklist):
        raise ConfigError("emergency.info_checklist 必须是非空信息准备清单（AC-014）")
    proximity_blacklist = tuple(
        str(w) for w in _require(emergency_raw, "proximity_blacklist", "emergency")
    )
    if not proximity_blacklist:
        raise ConfigError("emergency.proximity_blacklist 不得为空（无定位词防线）")
    emergency = EmergencyConfig(
        keywords=keywords,
        call_911_prompt=call_911_prompt,
        chinese_interpreter_phrase=chinese_interpreter_phrase,
        info_checklist=info_checklist,
        comfort_message=comfort_message,
        proximity_blacklist=proximity_blacklist,
    )

    guardrails_raw = _require(data, "guardrails", "root")
    guardrails = GuardrailsConfig(
        bias_markers=tuple(str(m) for m in _require(guardrails_raw, "bias_markers", "guardrails")),
        bias_message=str(_require(guardrails_raw, "bias_message", "guardrails")),
        bias_alternatives=tuple(
            str(a) for a in _require(guardrails_raw, "bias_alternatives", "guardrails")
        ),
        weapon_markers=tuple(
            str(m) for m in _require(guardrails_raw, "weapon_markers", "guardrails")
        ),
        weapon_message=str(_require(guardrails_raw, "weapon_message", "guardrails")),
        weapon_alternatives=tuple(
            str(a) for a in _require(guardrails_raw, "weapon_alternatives", "guardrails")
        ),
        panic_blacklist=tuple(
            str(w) for w in _require(guardrails_raw, "panic_blacklist", "guardrails")
        ),
    )
    for field_name, values in (
        ("bias_markers", guardrails.bias_markers),
        ("weapon_markers", guardrails.weapon_markers),
        ("panic_blacklist", guardrails.panic_blacklist),
    ):
        if not values or any(not v.strip() for v in values):
            raise ConfigError(f"guardrails.{field_name} 必须是非空静态表（负例防线确定性判定）")
    for field_name, value in (
        ("bias_message", guardrails.bias_message),
        ("weapon_message", guardrails.weapon_message),
    ):
        if not value.strip():
            raise ConfigError(f"guardrails.{field_name} 不得为空（拒绝话术单一事实源）")

    profile_raw = _require(data, "profile", "root")
    notice = str(_require(profile_raw, "notice", "profile"))
    if not notice.strip():
        raise ConfigError("profile.notice 不得为空（AC-023 画像声明结构断言）")
    crowd_raw = profile_raw.get("crowd_suggestions", {})
    if not isinstance(crowd_raw, dict):
        raise ConfigError("profile.crowd_suggestions 必须是映射（人群标签 → 建议）")
    profile = ProfileConfig(
        notice=notice,
        crowd_suggestions={str(k): str(v) for k, v in crowd_raw.items()},
        late_night_markers=tuple(
            str(m) for m in profile_raw.get("late_night_markers", ())
        ),
        late_night_note=str(profile_raw.get("late_night_note", "")),
    )
    if profile.late_night_markers and not profile.late_night_note.strip():
        raise ConfigError("profile.late_night_note 不得为空（晚归时间提示前置）")

    intel_raw = _require(data, "intel", "root")
    intel = IntelConfig(
        unverified_label=str(_require(intel_raw, "unverified_label", "intel"))
    )
    if not intel.unverified_label.strip():
        raise ConfigError("intel.unverified_label 不得为空（F7-3 未记载项统一标注）")

    data_source_raw = _require(data, "data_source", "root")
    sources_raw = _require(data_source_raw, "sources", "data_source")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("data_source.sources 必须是非空列表（F1 免责与契约同源）")
    sources = tuple(str(s).strip() for s in sources_raw)
    if any(not s for s in sources):
        raise ConfigError("data_source.sources 条目不得为空")
    time_range = str(_require(data_source_raw, "time_range", "data_source")).strip()
    if not time_range:
        raise ConfigError("data_source.time_range 不得为空（F1 免责与契约同源）")
    data_source = DataSourceConfig(
        socrata_base_url=str(_require(data_source_raw, "socrata_base_url", "data_source")),
        nypd_dataset_id=str(_require(data_source_raw, "nypd_dataset_id", "data_source")),
        output_dir=str(_require(data_source_raw, "output_dir", "data_source")),
        recorded_response=str(_require(data_source_raw, "recorded_response", "data_source")),
        runtime_dataset_path=str(_require(data_source_raw, "runtime_dataset_path", "data_source")),
        request_timeout_seconds=int(
            _require(data_source_raw, "request_timeout_seconds", "data_source")
        ),
        page_limit=int(_require(data_source_raw, "page_limit", "data_source")),
        page_limit_max=int(_require(data_source_raw, "page_limit_max", "data_source")),
        sources=sources,
        time_range=time_range,
    )
    for field_name in (
        "socrata_base_url",
        "nypd_dataset_id",
        "output_dir",
        "recorded_response",
        "runtime_dataset_path",
    ):
        if not getattr(data_source, field_name).strip():
            raise ConfigError(f"data_source.{field_name} 不得为空（adapter 来源/落盘路径）")
    if data_source.request_timeout_seconds <= 0:
        raise ConfigError("data_source.request_timeout_seconds 必须为正")
    if not (0 < data_source.page_limit <= data_source.page_limit_max):
        raise ConfigError("data_source.page_limit 必须在 (0, page_limit_max]（Socrata 平台硬上限）")

    cost_raw = _require(data, "cost_control", "root")
    rate_raw = _require(cost_raw, "rate_limit", "cost_control")
    estimation_raw = _require(cost_raw, "estimation", "cost_control")
    prices_raw = _require(estimation_raw, "prices_per_1k_tokens", "cost_control.estimation")
    if not isinstance(prices_raw, dict) or not prices_raw:
        raise ConfigError("cost_control.estimation.prices_per_1k_tokens 必须是非空映射")
    prices: dict[str, dict[str, float]] = {}
    for model_name, price in prices_raw.items():
        if not isinstance(price, dict):
            raise ConfigError(f"cost_control 单价条目必须是映射：{model_name!r}")
        entry = {str(k): float(v) for k, v in price.items()}
        for side in ("input", "output"):
            if side not in entry:
                raise ConfigError(
                    f"cost_control 单价条目缺少 {side!r} 键：{model_name!r}（缺键=免费，禁止）"
                )
        prices[str(model_name)] = entry
    if any(p < 0 for entry in prices.values() for p in entry.values()):
        raise ConfigError("cost_control 估算单价不得为负")
    if "default" not in prices:
        raise ConfigError("cost_control.estimation.prices_per_1k_tokens 必须含 default 兜底条目")
    cost_control = CostControlConfig(
        rate_window_seconds=float(_require(rate_raw, "window_seconds", "cost_control.rate_limit")),
        rate_max_requests=int(_require(rate_raw, "max_requests", "cost_control.rate_limit")),
        chars_per_token=int(_require(estimation_raw, "chars_per_token", "cost_control.estimation")),
        prices_per_1k_tokens=prices,
        degraded_notice=str(_require(cost_raw, "degraded_notice", "cost_control")),
        report_path=str(_require(cost_raw, "report_path", "cost_control")),
    )
    if cost_control.rate_window_seconds <= 0:
        raise ConfigError("cost_control.rate_limit.window_seconds 必须为正")
    if cost_control.rate_max_requests <= 0:
        raise ConfigError("cost_control.rate_limit.max_requests 必须为正")
    if cost_control.chars_per_token <= 0:
        raise ConfigError("cost_control.estimation.chars_per_token 必须为正")
    if not cost_control.degraded_notice.strip():
        raise ConfigError("cost_control.degraded_notice 不得为空（降级明示，不静默）")
    if not cost_control.report_path.strip():
        raise ConfigError("cost_control.report_path 不得为空（成本 JSONL 上报落盘）")

    synthetic_raw = _require(data, "synthetic_user", "root")
    synthetic_user = SyntheticUserConfig(
        model=str(_require(synthetic_raw, "model", "synthetic_user")),
        base_url=str(_require(synthetic_raw, "base_url", "synthetic_user")),
        interview_script=str(_require(synthetic_raw, "interview_script", "synthetic_user")),
        output_path=str(_require(synthetic_raw, "output_path", "synthetic_user")),
        dev_reference_label=str(_require(synthetic_raw, "dev_reference_label", "synthetic_user")),
        reply_max_chars=int(_require(synthetic_raw, "reply_max_chars", "synthetic_user")),
    )
    for field_name in ("model", "base_url", "interview_script", "output_path"):
        if not getattr(synthetic_user, field_name).strip():
            raise ConfigError(f"synthetic_user.{field_name} 不得为空（合成用户预检）")
    if not synthetic_user.dev_reference_label.strip():
        raise ConfigError("synthetic_user.dev_reference_label 不得为空（永不冒充真人证据的标注）")
    if synthetic_user.reply_max_chars <= 0:
        raise ConfigError("synthetic_user.reply_max_chars 必须为正（回答字数结构校验上界）")

    llm_raw = _require(data, "llm", "root")
    llm = LLMConfig(request_timeout_seconds=float(_require(llm_raw, "request_timeout_seconds", "llm")))
    if llm.request_timeout_seconds <= 0:
        raise ConfigError("llm.request_timeout_seconds 必须为正")

    eval_raw = _require(data, "eval", "root")
    prompt_versions_raw = _require(eval_raw, "prompt_versions", "eval")
    if not isinstance(prompt_versions_raw, dict) or not prompt_versions_raw:
        raise ConfigError("eval.prompt_versions 必须是非空映射（feedback_key → 版本）")
    quality_raw = _require(eval_raw, "quality", "eval")
    eval_cfg = EvalConfig(
        judge_model=str(_require(eval_raw, "judge_model", "eval")),
        base_url=str(_require(eval_raw, "base_url", "eval")),
        cassette=str(_require(eval_raw, "cassette", "eval")),
        cassette_template=str(_require(eval_raw, "cassette_template", "eval")),
        cassette_skill=str(_require(eval_raw, "cassette_skill", "eval")),
        pass_threshold=float(_require(eval_raw, "pass_threshold", "eval")),
        skill_coverage_min=int(_require(eval_raw, "skill_coverage_min", "eval")),
        quality=EvalQualityConfig(
            action_verbs=tuple(
                str(v) for v in _require(quality_raw, "action_verbs", "eval.quality")
            ),
            anchor_min_chars=int(
                _require(quality_raw, "anchor_min_chars", "eval.quality")
            ),
            night_time_words=tuple(
                str(v) for v in _require(quality_raw, "night_time_words", "eval.quality")
            ),
            safer_words=tuple(
                str(v) for v in _require(quality_raw, "safer_words", "eval.quality")
            ),
            danger_words=tuple(
                str(v) for v in _require(quality_raw, "danger_words", "eval.quality")
            ),
            negation_words=tuple(
                str(v) for v in _require(quality_raw, "negation_words", "eval.quality")
            ),
            min_actionability=float(
                _require(quality_raw, "min_actionability", "eval.quality")
            ),
            min_specificity=float(
                _require(quality_raw, "min_specificity", "eval.quality")
            ),
            max_contradiction_rate=float(
                _require(quality_raw, "max_contradiction_rate", "eval.quality")
            ),
        ),
        prompt_versions={str(k): str(v) for k, v in prompt_versions_raw.items()},
    )
    if not eval_cfg.judge_model.strip():
        raise ConfigError("eval.judge_model 不得为空（L2 考官模型锁定）")
    if not eval_cfg.base_url.strip():
        raise ConfigError("eval.base_url 不得为空（judge 接入点）")
    if not eval_cfg.cassette.strip():
        raise ConfigError("eval.cassette 不得为空（judge 录制回放路径）")
    if not eval_cfg.cassette_template.strip():
        raise ConfigError("eval.cassette_template 不得为空（模板对照路径 judge 录制回放路径）")
    if not eval_cfg.cassette_skill.strip():
        raise ConfigError("eval.cassette_skill 不得为空（Skill 路径管线调用录制回放路径）")
    if eval_cfg.skill_coverage_min <= 0:
        raise ConfigError("eval.skill_coverage_min 必须为正（主指标分母护栏）")
    if not (0.0 < eval_cfg.pass_threshold <= 1.0):
        raise ConfigError("eval.pass_threshold 必须在 (0, 1] 区间")
    if any(not v.strip() for v in eval_cfg.prompt_versions.values()):
        raise ConfigError("eval.prompt_versions 的值（版本字符串）不得为空")
    quality = eval_cfg.quality
    if not quality.action_verbs or any(not w.strip() for w in quality.action_verbs):
        raise ConfigError("eval.quality.action_verbs 必须是非空词表（actionability 规则特征）")
    if quality.anchor_min_chars < 2:
        raise ConfigError("eval.quality.anchor_min_chars 必须 ≥ 2（情报锚点最短公共子串）")
    if not quality.night_time_words or not quality.safer_words or not quality.danger_words:
        raise ConfigError("eval.quality 矛盾检测三组方向词表必须非空")
    if not quality.negation_words:
        raise ConfigError("eval.quality.negation_words 必须非空（否定豁免词表）")
    if not (0.0 <= quality.min_actionability <= 1.0):
        raise ConfigError("eval.quality.min_actionability 必须在 [0, 1] 区间")
    if not (0.0 <= quality.min_specificity <= 1.0):
        raise ConfigError("eval.quality.min_specificity 必须在 [0, 1] 区间")
    if not (0.0 <= quality.max_contradiction_rate <= 1.0):
        raise ConfigError("eval.quality.max_contradiction_rate 必须在 [0, 1] 区间")

    # one_liner 钩子词典（issue 18 / A3）：词典与阈值只活在本节，loader 只搬运校验。
    # 装配分支的判别键（与 pipeline._one_liner_hook_text 的 id 分支一一对应）；
    # 未知 id = 配置损坏，明确失败不静默（新增钩子必须两端同步登记）。
    known_hook_ids = {"night_higher", "top_type_dominant", "city_relative"}
    one_liner_raw = _require(data, "one_liner", "root")
    hooks_raw = _require(one_liner_raw, "hooks", "one_liner")
    if not isinstance(hooks_raw, list) or not hooks_raw:
        raise ConfigError("one_liner.hooks 必须是非空列表（钩子词典，按装配优先级排序）")
    hook_specs: list[OneLinerHookSpec] = []
    for raw in hooks_raw:
        hook_id = str(_require(raw, "id", "one_liner.hooks"))
        if hook_id not in known_hook_ids:
            raise ConfigError(f"one_liner.hooks 含未知钩子 id {hook_id!r}（装配分支不认，配置损坏）")
        if hook_id in {h.id for h in hook_specs}:
            raise ConfigError(f"one_liner.hooks 的 id {hook_id!r} 重复")
        text = str(_require(raw, "text", f"one_liner.hooks[{hook_id}]"))
        if not text.strip():
            raise ConfigError(f"one_liner.hooks[{hook_id}].text 不得为空")
        spec = OneLinerHookSpec(
            id=hook_id,
            text=text,
            night_min_ratio=(
                None
                if raw.get("night_min_ratio") is None
                else float(raw["night_min_ratio"])
            ),
            top_type_min_share=(
                None
                if raw.get("top_type_min_share") is None
                else float(raw["top_type_min_share"])
            ),
        )
        if hook_id == "night_higher":
            if spec.night_min_ratio is None or spec.night_min_ratio < 1:
                raise ConfigError("night_higher 必须声明 night_min_ratio ≥ 1（夜间须显著高于日间才说“偏高”）")
            if "{" in spec.text:
                raise ConfigError("night_higher.text 是固定话术，不得含 {占位符}")
        elif hook_id == "top_type_dominant":
            if spec.top_type_min_share is None or not (0 < spec.top_type_min_share <= 1):
                raise ConfigError("top_type_dominant 必须声明 top_type_min_share ∈ (0, 1]")
            if "{type}" not in spec.text:
                raise ConfigError("top_type_dominant.text 必须含 {type} 占位（type_names 中文名）")
        else:  # city_relative：垫底数值锚点（charts 在场即发言），无自有阈值
            if "{ratio}" not in spec.text:
                raise ConfigError("city_relative.text 必须含 {ratio} 占位（全市均值倍数）")
        hook_specs.append(spec)
    type_names_raw = one_liner_raw.get("type_names", {})
    if not isinstance(type_names_raw, dict) or not type_names_raw:
        raise ConfigError("one_liner.type_names 必须是非空映射（犯罪类型代码 → 中文名）")
    type_names = {str(k): str(v) for k, v in type_names_raw.items()}
    if any(not name.strip() for name in type_names.values()):
        raise ConfigError("one_liner.type_names 的值（中文名）不得为空")
    # A3 收紧面：钩子词典话术与展示词表本身不得命中空话/恐慌黑名单
    # （装配层 NEG-006 兜底的是叙事输出；词典层先拦配置，双保险）。
    for word in (*guardrails.panic_blacklist, *suggestions.empty_talk_blacklist):
        for spec in hook_specs:
            if word in spec.text:
                raise ConfigError(f"one_liner 钩子 {spec.id} 的话术命中黑名单词 {word!r}（A3 收紧）")
        for code, name in type_names.items():
            if word in name:
                raise ConfigError(f"one_liner.type_names[{code!r}] 命中黑名单词 {word!r}（A3 收紧）")
    one_liner = OneLinerConfig(hooks=tuple(hook_specs), type_names=type_names)

    time_buckets_raw = _require(data, "time_buckets", "root")
    if not isinstance(time_buckets_raw, dict):
        raise ConfigError("time_buckets 必须是映射")
    time_buckets = _parse_time_buckets(time_buckets_raw)
    for word in (*guardrails.panic_blacklist, *suggestions.empty_talk_blacklist):
        if word in time_buckets.unknown_message:
            raise ConfigError(f"time_buckets.unknown_message 命中黑名单词 {word!r}")

    return AppConfig(
        thresholds=thresholds,
        sample_size_tiers=tiers,
        confidence_explanations=dict(explanations),
        rating_rationale=rating_rationale,
        covered_precincts=covered,
        excluded_precincts=excluded,
        precinct_populations=precinct_populations,
        city_mean_per_100k=city_mean,
        max_retries=max_retries,
        disclaimer=disclaimer,
        disclaimer_emergency_line=disclaimer_emergency_line,
        addressing=AddressingConfig(aliases=aliases),
        degraded=degraded,
        suggestions=suggestions,
        one_liner=one_liner,
        time_buckets=time_buckets,
        emergency=emergency,
        followup=followup,
        comparison=comparison,
        guardrails=guardrails,
        profile=profile,
        intel=intel,
        data_source=data_source,
        cost_control=cost_control,
        synthetic_user=synthetic_user,
        llm=llm,
        eval=eval_cfg,
    )


@functools.lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """进程级缓存的默认配置入口；测试请用 load_config(path) 或 get_config.cache_clear()。"""
    return load_config()
