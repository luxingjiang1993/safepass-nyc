"""前端作品集级打磨测试（票 09）：空态/错误态文案与视觉 + 窄屏不破版。

全部是结构层断言：
    404 错误态：完整 HTML 页面（非裸文本）、与全站同一样式体系、
        有明确文案与回家路径（错误态 = 有文案有视觉处理，不是裸 Not Found）
    空态防线：查询输入框 required——浏览器原生拦截空提交（明确文案 + 视觉焦点），
        服务端 302 回首页仍作兜底（既有断言不动）
    窄屏不破版：样式含 max-width 媒体查询块（页边距/条形图标签/911 大按钮
        在小屏下显式收紧），长链接可断行不撑出横向滚动

UX 主观项（实机窄屏观感、无障碍抽验）转人工验收清单，不在本文件。
"""

from __future__ import annotations

import http.client
import threading
from pathlib import Path

import pytest

from frontend import app, render

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def server():
    srv = app.create_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def get(srv, path: str) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=60)
    conn.request("GET", path)
    resp = conn.getresponse()
    resp.body = resp.read().decode("utf-8")  # type: ignore[attr-defined]
    conn.close()
    return resp


# ---------------------------------------------------------------- 错误态（404）

class TestNotFoundPage:
    """错误态打磨：404 是完整页面——有文案、有视觉、有出路（票 09 勾选 1）。"""

    def test_404_status_preserved(self, server):
        # 既有断言（test_unknown_path_404）语义不变：未知路径仍是 404
        assert get(server, "/nope").status == 404

    def test_404_is_full_html_page_not_bare_text(self, server):
        body = get(server, "/nope").body  # type: ignore[attr-defined]
        assert body.startswith("<!DOCTYPE html>")
        assert "</html>" in body

    def test_404_uses_same_stylesheet(self, server):
        # 视觉统一：错误页与首页/结果页同一样式体系（非无样式的裸文本）
        body = get(server, "/nope").body  # type: ignore[attr-defined]
        assert "/static/style.css" in body

    def test_404_has_friendly_copy_and_way_home(self, server):
        body = get(server, "/nope").body  # type: ignore[attr-defined]
        assert "404" in body  # 明确状态码呈现
        assert 'href="/"' in body  # 明确的回家路径，不把用户留在死胡同

    def test_404_post_unknown_path_also_styled(self, server):
        conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=60)
        conn.request("POST", "/nope", body="", headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        assert resp.status == 404
        assert body.startswith("<!DOCTYPE html>")


# ---------------------------------------------------------------- 空态（查询输入）

class TestEmptyStateGuard:
    """空态防线：查询框 required——空提交在浏览器侧即被拦下并给出明确提示。"""

    def test_query_input_has_required_guard(self):
        from safepass import config_loader

        html = render.render_home(config_loader.get_config())
        start = html.index('name="q"')
        tag = html[start : html.index(">", start)]  # input 开标签整体
        assert "required" in tag

    def test_empty_query_server_fallback_unchanged(self, server):
        # 服务端兜底仍是 302 回首页（既有行为不破；required 只是第一道防线）
        resp = get(server, "/query?q=")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"


# ---------------------------------------------------------------- 窄屏不破版

class TestNarrowScreen:
    """窄屏结构层：小屏媒体查询块存在且收紧关键布局；长链接可断行。"""

    @pytest.fixture()
    def css(self, server) -> str:
        return get(server, "/static/style.css").body  # type: ignore[attr-defined]

    def test_mobile_media_query_block_exists(self, css):
        assert "@media (max-width: 30rem)" in css

    def test_mobile_block_tightens_key_layout(self, css):
        # 小屏下显式收紧的三处：页边距（不破版）、条形图标签（不挤压数值）、
        # 911 大按钮（恐慌场景下仍是最大视觉目标）
        block = css[css.index("@media (max-width: 30rem)") :]
        block = block[: block.index("/* ---")]  # 到下一个注释块为止
        for selector in (".page", ".bar-label", ".call-911-big"):
            assert selector in block

    def test_long_links_can_break(self, css):
        # 窄屏下长 URL 可断行，不撑出横向滚动（overflow-wrap）
        assert "overflow-wrap" in css
