"""票 07 / D2 追问芯片测试：能力可发现（S7）+ 契约类型符合预期（DoD）。

芯片 = 预填 follow_up 查询链接（`/query?q=…`，P6 定案 2：复用既有查询路由
与会话承接链路，零新增后端路由）；文案只用金标已覆盖的追问形态（P6 定案 1：
细节「{人群}{时间}呢？」= G19-G24 同款，对比「和{区域}比呢？」= G14/G17 同款），
标记与区域词全部来自集中配置——本文件用两把锁钉住 P6：
    ① 芯片文案与金标 fixture 的形态对账（细节逐字命中；对比同模板换区域词）；
    ② 芯片文案经 followup.classify 必判 KIND_DETAIL / KIND_COMPARISON
      （构造上保证"点了就是合法追问"，不发明后端分类不动的查询类型）。

集成测试与金标同一注入模式（test_golden_set._RouteStub 先例）：首轮直查走
无 LLM 确定性路径，芯片点击轮注入固定 follow_up 路由 stub——追问轮的三维
提取/建议在管线内已降为确定性 fallback，stub 每轮只消费一次路由调用。
紧急页无芯片（保持极简）；无会话点芯片 → 诚实降级（红线 4）。
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pytest

from frontend import app, render
from safepass import addressing, config_loader, contracts, followup, routing
from safepass.llm_client import ChatResponse
from safepass.pipeline import execute_query
from safepass.session_state import SessionState

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "fixtures" / "eval" / "golden_set_v1.json"
CSS = (REPO_ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")

CFG = config_loader.get_config()

BASE_QUERY = "上东区晚上安全吗？"

_CHIP_HREF = re.compile(r'class="chip" href="([^"]+)"')


def _chip_hrefs(body: str) -> list[str]:
    return _CHIP_HREF.findall(body)


def _chip_texts(body: str) -> list[str]:
    """页面里全部芯片的预填查询文本（顺序 = 渲染顺序：细节在前、对比在后）。"""
    return [
        parse_qs(urlparse(unescape(href)).query)["q"][0]
        for href in _chip_hrefs(body)
    ]


def _index_of(html: str, marker: str) -> int:
    """层级断言辅助（test_d1_first_screen 同款）：marker 恰好出现一次。"""
    assert html.count(marker) == 1, f"marker 应恰好出现一次：{marker!r}（实际 {html.count(marker)} 次）"
    return html.index(marker)


@pytest.fixture()
def uptown_result() -> contracts.SafetyQueryResult:
    result = execute_query(BASE_QUERY)
    assert isinstance(result, contracts.SafetyQueryResult)
    return result


# ---------------------------------------------------------------------------
# 1. 渲染级：芯片区块存在、文案来自配置、位置不破首屏五槽带
# ---------------------------------------------------------------------------


class TestChipRendering:
    def test_safety_page_renders_detail_and_comparison_chips(self, uptown_result):
        html = render.render_safety(uptown_result, CFG)
        assert 'class="chips"' in html
        assert html.count('class="chip"') == 2, "细节 + 对比各一枚芯片"
        # 票面示例文案：细节「女生晚上呢？」、对比「和法拉盛比呢？」（19 区首个
        # 非本区规范名 = 法拉盛，顺序来自配置别名表）
        assert 'href="/query?q=女生晚上呢？"' in html
        assert 'href="/query?q=和法拉盛比呢？"' in html

    def test_comparison_chip_never_targets_current_area(self):
        result = execute_query("法拉盛安全吗")
        html = render.render_safety(result, CFG)
        assert "和上东区比呢？" in html
        assert "和法拉盛比呢？" not in html, "不得拿本区和本区比"

    def test_detail_chip_adapts_to_profile_crowd(self, uptown_result):
        # 画像人群词自适应（金标同款形态：G20 留学生 / G24 带娃 / G21 一个人）
        for profile, expected in (
            ({"gender": "男生"}, "男生晚上呢？"),
            ({"identity": "留学生"}, "留学生晚上呢？"),
            ({"scene": ["带娃"]}, "带娃晚上呢？"),
            ({"gender": "女生", "identity": "留学生"}, "女生晚上呢？"),  # gender 优先
        ):
            html = render.render_safety(uptown_result, CFG, profile=profile)
            assert expected in html, f"profile={profile} 应产出芯片 {expected}"

    def test_detail_chip_falls_back_when_profile_not_a_marker(self, uptown_result):
        # 画像值不在配置标记表 → 回退默认人群词（不发明后端分类不动的文案）
        html = render.render_safety(
            uptown_result, CFG, profile={"gender": "不愿透露", "identity": "上班族"}
        )
        assert "女生晚上呢？" in html

    def test_chips_sit_after_five_slot_band_before_collapsed_details(self, uptown_result):
        # S7 次级行动不插进 D1 首屏五槽带：紧急资源之后、折叠细节（charts）之前
        # （真实接缝的上东区结果 dimensions 为空不渲染，charts 恒在）
        html = render.render_safety(uptown_result, CFG)
        assert _index_of(html, "紧急资源") < _index_of(html, 'class="chips"')
        assert _index_of(html, 'class="chips"') < _index_of(html, 'class="charts"')

    def test_emergency_page_renders_no_chips(self):
        html = render.render_result(execute_query("救命！有人抢劫"), CFG)
        assert "theme-emergency" in html, "前置：确认拿到的是紧急页"
        assert 'class="chip"' not in html
        assert "想继续问" not in html

    def test_non_safety_pages_render_no_chips(self):
        # 降级 / 对比 / 防线页各有自己的行动区块（重选菜单/维度表/转向清单），
        # 芯片只进安全结果页
        for query in ("哥大附近安全吗", "上东区和唐人街哪个更安全", "防身用什么比较好"):
            html = render.render_result(execute_query(query), CFG)
            assert 'class="chip"' not in html, f"{query} 的响应页不应有芯片"

    def test_chip_styles_exist(self):
        assert ".chip {" in CSS
        assert ".chip-row" in CSS
        assert "flex-wrap" in CSS[CSS.index(".chip-row") : CSS.index(".chip-row") + 200], \
            "芯片行窄屏必须可换行（无横向滚动）"


# ---------------------------------------------------------------------------
# 2. P6 锚定：文案 = 金标已覆盖形态；classify 必判合法追问
# ---------------------------------------------------------------------------


class TestChipFormsAreGoldenCovered:
    def test_chip_texts_match_golden_covered_forms(self, uptown_result):
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]
        detail_queries = {e["query"] for e in golden if e["form"] == "detail_followup"}
        comparison_queries = {e["query"] for e in golden if e["form"] == "comparison_followup"}
        detail_text, comparison_text = _chip_texts(render.render_safety(uptown_result, CFG))
        # 细节芯片逐字命中金标（G19）
        assert detail_text in detail_queries
        # 对比芯片 = 金标对比文案同一模板只换区域词（「和{区域}比呢？」，G17 同款）
        names = set(addressing.canonical_names(CFG).values())
        templates = {
            q.replace(name, "{area}")
            for q in comparison_queries
            for name in names
            if name in q
        }
        chip_template = next(
            comparison_text.replace(name, "{area}")
            for name in names
            if name in comparison_text
        )
        assert chip_template in templates

    def test_chips_classify_as_legal_followup_kinds_for_every_covered_area(self):
        # DoD 的构造性保证：任何覆盖区结果页的芯片，点击文本经 followup.classify
        # 必判细节追问 / 对比追问（绝不产出 topic_shift 的"死芯片"）
        for name in addressing.canonical_names(CFG).values():
            result = execute_query(name)
            assert isinstance(result, contracts.SafetyQueryResult)
            state = SessionState.from_result(result)
            detail_text, comparison_text = _chip_texts(render.render_safety(result, CFG))
            detail_plan = followup.classify(
                detail_text, addressing.resolve_areas(detail_text, CFG), state, CFG
            )
            assert detail_plan.kind == followup.KIND_DETAIL, f"{name} 细节芯片"
            comparison_plan = followup.classify(
                comparison_text, addressing.resolve_areas(comparison_text, CFG), state, CFG
            )
            assert comparison_plan.kind == followup.KIND_COMPARISON, f"{name} 对比芯片"
            assert comparison_plan.target is not None
            assert comparison_plan.target.precincts[0] != result.precinct


# ---------------------------------------------------------------------------
# 3. 集成级（HTTP）：点击芯片 → 契约类型符合预期（DoD）
# ---------------------------------------------------------------------------


class _RouteStub:
    """固定路由 stub（test_golden_set._RouteStub 同一注入模式，零 LLM）：
    模拟 FC 把追问轮路由到 follow_up；只被路由消费一次（管线内追问轮的
    三维提取/建议已降为确定性 fallback）。"""

    def __init__(self, route: str):
        self.route = route
        self.calls = 0

    def chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        return ChatResponse(
            content=json.dumps(
                {"route": self.route, "degraded_capability": None}, ensure_ascii=False
            )
        )


def _serve(store: app.SessionStore, llm_client=None):
    srv = app.create_server(port=0, store=store, llm_client=llm_client)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


def _get(srv, path: str, cookie: str | None = None) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(srv.server_address[0], srv.server_address[1], timeout=60)
    headers = {"Cookie": cookie} if cookie else {}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    resp.body = resp.read().decode("utf-8")  # type: ignore[attr-defined]
    conn.close()
    return resp


@pytest.fixture()
def servers():
    """共享 SessionStore 的双服务：plain（无 LLM，首轮直查）+ routed
    （follow_up 路由 stub，芯片点击轮）——会话经同一 store 贯穿（cookie 载体）。"""
    store = app.SessionStore()
    stub = _RouteStub(routing.ROUTE_FOLLOW_UP)
    plain, plain_thread = _serve(store)
    routed, routed_thread = _serve(store, stub)
    yield plain, routed, stub
    for srv, thread in ((plain, plain_thread), (routed, routed_thread)):
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _first_query_with_chips(srv) -> tuple[str, list[str]]:
    resp = _get(srv, f"/query?q={quote(BASE_QUERY)}")
    assert resp.status == 200
    cookie = resp.getheader("Set-Cookie").split(";")[0]
    hrefs = _chip_hrefs(resp.body)
    assert len(hrefs) == 2, "首轮结果页应露出细节 + 对比两枚芯片"
    return cookie, [quote(href, safe="/?=") for href in hrefs]


class TestChipClickIntegration:
    def test_detail_chip_click_yields_detail_followup_contract(self, servers):
        plain, routed, stub = servers
        cookie, (detail_href, _) = _first_query_with_chips(plain)

        resp = _get(routed, detail_href, cookie=cookie)

        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        # 契约类型 = 细节追问（KIND_DETAIL 的可观测面）：地点承接上轮 +
        # 人群/时间维度叠加，仍是安全结果页（非对比视图）
        assert "上东区" in body
        assert "<strong>人群</strong>：女生" in body
        assert "<strong>时间</strong>：晚上" in body
        assert "🔀" not in body
        assert stub.calls == 1, "追问轮只消费一次路由调用（提取/建议走确定性 fallback）"

    def test_comparison_chip_click_yields_comparison_contract(self, servers):
        plain, routed, stub = servers
        cookie, (_, comparison_href) = _first_query_with_chips(plain)

        resp = _get(routed, comparison_href, cookie=cookie)

        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        # 契约类型 = 对比（ComparisonResult 的可观测面）：对比视图 + 双侧区域卡片
        assert "🔀" in body and "区域对比" in body
        assert "上东区" in body and "法拉盛" in body
        assert stub.calls == 1

    def test_chip_click_without_session_degrades_honestly(self, servers):
        # 无会话（新窗口直接打开芯片链接）：无承接对象 → 诚实降级页，不编造
        _, routed, _ = servers
        resp = _get(routed, quote("/query?q=女生晚上呢？", safe="/?="))
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "暂时无法给出完整分析" in body
        assert 'class="chip"' not in body, "降级页不再叠芯片"

    def test_emergency_page_serves_no_chips(self, servers):
        plain, _, _ = servers
        resp = _get(plain, f"/query?q={quote('被跟踪了')}")
        assert resp.status == 200
        body = resp.body  # type: ignore[attr-defined]
        assert "theme-emergency" in body, "前置：确认拿到的是紧急页"
        assert 'class="chip"' not in body
        assert "想继续问" not in body
