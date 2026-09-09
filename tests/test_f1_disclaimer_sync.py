"""票 06 / F1：免责页时间范围与来源与覆盖内契约同源。

接缝（spec 波 2 第三刀 F1）：
    execute_query → SafetyQueryResult.sources / time_range；
    render.render_disclaimer_page；
    单一事实源 = config data_source.sources / data_source.time_range。
免责话术仍是配置字面量，不经 LLM。
"""

from __future__ import annotations

import dataclasses

from safepass import config_loader, contracts
from safepass.pipeline import execute_query
from frontend import render

_PROBE_TIME = "PROBE-TIME-RANGE-F1"
_PROBE_SOURCE = "PROBE-SOURCE-F1"


def test_in_coverage_contract_matches_disclaimer_page():
    cfg = config_loader.get_config()
    result = execute_query("上东区安全吗？")
    assert isinstance(result, contracts.SafetyQueryResult)
    html = render.render_disclaimer_page(cfg, [])
    assert result.time_range
    assert result.sources
    assert result.time_range in html
    for src in result.sources:
        assert src in html
    assert cfg.disclaimer in html
    assert result.disclaimer == cfg.disclaimer


def test_config_time_range_and_sources_are_the_fact_source():
    cfg = config_loader.get_config()
    result = execute_query("上东区安全吗？")
    assert isinstance(result, contracts.SafetyQueryResult)
    assert result.time_range == cfg.data_source.time_range
    assert result.sources == list(cfg.data_source.sources)


def test_changing_config_moves_contract_and_disclaimer_together(monkeypatch):
    cfg = config_loader.get_config()
    probed = dataclasses.replace(
        cfg,
        data_source=dataclasses.replace(
            cfg.data_source,
            time_range=_PROBE_TIME,
            sources=(_PROBE_SOURCE,),
        ),
    )
    monkeypatch.setattr(config_loader, "get_config", lambda: probed)
    result = execute_query("上东区安全吗？")
    assert isinstance(result, contracts.SafetyQueryResult)
    html = render.render_disclaimer_page(probed, [])
    assert result.time_range == _PROBE_TIME
    assert result.sources == [_PROBE_SOURCE]
    assert _PROBE_TIME in html
    assert _PROBE_SOURCE in html
    assert cfg.data_source.time_range not in html
    assert cfg.data_source.time_range != result.time_range
