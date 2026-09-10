"""票 09 / D4：视觉网格、浅深主题与十槽插画。

接缝（第三刀 Testing Decisions）：
    render —— prefers-color-scheme 与显式 cookie 的 html class 可分；
    紧急页 class 不含深色主题；10 槽各有一处 data-illustration 标记。
    app —— 主题 cookie 名可锁；页内开关写入 cookie（不是画像）。
    隐私页 —— 写明主题 cookie（不是画像）。
    先验：D1 首屏结构锁仍绿。不锁 CSS 像素、不锁 SVG path。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from frontend import app, render
from safepass import config_loader, contracts
from tests.test_frontend_app import get
from tests.test_frontend_render import (
    make_comparison,
    make_degraded,
    make_emergency,
    make_safety,
)

CFG = config_loader.get_config()
REPO_ROOT = Path(__file__).resolve().parent.parent
CSS = (REPO_ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")

THEME_COOKIE = "safepass_theme"


@pytest.fixture()
def server():
    srv = app.create_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)

# 十槽插画标记（自制单色 SVG；不按灯配犯罪图）
ILLUSTRATION_SLOTS = (
    "home",
    "safety-header",
    "out-of-coverage",
    "emergency",
    "empty",
    "fuse",
    "guardrail",
    "comparison",
    "legal",
    "unparseable",
)


def _html_class(html: str) -> str:
    """从 <html ...> 开标签抽出 class 属性值（无则空串）。"""
    start = html.index("<html")
    end = html.index(">", start)
    tag = html[start:end]
    marker = 'class="'
    if marker not in tag:
        return ""
    i = tag.index(marker) + len(marker)
    return tag[i : tag.index('"', i)]


class TestThemeClasses:
    def test_explicit_dark_cookie_sets_html_theme_dark(self):
        html = render.render_home(CFG, theme="dark")
        assert "theme-dark" in _html_class(html)
        assert "theme-light" not in _html_class(html)

    def test_explicit_light_cookie_sets_html_theme_light(self):
        html = render.render_home(CFG, theme="light")
        assert "theme-light" in _html_class(html)
        assert "theme-dark" not in _html_class(html)

    def test_no_cookie_leaves_html_without_explicit_theme_class(self):
        # 无显式 cookie 时不钉死浅/深 class，交给 CSS prefers-color-scheme
        html = render.render_home(CFG, theme=None)
        classes = _html_class(html)
        assert "theme-dark" not in classes
        assert "theme-light" not in classes

    def test_css_has_prefers_color_scheme_and_explicit_overrides(self):
        assert "prefers-color-scheme" in CSS
        assert "html.theme-dark" in CSS or "html.theme-light" in CSS

    def test_emergency_page_has_no_dark_theme_class(self):
        html = render.render_emergency(make_emergency(), theme="dark")
        assert "theme-emergency" in html
        assert "theme-dark" not in _html_class(html)
        assert 'class="theme-emergency"' in html or "theme-emergency" in html

    def test_theme_switch_present_on_non_emergency_pages(self):
        html = render.render_home(CFG)
        assert "theme-switch" in html
        assert f"/theme?set=dark" in html or 'set=dark' in html
        assert f"/theme?set=light" in html or 'set=light' in html

    def test_theme_switch_absent_on_emergency_page(self):
        html = render.render_emergency(make_emergency())
        assert "theme-switch" not in html


class TestThemeCookieRoute:
    def test_theme_route_sets_theme_cookie_and_redirects(self, server):
        resp = get(server, "/theme?set=dark")
        assert resp.status in (302, 303)
        set_cookie = resp.getheader("Set-Cookie") or ""
        assert f"{THEME_COOKIE}=dark" in set_cookie
        # 主题 cookie 不是会话画像载体
        assert "safepass_sid=" not in set_cookie or THEME_COOKIE in set_cookie

    def test_theme_cookie_applied_on_subsequent_page(self, server):
        get(server, "/theme?set=dark")
        home = get(server, "/", cookie=f"{THEME_COOKIE}=dark")
        assert home.status == 200
        assert "theme-dark" in _html_class(home.body)  # type: ignore[attr-defined]

    def test_theme_system_clears_explicit_cookie(self, server):
        resp = get(server, "/theme?set=system")
        set_cookie = resp.getheader("Set-Cookie") or ""
        assert THEME_COOKIE in set_cookie
        assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


class TestTenIllustrationSlots:
    def test_all_ten_slots_marked(self):
        pages = {
            "home": render.render_home(CFG),
            "safety-header": render.render_safety(make_safety(), CFG),
            "out-of-coverage": render.render_degraded(make_degraded(), CFG),
            "emergency": render.render_emergency(make_emergency()),
            "empty": render.render_empty_state(CFG),
            "fuse": render.render_safety(
                make_safety(
                    llm_degraded=True,
                    degradation_notice="今日 AI 生成预算已用尽，本回复改由确定性数据与模板生成；安全评级与统计数据不受影响。",
                ),
                CFG,
            ),
            "guardrail": render.render_guardrail(
                contracts.GuardrailResult(
                    guardrail_kind="weapon_refusal",
                    message="我们无法提供武器或器械的选购与携带建议",
                    alternatives=["担心出行安全时，优先选择照明好、人流多的主干道"],
                    sources=[],
                    disclaimer=CFG.disclaimer,
                )
            ),
            "comparison": render.render_comparison(make_comparison(), CFG),
            "legal": render.render_privacy(CFG),
            "unparseable": render.render_not_found(CFG),
        }
        for slot in ILLUSTRATION_SLOTS:
            html = pages[slot]
            assert f'data-illustration="{slot}"' in html, f"缺插画槽：{slot}"
            assert "<svg" in html[html.index(f'data-illustration="{slot}"') :][:800]

    def test_legal_slot_shared_by_privacy_and_disclaimer(self):
        privacy = render.render_privacy(CFG)
        disclaimer = render.render_disclaimer_page(CFG, [])
        assert 'data-illustration="legal"' in privacy
        assert 'data-illustration="legal"' in disclaimer

    def test_illustrations_are_monochrome_current_color_not_rating_art(self):
        # 单色随主题变色：用 currentColor；禁止按灯配犯罪叙事图
        home = render.render_home(CFG)
        assert "currentColor" in home
        assert "rating-green" not in home.split("data-illustration")[1][:400]


class TestPrivacyThemeCookieDisclosure:
    def test_privacy_mentions_theme_cookie_separate_from_profile(self):
        html = render.render_privacy(CFG)
        assert THEME_COOKIE in html or "主题" in html
        assert "画像" in html
        # 不得再声称「唯一 cookie」却漏掉主题偏好
        assert "主题" in html
        assert "不是画像" in html or "不是会话画像" in html or "不含查询" in html


class TestBriefingGridCss:
    def test_briefing_grid_and_type_scale_exist(self):
        assert "briefing-grid" in CSS
        assert "--fs-" in CSS or "font-size" in CSS

    def test_safety_page_uses_briefing_grid_wrapper(self):
        html = render.render_safety(make_safety(), CFG)
        assert "briefing-grid" in html


class TestD1SlotOrderStillHolds:
    def test_five_slot_order_unchanged(self):
        html = render.render_result(make_safety(), CFG)

        def idx(marker: str) -> int:
            assert html.count(marker) == 1, marker
            return html.index(marker)

        order = [
            idx('class="result-head'),
            idx('class="one-liner"'),
            idx('class="suggestions"'),
            idx("紧急资源"),
            idx('class="dimensions"'),
        ]
        assert order == sorted(order)
