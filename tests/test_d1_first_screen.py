"""票 06 / D1 首屏信息架构测试：结构断言锁层级（S3 五槽 + 默认折叠）。

首屏（窄屏一屏内）只装结论与行动：
    评级槽（result-head 结论卡片）→ 人话解释槽（one-liner 区块：one_liner
    数据钩子 + 评级依据，C1 落地前的确定性拼装占位）→ 建议槽（suggestions
    常驻区块 + grounds 渲染槽）→ 紧急资源槽，五槽连排（pin-hint 查询语境
    提示排五槽带之后，不插进槽位序列）；
    图表 / community / 来源默认折叠（details 不挂 open）；dimensions /
    unknowns 同样折叠（⚪ 数据不足时 unknowns 例外展开——「为什么没评级」
    本身就是结论）；降级横幅首屏可见（header 之后、建议之前）。

层级断言 = index 顺序 + details 开合状态（快照式结构锁，不逐字锁全文——
C1 / A4 波 2 换内容时结构不漂）。
"""

from __future__ import annotations

from pathlib import Path

from safepass import config_loader, contracts
from frontend import render

CFG = config_loader.get_config()

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS = (REPO_ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")

NOTICE = "今日 AI 生成预算已用尽，本回复改由确定性数据与模板生成；安全评级与统计数据不受影响。"


def make_safety(**overrides) -> contracts.SafetyQueryResult:
    base = dict(
        area="上东区", precinct=19, rating="green",
        rating_explainable_basis=0.62, confidence_tier="HIGH", sample_size=312,
        one_liner="上东区：相对安全",
        extracted=contracts.ExtractedDimensions(area="上东区", crowd=None, time=None),
        dimensions=[{"dimension": "夜间风险", "value": "22:00 后建议走主干道"}],
        suggestions=[
            "夜间出行尽量结伴，并提前告知朋友行程",
            "随身包放在身前视线范围内，手机握在手里",
            "优先选择照明好、人流多的主干道通行",
        ],
        unknowns=[],
        sources=["NYPD 公开数据（模拟）"],
        time_range="2024-01-01 至 2025-01-01",
        charts=contracts.Charts(
            top5_types=[
                contracts.OffenseCount(offense_type="盗窃", count=120),
                contracts.OffenseCount(offense_type="抢劫", count=45),
            ],
            day_night=contracts.DayNight(day=200, night=112),
        ),
        community_info={
            "hate_crime": "有公开记录的仇恨犯罪事件",
            "scam_alerts": ["假冒公检法诈骗"],
            "chinese_officer": "未核实到",
            "community_resources": [
                {"name": "华人社区中心", "source": "https://example.org"}
            ],
            "sources": ["https://example.org/overview"],
        },
        emergency_resources=[
            contracts.Venue(
                type="police", name="19th Precinct", name_zh="第19警局",
                address="153 E 67th St", phone="212-452-0600",
                source="nypd.gov", verified=True,
            )
        ],
        profile_notice="画像仅在本次会话生效，关闭页面即删除",
        disclaimer="本分析仅供参考，不替代专业安保建议。",
    )
    base.update(overrides)
    return contracts.SafetyQueryResult(**base)


def _index_of(html: str, marker: str) -> int:
    """层级断言辅助：marker 必须恰好存在一次（防拼写漂移的静默通过）。"""
    assert html.count(marker) == 1, f"marker 应恰好出现一次：{marker!r}（实际 {html.count(marker)} 次）"
    return html.index(marker)


class TestFirstScreenHierarchy:
    """首屏五槽顺序与折叠态（层级锁，S3 槽位稳定）。"""

    def test_first_screen_slot_order(self):
        html = render.render_result(make_safety(), CFG)
        order = [
            _index_of(html, 'class="result-head'),  # 1 评级（结论档）
            _index_of(html, 'class="one-liner"'),  # 2 人话解释（占位拼装）
            _index_of(html, 'class="suggestions"'),  # 3 建议（含 grounds 槽）
            _index_of(html, "紧急资源"),  # 4 紧急资源
            _index_of(html, 'class="dimensions"'),  # 折叠细节层
            _index_of(html, 'class="charts"'),
            _index_of(html, 'class="community"'),
            _index_of(html, 'class="sources"'),
        ]
        assert order == sorted(order), "首屏五槽必须领先于全部折叠细节"

    def test_charts_community_sources_dimensions_collapsed_by_default(self):
        html = render.render_result(make_safety(), CFG)
        for cls in ("charts", "community", "sources", "dimensions"):
            assert f'<details class="{cls}">' in html, f"{cls} 应为折叠容器"
            assert f'<details class="{cls}" open' not in html, f"{cls} 默认不得展开"

    def test_suggestions_always_visible_not_in_details(self):
        html = render.render_result(make_safety(), CFG)
        assert '<section class="suggestions">' in html
        assert html.count("✅") == 3

    def test_emergency_resources_before_collapsed_details(self):
        html = render.render_result(make_safety(), CFG)
        assert _index_of(html, "紧急资源") < _index_of(html, 'class="dimensions"')

    def test_pin_hint_never_breaks_five_slot_band(self):
        # 查询语境提示（pin-hint）排在五槽带之后：即使 query 带人群信息，
        # 评级→人话解释→建议→紧急资源 的槽位序列不被插入物打断（S3 槽位稳定）
        result = make_safety(
            extracted=contracts.ExtractedDimensions(area="上东区", crowd="女生", time=None),
        )
        html = render.render_result(result, CFG)
        assert "pin-hint" in html
        assert _index_of(html, "紧急资源") < _index_of(html, "pin-hint")
        assert _index_of(html, "pin-hint") < _index_of(html, 'class="dimensions"')

    def test_unknowns_open_when_insufficient_data(self):
        # ⚪（数据不足）时「为什么没有评级」本身就是结论：默认展开
        result = make_safety(
            rating="insufficient_data", rating_explainable_basis=None,
            confidence_tier=None, sample_size=6, charts=None,
            unknowns=["该区域过去 12 个月的有效记录过少，暂不足以给出可靠评级。"],
        )
        html = render.render_result(result, CFG)
        assert '<details class="unknowns" open>' in html

    def test_unknowns_collapsed_when_rated(self):
        html = render.render_result(make_safety(unknowns=["补充说明"]), CFG)
        assert '<details class="unknowns">' in html
        assert '<details class="unknowns" open>' not in html

    def test_rating_explanation_assembly_in_one_liner_slot(self):
        # 人话解释占位 = one_liner + 评级依据同区块（C1 波 2 换真 rating_rationale）；
        # 倍数保留一位小数，与 one_liner city_relative 钩子同精度（不打架）
        html = render.render_result(make_safety(rating_explainable_basis=0.62), CFG)
        block = html[
            _index_of(html, 'class="one-liner"') :
            html.index("</section>", _index_of(html, 'class="one-liner"'))
        ]
        assert "一句话总结" in block
        assert "0.6" in block and "市均值" in block
        assert "0.62" not in block

    def test_degraded_banner_first_screen_between_rating_and_suggestions(self):
        result = make_safety(llm_degraded=True, degradation_notice=NOTICE)
        html = render.render_result(result, CFG)
        header_end = html.index("</header>")
        assert header_end < _index_of(html, "llm-degraded-banner")
        assert _index_of(html, "llm-degraded-banner") < _index_of(html, 'class="suggestions"')
        assert _index_of(html, "llm-degraded-banner") < _index_of(html, 'class="dimensions"')


class TestSuggestionGroundsSlot:
    """grounds 渲染槽（P6 定案 3 + 票 01 / A4）：建议区固定槽位；有依据小号
    「建议依据」+ 列表级引文；无依据标「通用建议」、不装成有出处。"""

    def test_slot_rendered_when_grounds_present(self):
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(
                    doc_id="p19_scam_01", quote="近期冒充公检法诈骗高发"
                ),
            ],
        )
        html = render.render_result(result, CFG)
        assert 'class="suggestion-grounds"' in html
        assert "近期冒充公检法诈骗高发" in html
        assert 'data-doc-id="p19_scam_01"' in html  # A8 溯源锚点
        # 槽位在建议区块内部（先于紧急资源）
        assert _index_of(html, 'class="suggestion-grounds"') < _index_of(html, "紧急资源")

    def test_grounds_heading_when_present(self):
        # 有依据 ↔ 无依据在 HTML 上可分：非空加小号标题「建议依据」，
        # 且与首屏「评级依据」用词分开（CONTEXT 建议依据 ≠ 评级依据）
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(
                    doc_id="p19_scam", quote="近期冒充公检法诈骗高发"
                ),
            ],
        )
        html = render.render_result(result, CFG)
        assert _index_of(html, "建议依据") < _index_of(html, "近期冒充公检法诈骗高发")
        assert "评级依据" in html
        assert "通用建议" not in html
        assert 'class="generic-suggestion-label"' not in html
        grounds_block = html[
            _index_of(html, 'class="suggestion-grounds"') :
            html.index("</div>", _index_of(html, 'class="suggestion-grounds"'))
        ]
        assert "建议依据" in grounds_block
        assert "ground-quote" in grounds_block

    def test_grounds_are_list_level_not_per_suggestion(self):
        # 契约是整份结果上的列表：一块依据槽，禁止一条建议一条依据
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(doc_id="p19_scam", quote="使领馆不会电话要求转账"),
                contracts.SuggestionGround(doc_id="p19_overview", quote="夜间独行尽量结伴"),
            ],
        )
        html = render.render_result(result, CFG)
        assert html.count('class="suggestion-grounds"') == 1
        assert html.count("建议依据") == 1
        assert html.count('class="ground-quote"') == 2
        ul_end = html.index("</ul>", _index_of(html, 'class="suggestions"'))
        assert ul_end < _index_of(html, 'class="suggestion-grounds"')

    def test_grounds_block_does_not_copy_chart_stats(self):
        # 不把 Top 罪名/昼夜比抄到建议依据下（图表槽的职责）
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(
                    doc_id="p19_scam", quote="使领馆不会电话要求转账"
                ),
            ],
        )
        html = render.render_result(result, CFG)
        start = _index_of(html, 'class="suggestion-grounds"')
        block = html[start : html.index("</div>", start)]
        assert "盗窃" not in block
        assert "抢劫" not in block
        assert "200" not in block and "112" not in block

    def test_ground_quote_found_in_knowledge_fixture(self):
        # DoD：有依据时引文可在夹具文档中找到（页面不是装饰性引用）
        quote = "使领馆不会电话要求转账"
        doc = (REPO_ROOT / "fixtures" / "knowledge" / "p19_scam.md").read_text(
            encoding="utf-8"
        )
        assert quote in doc
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(doc_id="p19_scam", quote=quote),
            ],
        )
        html = render.render_result(result, CFG)
        assert quote in html
        assert 'data-doc-id="p19_scam"' in html

    def test_slot_absent_when_no_grounds(self):
        # 无依据不装成有依据（S1）：不渲染引用槽，建议区标明「通用建议」
        html = render.render_result(make_safety(), CFG)
        assert "suggestion-grounds" not in html
        assert "ground-quote" not in html
        assert "建议依据" not in html
        assert _index_of(html, 'class="generic-suggestion-label"') < _index_of(
            html, "紧急资源"
        )
        assert "通用建议" in html
        assert "评级依据" in html

    def test_ground_quote_html_escaped(self):
        result = make_safety(
            suggestions_source="skill",
            suggestion_grounds=[
                contracts.SuggestionGround(
                    doc_id="p19_x", quote="<script>alert(1)</script>"
                ),
            ],
        )
        html = render.render_result(result, CFG)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestDegradedGeneralSuggestionsSemantics:
    """越界页已有「通用建议」= 无本区数据；A4 不改该语义。"""

    def test_out_of_coverage_keeps_details_summary_label(self):
        html = render.render_degraded(
            contracts.DegradedResult(
                degraded_capability="out_of_coverage",
                message="该区域不在数据覆盖范围内",
                alternative_info=None,
                reselection_invitation="请从覆盖区域中重新选择",
                general_suggestions=["夜间出行尽量结伴，并提前告知朋友行程"],
                emergency_resources=[],
                disclaimer="本分析仅供参考，不替代专业安保建议。",
                sources=[],
            ),
            CFG,
        )
        assert '<details class="suggestions" open>' in html
        assert "<summary>💡 通用建议</summary>" in html
        assert "suggestion-grounds" not in html
        assert "建议依据" not in html
        assert 'class="generic-suggestion-label"' not in html


class TestFirstScreenCss:
    """首屏样式结构层：五槽卡片/依据槽样式存在，窄屏媒体查询收紧首屏间距。"""

    def test_conclusion_card_and_grounds_styles_exist(self):
        # 结论卡片经 hero 修饰类作用，只改安全结果页首屏头（其余页不动）
        assert ".result-head.hero" in CSS
        assert ".suggestion-grounds" in CSS
        assert ".ground-quote" in CSS
        assert ".grounds-heading" in CSS
        assert ".generic-suggestion-label" in CSS

    def test_narrow_screen_tightens_first_screen_slots(self):
        block = CSS[CSS.index("@media (max-width: 30rem)") :]
        assert ".result-head.hero, section, details" in block  # 首屏间距收紧
        assert ".result-head.hero h1" in block
        assert ".suggestions li" in block
