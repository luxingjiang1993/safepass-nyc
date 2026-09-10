"""票 07 / A5：画像本机可感知。

接缝：
    唯一接缝 execute_query —— 同区两画像 rating 相等、suggestions 不全等；
    Skill 请求体仍无六维画像。
    展示接缝 render_result —— 覆盖内折叠默认闭合、无第二盏灯；
    无画像 / 紧急 / 越界 / 防线无该块。
本票不跑 L2。
"""

from __future__ import annotations

import json
import threading
from urllib.parse import quote

import pytest

from frontend import app, render
from safepass import config_loader, contracts, pipeline
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query
from safepass.skills.suggestion import SuggestionPack
from tests.test_frontend_app import _FORM_BODY, get, post
from tests.test_frontend_render import (
    make_comparison,
    make_degraded,
    make_emergency,
    make_safety,
)

CFG = config_loader.get_config()

_ROUTE_OUT = json.dumps({"route": "area_safety_query"}, ensure_ascii=False)
_EXTRACTION_OUT = json.dumps(
    {"area": "上东区", "crowd": None, "time": None}, ensure_ascii=False
)
_SKILL_OUT = json.dumps(
    {
        "suggestions": [
            "夜间出行尽量结伴，并提前告知朋友行程",
            "随身包放在身前视线范围内，手机握在手里",
            "优先选择照明好、人流多的主干道通行",
        ],
        "suggestion_grounds": [],
    },
    ensure_ascii=False,
)

KID_PROFILE = {"scene": ["带娃"]}
LATE_FEMALE_PROFILE = {"gender": "女生", "scene": ["晚归"]}
SIX_DIM_PROFILE = {
    "gender": "女生",
    "age": "18-25",
    "identity": "留学生",
    "english": "基础日常",
    "duration": "刚来（1年以内）",
    "scene": ["晚归"],
}


class _ScriptedFakeLLM:
    def __init__(self, script: list[str]):
        self._script = list(script)
        self.seen_messages: list[list[dict]] = []

    def chat(self, messages, *, model=None, **kwargs):
        self.seen_messages.append([dict(m) for m in messages])
        content = self._script.pop(0)
        return ChatResponse(content=content, model=model or "qwen-flash")


def test_same_area_two_profiles_rating_equal_suggestions_differ():
    """同区两画像：灯不变、建议不全等；晚归女生建议能看见夜间或独处。"""
    kid = execute_query("上东区安全吗？", profile=KID_PROFILE)
    late = execute_query("上东区安全吗？", profile=LATE_FEMALE_PROFILE)
    plain = execute_query("上东区安全吗？")

    assert kid.type == late.type == "safety"
    assert kid.rating == late.rating == plain.rating
    assert kid.suggestions != late.suggestions
    assert late.suggestions != plain.suggestions
    assert any("夜间" in s or "独处" in s for s in late.suggestions)
    assert any(d["dimension"] == "时间提示" for d in late.dimensions)
    assert all(d["dimension"] != "时间提示" for d in kid.dimensions)


def test_six_dim_profile_never_enters_skill_request():
    """六维画像不进 Skill 输入打包，也不出现在发给模型的请求体。"""
    fake = _ScriptedFakeLLM([_ROUTE_OUT, _EXTRACTION_OUT, _SKILL_OUT])
    result = execute_query(
        "上东区安全吗？", profile=SIX_DIM_PROFILE, llm_client=fake
    )
    assert result.type == "safety"
    assert SuggestionPack.__dataclass_fields__.keys().isdisjoint({"profile", "persona"})
    all_text = "\n".join(m["content"] for call in fake.seen_messages for m in call)
    for marker in ("18-25", "基础日常", "刚来（1年以内）"):
        assert marker not in all_text, f"六维画像泄漏进 LLM 请求体：{marker!r}"


def test_privacy_page_keeps_zero_upload_wording():
    """隐私页零上传口径不改为「画像上传」。"""
    html = render.render_privacy(CFG)
    assert "零上传" in html
    assert "画像不会发送给任何第三方服务" in html
    assert "画像上传" not in html


def test_coverage_fold_collapsed_suggestions_only_no_second_light():
    """有画像的覆盖内页：折叠默认关闭，只并排建议，没有第二盏灯。"""
    html = render.render_result(
        make_safety(),
        CFG,
        profile=LATE_FEMALE_PROFILE,
        baseline_suggestions=[
            "夜间出行尽量结伴，并提前告知朋友行程",
            "随身包放在身前视线范围内，手机握在手里",
            "优先选择照明好、人流多的主干道通行",
        ],
    )
    assert '<details class="profile-compare">' in html
    assert '<details class="profile-compare" open' not in html
    assert "对比：无画像时的建议" in html
    fold_start = html.index('class="profile-compare"')
    fold_end = html.index("</details>", fold_start)
    fold = html[fold_start:fold_end]
    assert "rating-" not in fold
    assert "🟢" not in fold and "🟡" not in fold and "🔴" not in fold
    assert "相对安全" not in fold
    assert html.count('class="result-head') == 1
    assert html.index("紧急资源") < html.index("对比：无画像时的建议")


def test_no_profile_and_non_coverage_pages_have_no_compare_fold():
    """无画像 / 紧急 / 越界 / 防线不渲染该折叠。"""
    baseline = ["夜间出行尽量结伴，并提前告知朋友行程"]
    safety_no_profile = render.render_result(
        make_safety(), CFG, baseline_suggestions=baseline
    )
    emergency = render.render_result(make_emergency(), CFG, profile=LATE_FEMALE_PROFILE)
    degraded = render.render_result(
        make_degraded(), CFG, profile=LATE_FEMALE_PROFILE
    )
    guardrail = render.render_result(
        contracts.GuardrailResult(
            guardrail_kind="weapon_refusal",
            message="我们无法提供武器或器械的选购与携带建议",
            alternatives=["担心出行安全时，优先选择照明好、人流多的主干道"],
            sources=[],
            disclaimer="本分析仅供参考，不替代专业安保建议。",
        ),
        CFG,
        profile=LATE_FEMALE_PROFILE,
    )
    comparison = render.render_result(
        make_comparison(), CFG, profile=LATE_FEMALE_PROFILE
    )
    for html in (
        safety_no_profile,
        emergency,
        degraded,
        guardrail,
        comparison,
    ):
        assert "profile-compare" not in html
        assert "对比：无画像时的建议" not in html


@pytest.fixture()
def server():
    srv = app.create_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_http_compare_fold_uses_second_empty_profile_seam(server, monkeypatch):
    """对比块：有画像时再跑一次空画像接缝；折叠可见且零上传。"""
    calls: list[dict | None] = []
    real = pipeline.execute_query

    def spy(query_text, *, profile=None, session_state=None, llm_client=None):
        calls.append(profile)
        return real(
            query_text,
            profile=profile,
            session_state=session_state,
            llm_client=llm_client,
        )

    monkeypatch.setattr(app.pipeline, "execute_query", spy)
    posted = post(server, "/profile", body=_FORM_BODY)
    cookie = posted.getheader("Set-Cookie").split(";")[0]
    resp = get(server, f"/query?q={quote('上东区')}", cookie=cookie)
    assert resp.status == 200
    body = resp.body  # type: ignore[attr-defined]
    assert "对比：无画像时的建议" in body
    assert '<details class="profile-compare">' in body
    assert body.count('class="result-head') == 1
    fold_start = body.index('class="profile-compare"')
    fold_end = body.index("</details>", fold_start)
    fold = body[fold_start:fold_end]
    assert "rating-" not in fold
    assert "🟢" not in fold
    assert len(calls) == 2
    assert calls[0]
    assert calls[1] is None


def test_http_no_profile_or_emergency_skips_compare_fold(server, monkeypatch):
    """无画像只跑一次接缝；紧急页即使有画像也不出对比块。"""
    calls: list[dict | None] = []
    real = pipeline.execute_query

    def spy(query_text, *, profile=None, session_state=None, llm_client=None):
        calls.append(profile)
        return real(
            query_text,
            profile=profile,
            session_state=session_state,
            llm_client=llm_client,
        )

    monkeypatch.setattr(app.pipeline, "execute_query", spy)
    plain = get(server, f"/query?q={quote('上东区')}")
    assert plain.status == 200
    assert "对比：无画像时的建议" not in plain.body  # type: ignore[attr-defined]
    assert len(calls) == 1

    posted = post(server, "/profile", body=_FORM_BODY)
    cookie = posted.getheader("Set-Cookie").split(";")[0]
    emergency = get(server, f"/query?q={quote('被跟踪了')}", cookie=cookie)
    assert emergency.status == 200
    assert "对比：无画像时的建议" not in emergency.body  # type: ignore[attr-defined]
    assert "theme-emergency" in emergency.body  # type: ignore[attr-defined]
    assert len(calls) == 2
    assert calls[-1]
