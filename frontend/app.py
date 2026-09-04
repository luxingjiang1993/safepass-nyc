"""前端 HTTP 薄服务层（issue 11 + issue 12）：stdlib http.server，零新增依赖。

路由只有五条，全部薄胶水、零业务逻辑：
    GET  /                   → render.render_home（五个核心警区快速查询按钮 + 画像侧边栏）
    GET  /query?q=...        → safepass.pipeline.execute_query 唯一接缝（spec D1）
                               → render.render_result 渲染判别联合
    GET  /static/style.css   → 静态样式
    POST /profile            → 画像表单写入会话（进程内 SessionStore，PRG 303）
    POST /profile/clear      → 清除会话画像（PRG 303）

会话载体（spec D2/D6）：cookie `safepass_sid` + 进程内 SessionStore 保存上轮
结构化结果（SessionState，不存对话历史）与会话画像（spec D5，六维表单字典）。
响应后可承接（Safety/Comparison）→ from_result 重建；降级/紧急 → from_result
抛 TypeError → 清空。会话随服务进程消失，零持久化（画像/会话数据的落盘防线
不变：tests/test_frontend_app.py 有目录逐字节快照断言）。

画像提交只写入进程内会话字典，没有任何磁盘写入或外部上传请求；关闭页面
（丢弃 cookie）即删除。查询路由把会话画像作为 execute_query 的 profile
参数透传——画像只作用于建议排序与时间提示（ADR-0002），永不进入评级。

本层默认不注入 llm_client（llm_client=None）：走确定性路径（静态意图标记 +
D12 后置 + 区域解析），离线可跑；生产 LLM 接入属后续切片。
"""

from __future__ import annotations

import secrets
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, parse_qs, urlparse

from safepass import config_loader, pipeline
from safepass.session_state import SessionState
from frontend import render

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_COOKIE_NAME = "safepass_sid"

# 画像表单的普通维度（单值下拉）；scene 为标签多选，单独处理
_PROFILE_FIELDS = ("gender", "age", "identity", "english", "duration")


class SessionStore:
    """进程内会话状态载体：sid → 上轮结构化结果 + 会话画像（零持久化）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, SessionState] = {}
        self._profiles: dict[str, dict[str, Any]] = {}

    def get(self, sid: str) -> SessionState | None:
        with self._lock:
            return self._states.get(sid)

    def put(self, sid: str, state: SessionState) -> None:
        with self._lock:
            self._states[sid] = state

    def clear(self, sid: str) -> None:
        with self._lock:
            self._states.pop(sid, None)

    def adopt_result(self, sid: str, result: object) -> None:
        """以新响应重建会话状态；降级/紧急形态不含可承接区域结果 → 清空（from_result 契约）。"""
        try:
            self.put(sid, SessionState.from_result(result))  # type: ignore[arg-type]
        except TypeError:
            self.clear(sid)

    # -- 会话画像（spec D5：仅本次会话生效，关闭页面即删除） --------------
    def get_profile(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            return self._profiles.get(sid)

    def put_profile(self, sid: str, profile: dict[str, Any]) -> None:
        with self._lock:
            if profile:
                self._profiles[sid] = profile
            else:
                self._profiles.pop(sid, None)  # 空画像等价于未填写（零门槛）

    def clear_profile(self, sid: str) -> None:
        # 不加锁直接委托：put_profile 自带锁且空画像即弹出（Lock 非可重入）
        self.put_profile(sid, {})

    def pin_scene(self, sid: str, tag: str) -> None:
        """查询内人群信息一键固定（issue 12）：合并进既有画像的场景标签，
        不覆盖用户已填的其他维度。"""
        if not tag.strip():
            return
        with self._lock:
            profile = dict(self._profiles.get(sid) or {})
            scene = list(profile.get("scene") or [])
            if tag not in scene:
                scene.append(tag)
            profile["scene"] = scene
            self._profiles[sid] = profile


def _new_sid() -> str:
    return secrets.token_urlsafe(16)


def _form_profile(fields: dict[str, list[str]]) -> dict[str, Any]:
    """urlencoded 表单 → 会话画像字典：空值丢弃，scene 多选收为列表。"""
    profile: dict[str, Any] = {}
    for key in _PROFILE_FIELDS:
        value = fields.get(key, [""])[0].strip()
        if value:
            profile[key] = value
    scene = [tag.strip() for tag in fields.get("scene", []) if tag.strip()]
    if scene:
        profile["scene"] = scene
    return profile


def make_handler(store: SessionStore | None = None):
    """构造请求处理类（store 可注入，便于测试与多实例隔离）。"""
    sessions = store if store is not None else SessionStore()

    class SafePassHandler(BaseHTTPRequestHandler):
        server_version = "SafePassFrontend/0.2"

        def log_message(self, format: str, *args: object) -> None:  # 静音默认访问日志
            pass

        # -- 响应辅助 --------------------------------------------------
        def _send(
            self,
            payload: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
            set_cookie: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.end_headers()
            self.wfile.write(payload)

        def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK, set_cookie: str | None = None) -> None:
            self._send(body.encode("utf-8"), "text/html; charset=utf-8", status, set_cookie)

        def _send_css(self) -> None:
            self._send((_STATIC_DIR / "style.css").read_bytes(), "text/css; charset=utf-8")

        def _send_redirect(self, location: str, set_cookie: str | None = None) -> None:
            """PRG：303 See Other 重定向，表单提交后回到页面视图。"""
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _sid_from_cookie(self) -> str | None:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            cookie = SimpleCookie(raw)
            morsel = cookie.get(_COOKIE_NAME)
            return morsel.value if morsel else None

        def _cookie_for(self, sid: str) -> str:
            return f"{_COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Lax"

        def _read_form(self) -> dict[str, list[str]]:
            """读取 urlencoded 表单体（长度受限，防御异常请求）。"""
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            except ValueError:
                length = 0
            body = self.rfile.read(length).decode("utf-8") if length else ""
            return parse_qs(body, keep_blank_values=True)

        # -- 路由 ------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802（stdlib 命名）
            parsed = urlparse(self.path)
            if parsed.path == "/":
                sid = self._sid_from_cookie()
                profile = sessions.get_profile(sid) if sid else None
                self._send_html(render.render_home(config_loader.get_config(), profile))
                return
            if parsed.path == "/static/style.css":
                self._send_css()
                return
            if parsed.path == "/query":
                self._handle_query(parsed)
                return
            self._send_html("Not Found", HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802（stdlib 命名）
            parsed = urlparse(self.path)
            if parsed.path == "/profile":
                self._handle_profile()
                return
            if parsed.path == "/profile/clear":
                self._handle_profile_clear()
                return
            self._send_html("Not Found", HTTPStatus.NOT_FOUND)

        def _redirect_target(self) -> str:
            """PRG 回跳目标：优先回到来源页（同主机、站内路径），否则首页。

            固定提示从结果页触发——回到原结果页保住上下文；仅信任与 Host
            头一致的 Referer，杜绝开放重定向。
            """
            referer = self.headers.get("Referer")
            if referer:
                parsed_ref = urlparse(referer)
                if parsed_ref.netloc == self.headers.get("Host") and parsed_ref.path.startswith("/"):
                    query = f"?{parsed_ref.query}" if parsed_ref.query else ""
                    return parsed_ref.path + query
            return "/"

        # -- 画像提交（零持久化：只写进程内会话字典） -------------------
        def _handle_profile(self) -> None:
            fields = self._read_form()
            sid = self._sid_from_cookie() or _new_sid()
            add_scene = fields.get("add_scene", [""])[0].strip()
            if add_scene:
                # 一键固定：合并进既有画像，保留用户已填维度
                sessions.pin_scene(sid, add_scene)
            else:
                sessions.put_profile(sid, _form_profile(fields))
            self._send_redirect(self._redirect_target(), set_cookie=self._cookie_for(sid))

        def _handle_profile_clear(self) -> None:
            sid = self._sid_from_cookie()
            if sid:
                sessions.clear_profile(sid)
            self._send_redirect("/")

        # -- 查询 ------------------------------------------------------
        def _handle_query(self, parsed: ParseResult) -> None:
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            if not query:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/")
                self.end_headers()
                return
            sid = self._sid_from_cookie() or _new_sid()
            result = pipeline.execute_query(
                query,
                profile=sessions.get_profile(sid),
                session_state=sessions.get(sid),
                llm_client=None,  # 确定性路径：静态意图标记 + D12 后置（离线可跑）
            )
            sessions.adopt_result(sid, result)
            self._send_html(
                render.render_result(
                    result, config_loader.get_config(), sessions.get_profile(sid)
                ),
                set_cookie=self._cookie_for(sid),
            )

    return SafePassHandler


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    store: SessionStore | None = None,
) -> ThreadingHTTPServer:
    """创建线程化 HTTP 服务（port=0 由系统分配端口，测试用）。"""
    return ThreadingHTTPServer((host, port), make_handler(store))


def main() -> None:
    server = create_server()
    host, port = server.server_address
    print(f"SafePass NYC 前端：http://{host}:{port}（Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
