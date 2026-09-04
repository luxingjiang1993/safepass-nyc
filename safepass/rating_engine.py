"""评级引擎（ADR-0001 / spec D4；issue 04 / RALPH T2）。

纯函数：输入数据 Agent 统计（data_agent.PrecinctStats）+ 全市均值
→ 输出安全评级枚举（green/yellow/red/insufficient_data）与可信度档
（HIGH/MODERATE/LOW）。零 LLM 参与、零画像参与（ADR-0002：画像不改变评级）。

规则全部读集中配置（config/app.yaml），本模块不内置任何阈值系数/样本量档位：
- 倍数 = per-100k 犯罪率 / 全市均值；低于 green_max_ratio → 🟢；
  达到 green_max 至 red_min（含两端）→ 🟡；高于 red_min_ratio → 🔴
- 样本量门控与评级同源（同一 sample_size 输入）：落入强制档
  （rating 非空，如 insufficient_data）→ 不给评级数值、不给可信度、不给解释
- 可信度解释 = 配置固定模板 .format(n=真实命中数)，动态透出
- 全市均值缺失（T0 未回填）→ 明确失败，不静默兜底
"""

from __future__ import annotations

from dataclasses import dataclass

from safepass import config_loader
from safepass.data_agent import PrecinctStats

RATING_GREEN = "green"
RATING_YELLOW = "yellow"
RATING_RED = "red"


@dataclass(frozen=True)
class RatingResult:
    """评级输出：评级字段是枚举，不出现自由文本（spec D3）。

    ratio_to_city_mean 即契约的 rating_explainable_basis（per-100k 与市均值倍数）；
    sample_size 与数据 Agent 聚合同源（同一真实命中数输入）。
    """

    rating: str  # green | yellow | red | insufficient_data（后者取值来自配置强制档）
    ratio_to_city_mean: float
    confidence: str | None  # HIGH | MODERATE | LOW；强制 ⚪ 档为 None
    explanation: str | None  # 配置固定模板动态填充命中数；强制 ⚪ 档为 None
    sample_size: int


def _tier_for_sample_size(
    sample_size: int, cfg: config_loader.AppConfig
) -> config_loader.SampleSizeTier:
    for tier in cfg.sample_size_tiers:
        if tier.min <= sample_size and (tier.max is None or sample_size <= tier.max):
            return tier
    # config_loader 保证区间从 0 开始且无缝衔接，此处不可达；防御性明确失败
    raise config_loader.ConfigError(f"样本量 {sample_size} 无匹配档位（配置不变量被破坏）")


def rate_precinct(
    stats: PrecinctStats, cfg: config_loader.AppConfig | None = None
) -> RatingResult:
    """评级纯函数：单警区统计 → 评级枚举 + 可信度档 + 解释。零 LLM、零画像。"""
    if cfg is None:
        cfg = config_loader.get_config()
    if cfg.city_mean_per_100k is None:
        raise config_loader.ConfigError(
            "city_mean_per_100k 未回填（config/app.yaml）；评级引擎依赖全市均值，拒绝运行"
        )
    ratio = stats.rate_per_100k / cfg.city_mean_per_100k
    tier = _tier_for_sample_size(stats.sample_size, cfg)
    if tier.rating is not None:
        # 强制档（样本量不足 ⚪）：不给出评级数值、不给可信度、不给解释（spec D4）
        return RatingResult(
            rating=tier.rating,
            ratio_to_city_mean=ratio,
            confidence=None,
            explanation=None,
            sample_size=stats.sample_size,
        )
    thresholds = cfg.thresholds
    if ratio < thresholds.green_max_ratio:
        rating = RATING_GREEN
    elif ratio <= thresholds.red_min_ratio:
        rating = RATING_YELLOW
    else:
        rating = RATING_RED
    template = cfg.confidence_explanations.get(tier.confidence)
    if template is None:
        raise config_loader.ConfigError(
            f"confidence_explanations 缺少档位 {tier.confidence} 的模板（config/app.yaml）"
        )
    return RatingResult(
        rating=rating,
        ratio_to_city_mean=ratio,
        confidence=tier.confidence,
        explanation=template.format(n=stats.sample_size),
        sample_size=stats.sample_size,
    )
