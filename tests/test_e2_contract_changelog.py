"""issue 39 / E2 契约版本说明：短 changelog 列出本刀相关字段与前端兼容策略。

接缝：
    文档 = docs/contract-changelog.md（约定小节存在即可，不锁散文措辞以外的版式）
    渲染 = frontend.render.render_result：未知键不得崩，空 suggestion_grounds
           不得装成有建议依据
    契约 = SafetyQueryResult.model_validate 忽略未知键，不引入服务型 API 版本号
"""

from __future__ import annotations

from pathlib import Path

from frontend import render
from safepass import config_loader, contracts
from tests.test_frontend_render import make_safety

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "docs" / "contract-changelog.md"
CFG = config_loader.get_config()


def _changelog() -> str:
    assert CHANGELOG.is_file(), "缺少 docs/contract-changelog.md（E2 契约字段短说明）"
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.strip(), "契约 changelog 不得为空"
    return text


def test_changelog_lists_wave2_fields_and_frontend_compat():
    text = _changelog()
    assert "rating_rationale" in text
    assert "时段桶" in text
    assert "中文罪名" in text
    assert "未知" in text and "崩" in text
    assert "假装有依据" in text or "装成有依据" in text


def test_changelog_rejects_service_api_versioning():
    text = _changelog()
    assert "不" in text and ("API 版本" in text or "api 版本" in text.lower())
    lowered = text.lower()
    assert "api_version" not in lowered
    assert "/v1/" not in lowered
    assert "/v2/" not in lowered


def test_contracts_module_points_at_changelog():
    src = (REPO_ROOT / "safepass" / "contracts.py").read_text(encoding="utf-8")
    assert "docs/contract-changelog.md" in src
    assert "api_version" not in contracts.SafetyQueryResult.model_fields
    for cls in (
        contracts.SafetyQueryResult,
        contracts.ComparisonResult,
        contracts.EmergencyResult,
        contracts.DegradedResult,
        contracts.GuardrailResult,
    ):
        assert "api_version" not in cls.model_fields


def test_unknown_payload_keys_do_not_crash_or_fake_grounds():
    payload = make_safety().model_dump()
    assert payload["suggestion_grounds"] == []
    payload["e2_unknown_future_field"] = "不得渲染"
    payload["offense_label_zh"] = "盗窃"
    payload["fake_grounds"] = [{"doc_id": "x", "quote": "伪造的建议依据"}]
    result = contracts.SafetyQueryResult.model_validate(payload)
    assert result.suggestion_grounds == []
    html = render.render_result(result, CFG)
    assert "伪造的建议依据" not in html
    assert "不得渲染" not in html
    assert "不得渲染" not in html
    assert "通用建议" in html
    assert 'class="suggestion-grounds"' not in html
    assert "建议依据" not in html
    assert "评级依据" in html
