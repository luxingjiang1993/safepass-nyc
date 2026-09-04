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

# config/app.yaml 相对本文件：safepass/config_loader.py -> 项目根/config/app.yaml
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "app.yaml"


class ConfigError(RuntimeError):
    """集中配置缺失、损坏或违反不变量时抛出（明确失败，不静默兜底）。"""


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
    """

    empty_talk_blacklist: tuple[str, ...]
    safety_general: tuple[str, ...]


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
class AppConfig:
    thresholds: RatingThresholds
    sample_size_tiers: tuple[SampleSizeTier, ...]
    confidence_explanations: dict[str, str]
    covered_precincts: frozenset[int]
    excluded_precincts: frozenset[int]
    city_mean_per_100k: float | None
    max_retries: int
    disclaimer: str
    addressing: AddressingConfig
    degraded: DegradedConfig
    suggestions: SuggestionsConfig
    emergency: EmergencyConfig
    followup: FollowUpConfig
    comparison: ComparisonConfig
    guardrails: GuardrailsConfig
    profile: ProfileConfig
    intel: IntelConfig


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

    coverage = _require(data, "coverage", "root")
    covered = frozenset(int(p) for p in _require(coverage, "precincts", "coverage"))
    excluded = frozenset(int(p) for p in coverage.get("excluded_precincts", []))
    if not covered:
        raise ConfigError("coverage.precincts 不能为空")
    if covered & excluded:
        raise ConfigError("coverage.precincts 与 excluded_precincts 不得相交")

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

    suggestions_raw = _require(data, "suggestions", "root")
    suggestions = SuggestionsConfig(
        empty_talk_blacklist=tuple(
            str(w) for w in _require(suggestions_raw, "empty_talk_blacklist", "suggestions")
        ),
        safety_general=tuple(
            str(s) for s in _require(suggestions_raw, "safety_general", "suggestions")
        ),
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

    return AppConfig(
        thresholds=thresholds,
        sample_size_tiers=tiers,
        confidence_explanations=dict(explanations),
        covered_precincts=covered,
        excluded_precincts=excluded,
        city_mean_per_100k=city_mean,
        max_retries=max_retries,
        disclaimer=disclaimer,
        addressing=AddressingConfig(aliases=aliases),
        degraded=degraded,
        suggestions=suggestions,
        emergency=emergency,
        followup=followup,
        comparison=comparison,
        guardrails=guardrails,
        profile=profile,
        intel=intel,
    )


@functools.lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """进程级缓存的默认配置入口；测试请用 load_config(path) 或 get_config.cache_clear()。"""
    return load_config()
