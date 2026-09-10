"""罪名中文展示（C3）：图表 Top5 与建议数据包共用配置映射。

映射只活在 config one_liner.type_names / unknown_offense_label。
未收录类型外显 unknown_offense_label，count 原样保留。无翻译 API。
"""

from __future__ import annotations

from safepass import config_loader, contracts


def offense_label_zh(offense_type: str, cfg: config_loader.AppConfig) -> str:
    """类型代码 → 展示用中文；未收录则外显配置 unknown_offense_label。"""
    return cfg.one_liner.type_names.get(offense_type, cfg.one_liner.unknown_offense_label)


def mapped_offense_count(
    offense_type: str, count: int, cfg: config_loader.AppConfig
) -> contracts.OffenseCount:
    """契约 Top5 条目：代码保留，中文名与建议数据包同源。"""
    return contracts.OffenseCount(
        offense_type=offense_type,
        count=count,
        label_zh=offense_label_zh(offense_type, cfg),
    )
