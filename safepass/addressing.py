"""中文地址识别（issue 05 / D12 最小版；issue 09 / T7 扩充为完整版）。

职责只做两件事（spec D12：地址解析结果是越界判定的唯一权威）：
    1. 警区映射：查询文本 → 配置别名表（config/app.yaml addressing.aliases）
       命中的警区列表（中城 → [14, 18]；哥大附近 → 26）。
    2. 覆盖清单判定：命中警区 ⊆ covered_precincts 且为单一警区才算覆盖内。

零 LLM 参与、零警区号字面量（一律读集中配置）。
长别名优先 + 重叠去重：「布鲁克林 Heights」不会被「布鲁克林高地」的短命中截断。
10/10 地址集（PRD UX-002）与扩展标注集（>90%，NEG-007）由
tests/test_chinese_address.py / tests/test_guardrails.py 锁定别名表。
"""

from __future__ import annotations

from dataclasses import dataclass

from safepass import config_loader


@dataclass(frozen=True)
class ResolvedArea:
    """一次别名命中的解析结果。

    area:      命中的别名原文（越界说明里诚实点出用户说的是哪里）。
    canonical_name: 命中警区在覆盖清单内的规范中文名（越界/跨警区时回退为别名原文）。
    precincts: 解析出的警区号列表；多警区（中城）天然无法按警区建模。
    """

    area: str
    canonical_name: str
    precincts: tuple[int, ...]

    def in_coverage(self, cfg: config_loader.AppConfig) -> bool:
        """单一警区且该警区在覆盖清单内（D12 后置校验的判定口径）。"""
        return len(self.precincts) == 1 and self.precincts[0] in cfg.covered_precincts


def canonical_names(cfg: config_loader.AppConfig) -> dict[int, str]:
    """覆盖警区 → 规范中文名：取配置别名表中首个映射到该警区的别名（顺序稳定）。"""
    names: dict[int, str] = {}
    for alias, precincts in cfg.addressing.aliases.items():
        if len(precincts) == 1 and precincts[0] in cfg.covered_precincts:
            names.setdefault(precincts[0], alias)
    return names


def resolve_areas(
    query_text: str, cfg: config_loader.AppConfig
) -> tuple[ResolvedArea, ...]:
    """按别名表解析查询文本中提到的全部区域，按出现位置排序。

    同一警区集合只保留首次命中（「上东区和上东城」= 一个区域）；
    长别名优先且重叠区间不重复计数。查无所获返回空元组（由调用方明确处理）。
    """
    lowered = query_text.lower()
    spans: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for alias in sorted(cfg.addressing.aliases, key=len, reverse=True):
        start = lowered.find(alias.lower())
        if start == -1:
            continue
        span = (start, start + len(alias))
        if any(span[0] < s[1] and s[0] < span[1] for s in spans):
            continue  # 与已有命中重叠，长别名优先
        spans.append(span)
        hits.append((start, alias))

    names = canonical_names(cfg)
    seen: set[tuple[int, ...]] = set()
    resolved: list[ResolvedArea] = []
    for _, alias in sorted(hits):
        precincts = cfg.addressing.aliases[alias]
        if precincts in seen:
            continue
        seen.add(precincts)
        canonical = names.get(precincts[0], alias) if len(precincts) == 1 else alias
        resolved.append(ResolvedArea(area=alias, canonical_name=canonical, precincts=precincts))
    return tuple(resolved)
