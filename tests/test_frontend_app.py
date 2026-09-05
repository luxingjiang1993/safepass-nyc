"""前端 HTTP 薄服务层集成测试（issue 11）。

起真实线程化服务（端口 0），走真实路由与唯一接缝 execute_query
（llm_client=None 确定性路径：静态意图标记 + D12 后置 + 区域解析，
离线可跑）。断言结构层：首页五按钮、查询结果评级与免责、
Set-Cookie 会话建立、显式双区对比渲染对比视图、降级形态渲染。
"""

from __future__ import annotations

import http.client
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from frontend import app

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


def get(srv, path: str, cookie: str | None = None) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=60)
    headers = {"Cookie": cookie} if cookie else {}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    resp.body = resp.read().decode("utf-8")  # type: ignore[attr-defined]
    conn.close()
    return resp


def post(
    srv,
    path: str,
    body: str = "",
    cookie: str | None = None,
    referer: str | None = None,
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=60)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    if referer:
        headers["Referer"] = referer
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    resp.body = resp.read().decode("utf-8")  # type: ignore[attr-defined]
    conn.close()
    return resp


class TestHomeRoute:
    def test_home_200_with_quick_buttons(self, server):
        resp = get(server, "/")
        assert resp.status == 200
        for area in ("上东区", "法拉盛", "唐人街", "威廉斯堡", "布鲁克林高地"):
            assert area in resp.body  # type: ignore[attr-defined]

    def test_static_css(self, server):
        resp = get(server, "/static/style.css")
        assert resp.status == 200
        assert "text/css" in resp.getheader("Content-Type")

    def test_unknown_path_404(self, server):
        assert get(server, "/nope").status == 404


class TestQueryRoute:
    def test_quick_query_safety_result(self, server):
        resp = get(server, f"/query?q={quote('上东区')}")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "🟢" in body and "相对安全" in body
        assert "上东区" in body
        assert "本分析仅供参考，不替代专业安保建议。" in body
        assert "📈" in body  # 有数据 → 图表模块渲染

    def test_query_sets_session_cookie(self, server):
        resp = get(server, f"/query?q={quote('上东区')}")
        set_cookie = resp.getheader("Set-Cookie")
        assert set_cookie is not None
        assert "safepass_sid=" in set_cookie and "HttpOnly" in set_cookie

    def test_explicit_comparison_query(self, server):
        resp = get(server, f"/query?q={quote('上东区和唐人街哪个更安全')}")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "🔀" in body  # 对比视图
        assert "上东区" in body and "唐人街" in body

    def test_out_of_coverage_query_degraded_view(self, server):
        resp = get(server, f"/query?q={quote('哥大附近安全吗')}")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "暂时无法给出完整分析" in body
        assert "本分析仅供参考，不替代专业安保建议。" in body

    def test_empty_query_redirects_home(self, server):
        resp = get(server, "/query?q=")
        assert resp.status == 302
        assert resp.getheader("Location") == "/"

    def test_session_followup_comparison_via_cookie(self, server):
        # 会话载体：首轮安全结果建立会话，随后显式对比照常渲染（cookie 贯穿）
        first = get(server, f"/query?q={quote('上东区')}")
        cookie = first.getheader("Set-Cookie").split(";")[0]
        second = get(server, f"/query?q={quote('布鲁克林高地')}", cookie=cookie)
        assert second.status == 200
        assert "布鲁克林高地" in second.body  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 紧急模式（issue 12）

class TestEmergencyRoute:
    def test_emergency_query_enters_red_mode_under_2s(self, server):
        start = time.monotonic()
        resp = get(server, f"/query?q={quote('被跟踪了')}")
        elapsed = time.monotonic() - start
        assert resp.status == 200
        assert elapsed < 2.0  # spec：检测到紧急输入后 <2s 进入（UX-006）
        body = resp.body  # type: ignore[attr-defined]
        assert "theme-emergency" in body  # 红色极简紧急主题
        assert 'href="tel:911"' in body
        assert "I need help. Can I have a Chinese interpreter?" in body
        assert "保持冷静" in body or "提供以下信息" in body  # 信息准备清单

    def test_emergency_page_full_content(self, server):
        resp = get(server, f"/query?q={quote('有人跟踪我，在上东区')}")
        body = resp.body  # type: ignore[attr-defined]
        # 按警区安全场所清单（便利店/医院/警局）与 311 协助电话均可读/可点击
        assert "tel:911" in body and "tel:311" in body
        assert "NYPD 19th Precinct" in body
        # 无定位能力：页面文案不得出现暗示定位的词
        for word in ("最近", "离你最近"):
            assert word not in body
        # 紧急页保持极简：无画像侧边栏
        assert 'action="/profile"' not in body

    def test_emergency_without_area_uses_generic_list(self, server):
        resp = get(server, f"/query?q={quote('救命')}")
        body = resp.body  # type: ignore[attr-defined]
        assert "311" in body  # 通用清单：911/311 + 五警局


# ---------------------------------------------------------------- 画像侧边栏（issue 12）

_FORM_BODY = "gender=%E5%A5%B3%E7%94%9F&identity=%E7%95%99%E5%AD%A6%E7%94%9F&scene=%E5%B8%A6%E5%A8%83&scene=%E6%99%9A%E5%BD%92"
# gender=女生&identity=留学生&scene=带娃&scene=晚归（urlencoded UTF-8，避免测试文件编码歧义）


def _snapshot_tree(*roots: Path) -> dict:
    state: dict = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                st = path.stat()
                state[str(path)] = (st.st_mtime_ns, st.st_size)
    return state


class TestProfileRoute:
    def test_post_profile_redirects_and_sets_cookie(self, server):
        resp = post(server, "/profile", body=_FORM_BODY)
        assert resp.status == 303  # PRG：See Other 重定向回页面
        assert resp.getheader("Location") == "/"
        set_cookie = resp.getheader("Set-Cookie")
        assert set_cookie is not None and "safepass_sid=" in set_cookie

    def test_profile_prefilled_on_next_page_view(self, server):
        resp = post(server, "/profile", body=_FORM_BODY)
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        home = get(server, "/", cookie=cookie)
        assert 'value="女生" selected' in home.body  # type: ignore[attr-defined]
        assert 'value="留学生" selected' in home.body  # type: ignore[attr-defined]
        assert 'value="带娃" checked' in home.body  # type: ignore[attr-defined]
        assert 'value="晚归" checked' in home.body  # type: ignore[attr-defined]
        # 隐私声明随表单可见（AC-023）
        assert "画像仅在本次会话生效，关闭页面即删除" in home.body  # type: ignore[attr-defined]

    def test_profile_zero_persistence_new_session_sees_empty_form(self, server):
        # 可观测断言①：画像只写进程内会话——新会话（无 cookie）表单为空
        resp = post(server, "/profile", body=_FORM_BODY)
        assert resp.status == 303
        fresh = get(server, "/")
        assert " selected" not in fresh.body  # type: ignore[attr-defined]
        assert " checked" not in fresh.body  # type: ignore[attr-defined]

    def test_profile_zero_persistence_no_disk_write(self, server):
        # 可观测断言②：POST /profile 全程 config/fixtures/cassette 目录逐字节不变
        watched = (REPO_ROOT / "config", REPO_ROOT / "fixtures", REPO_ROOT / "tests" / "cassettes")
        before = _snapshot_tree(*watched)
        post(server, "/profile", body=_FORM_BODY)
        assert _snapshot_tree(*watched) == before

    def test_profile_changes_suggestions_not_rating(self, server):
        # 画像消费（spec D5）：建议层个性化排序前置；评级展示与无画像完全一致
        resp = post(server, "/profile", body=_FORM_BODY)
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        with_profile = get(server, f"/query?q={quote('上东区')}", cookie=cookie)
        plain = get(server, f"/query?q={quote('上东区')}")
        for marker in ("🟢", "相对安全"):
            assert marker in with_profile.body  # type: ignore[attr-defined]
            assert marker in plain.body  # type: ignore[attr-defined]
        # 带娃画像 → 个性化建议排序前置（来自配置 crowd_suggestions）
        assert "带娃出行优先选择商场与主街照明好的路段" in with_profile.body  # type: ignore[attr-defined]
        # 未填画像 → 全部查询照常可用（零门槛）
        assert "🟢" in plain.body  # type: ignore[attr-defined]

    def test_clear_profile_empties_session(self, server):
        resp = post(server, "/profile", body=_FORM_BODY)
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        cleared = post(server, "/profile/clear", cookie=cookie)
        assert cleared.status == 303
        home = get(server, "/", cookie=cookie)
        assert " selected" not in home.body  # type: ignore[attr-defined]
        assert " checked" not in home.body  # type: ignore[attr-defined]

    def test_pin_in_query_crowd_offered_then_fixed(self, server):
        # 查询文本内画像信息：当次提示「可固定到侧边栏」，评级展示不变
        hinted = get(server, f"/query?q={quote('我是女生，上东区晚上安全吗')}")
        assert "pin-hint" in hinted.body  # type: ignore[attr-defined]
        assert "可固定到侧边栏" in hinted.body  # type: ignore[attr-defined]
        plain = get(server, f"/query?q={quote('上东区晚上安全吗')}")
        for marker in ("🟢", "相对安全"):
            assert marker in hinted.body  # type: ignore[attr-defined]
            assert marker in plain.body  # type: ignore[attr-defined]

        # 固定（POST /profile add_scene）→ 后续查询不再提示，侧边栏回填
        resp = post(server, "/profile", body="add_scene=%E5%A5%B3%E7%94%9F")  # add_scene=女生
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        followup = get(server, f"/query?q={quote('上东区晚上安全吗')}", cookie=cookie)
        assert "pin-hint" not in followup.body  # type: ignore[attr-defined]
        home = get(server, "/", cookie=cookie)
        assert 'value="女生" checked' in home.body  # type: ignore[attr-defined]

    def test_pin_preserves_other_profile_fields(self, server):
        # 一键固定是合并而非覆盖：既有画像维度与场景标签全部保留
        resp = post(server, "/profile", body=_FORM_BODY)
        cookie = resp.getheader("Set-Cookie").split(";")[0]
        post(server, "/profile", body="add_scene=%E5%A5%B3%E7%94%9F", cookie=cookie)  # add_scene=女生
        home = get(server, "/", cookie=cookie)
        assert 'value="女生" selected' in home.body  # type: ignore[attr-defined]
        assert 'value="留学生" selected' in home.body  # type: ignore[attr-defined]
        assert 'value="带娃" checked' in home.body  # type: ignore[attr-defined]
        assert 'value="晚归" checked' in home.body  # type: ignore[attr-defined]
        assert 'value="女生" checked' in home.body  # type: ignore[attr-defined]

    def test_profile_redirect_honors_same_host_referer(self, server):
        # PRG 回跳：来源是本站结果页时回到原页（保住查询上下文）
        host = server.server_address[0]
        port = server.server_address[1]
        referer = f"http://{host}:{port}/query?q={quote('上东区')}"
        resp = post(server, "/profile", body=_FORM_BODY, referer=referer)
        assert resp.getheader("Location") == f"/query?q={quote('上东区')}"

    def test_profile_redirect_rejects_external_referer(self, server):
        # 开放重定向防线：外站 Referer 一律回首页
        resp = post(
            server,
            "/profile",
            body=_FORM_BODY,
            referer="https://evil.example.org/phish",
        )
        assert resp.getheader("Location") == "/"


# ---------------------------------------------------------------- 隐私页 + 免责页（票 08）

class TestLegalPages:
    def test_privacy_route_200_and_defense_wording(self, server):
        resp = get(server, "/privacy")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "画像仅在本次会话生效，关闭页面即删除" in body
        assert "评级" in body  # ADR-0002 口径披露

    def test_disclaimer_route_200_with_data_and_emergency(self, server):
        resp = get(server, "/disclaimer")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "本分析仅供参考，不替代专业安保建议。" in body
        assert "911" in body and "311" in body
        # 通用安全场所清单（五警局静态表）逐字段透出
        assert "NYPD" in body

    def test_legal_pages_write_nothing_to_disk(self, server):
        # 公开页面是纯渲染：config/fixtures/cassette 目录逐字节不变
        watched = (REPO_ROOT / "config", REPO_ROOT / "fixtures", REPO_ROOT / "tests" / "cassettes")
        before = _snapshot_tree(*watched)
        get(server, "/privacy")
        get(server, "/disclaimer")
        assert _snapshot_tree(*watched) == before
