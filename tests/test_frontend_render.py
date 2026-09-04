"""前端渲染层测试（issue 11，TDD 先红）。

渲染层是纯函数接缝：结构化响应契约 → HTML 字符串。断言全部是结构层：
    首页：五个快速查询按钮（零输入出查询链接）、免责页脚
    安全结果：评级图标与文字并存、可信度星级与动态样本量文案（AC-009）、
        一句话总结、3-5 条建议、🤷 unknowns 区域、图表数字与契约逐字段一致（AC-022）、
        ⚪ 时图表模块整体隐藏、评级可解释依据、数据来源与覆盖时间、免责声明（AC-010）
    对比/降级：按 ComparisonResult / DegradedResult 契约逐字段渲染
    横切：HTML 转义、viewport meta（窄屏结构层）、dispatcher 类型完备

UX 主观项（语气温暖/可信度感知/窄屏实机/无障碍抽验）转人工验收清单，不在本文件。
"""

from __future__ import annotations

import pytest

from safepass import config_loader, contracts
from safepass.degraded import RATING_LABELS
from frontend import render

CFG = config_loader.get_config()

FIVE_AREAS = ["上东区", "法拉盛", "唐人街", "威廉斯堡", "布鲁克林高地"]

VENUE = contracts.Venue(
    type="police", name="19th Precinct", name_zh="第19警局",
    address="153 E 67th St", phone="212-452-0600", source="nypd.gov", verified=True,
)


def make_safety(**overrides) -> contracts.SafetyQueryResult:
    base = dict(
        area="上东区", precinct=19, rating="green",
        rating_explainable_basis=0.62, confidence_tier="HIGH", sample_size=312,
        one_liner="上东区整体安全",
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
        emergency_resources=[VENUE],
        profile_notice="画像仅在本次会话生效，关闭页面即删除",
        disclaimer="本分析仅供参考，不替代专业安保建议。",
    )
    base.update(overrides)
    return contracts.SafetyQueryResult(**base)


# ---------------------------------------------------------------- 首页

class TestHome:
    def test_five_quick_query_buttons(self):
        html = render.render_home(CFG)
        for area in FIVE_AREAS:
            assert area in html
            assert f"/query?q={area}" in html

    def test_home_has_disclaimer_footer(self):
        assert CFG.disclaimer in render.render_home(CFG)

    def test_home_has_viewport_meta(self):
        assert 'name="viewport"' in render.render_home(CFG)


# ---------------------------------------------------------------- 安全结果

class TestSafetyResult:
    def test_rating_icon_and_text_side_by_side(self):
        html = render.render_result(make_safety(), CFG)
        assert "🟢" in html and "相对安全" in html

    def test_rating_labels_cover_all_four_ratings(self):
        # 表现层与后端标签表同源（degraded.RATING_LABELS），四级齐全
        for rating in ("green", "yellow", "red", "insufficient_data"):
            assert RATING_LABELS[rating]

    def test_confidence_stars_and_dynamic_sample_size(self):
        result = make_safety(confidence_tier="HIGH", sample_size=312)
        html = render.render_result(result, CFG)
        assert "⭐⭐⭐⭐⭐" in html
        assert "可信度：高" in html
        assert "312" in html
        assert "基于本次查询命中的 312 条记录" in html

    def test_moderate_tier_three_stars(self):
        result = make_safety(
            confidence_tier="MODERATE", sample_size=58, rating="yellow",
            rating_explainable_basis=1.05,
        )
        html = render.render_result(result, CFG)
        assert "⭐⭐⭐☆☆" in html and "可信度：中等" in html and "58" in html

    def test_one_liner_rendered(self):
        assert "上东区整体安全" in render.render_result(make_safety(), CFG)

    def test_rating_basis_rendered_when_present(self):
        html = render.render_result(make_safety(rating_explainable_basis=0.62), CFG)
        assert "0.62" in html and "市均值" in html

    def test_suggestions_3_to_5_rendered(self):
        html = render.render_result(make_safety(), CFG)
        assert html.count("✅") == 3

    def test_unknowns_section_rendered_when_present(self):
        result = make_safety(
            rating="insufficient_data", rating_explainable_basis=None,
            confidence_tier=None, sample_size=6,
            unknowns=["该区域过去 12 个月的有效记录过少，暂不足以给出可靠评级。"],
            charts=None,
        )
        html = render.render_result(result, CFG)
        assert "🤷" in html
        assert "记录过少" in html

    def test_charts_numbers_match_contract(self):
        html = render.render_result(make_safety(), CFG)
        assert "📈" in html
        for offense, count in (("盗窃", 120), ("抢劫", 45)):
            assert offense in html and str(count) in html
        assert "200" in html and "112" in html  # 白天/夜间

    def test_charts_module_hidden_when_insufficient(self):
        result = make_safety(
            rating="insufficient_data", rating_explainable_basis=None,
            confidence_tier=None, sample_size=6, charts=None,
            unknowns=["记录过少"],
        )
        html = render.render_result(result, CFG)
        assert "📈" not in html

    def test_disclaimer_sources_time_range_rendered(self):
        html = render.render_result(make_safety(), CFG)
        assert "本分析仅供参考，不替代专业安保建议。" in html
        assert "NYPD 公开数据（模拟）" in html
        assert "2024-01-01 至 2025-01-01" in html

    def test_emergency_resources_rendered(self):
        html = render.render_result(make_safety(), CFG)
        assert "19th Precinct" in html and "212-452-0600" in html

    def test_community_info_rendered(self):
        html = render.render_result(make_safety(), CFG)
        assert "假冒公检法诈骗" in html
        assert "未核实到" in html
        assert "https://example.org" in html

    def test_html_escaping(self):
        result = make_safety(area="<b>上东区</b>")
        html = render.render_result(result, CFG)
        assert "<b>上东区</b>" not in html
        assert "&lt;b&gt;" in html


# ---------------------------------------------------------------- 对比

def make_comparison() -> contracts.ComparisonResult:
    return contracts.ComparisonResult(
        areas=[
            contracts.AreaSummary(
                area="上东区", precinct=19, rating="green", sample_size=312,
                day_night=contracts.DayNight(day=200, night=112),
                top5_types=[contracts.OffenseCount(offense_type="盗窃", count=120)],
            ),
            contracts.AreaSummary(
                area="唐人街", precinct=5, rating="red", sample_size=488,
                day_night=contracts.DayNight(day=260, night=228),
                top5_types=[contracts.OffenseCount(offense_type="抢劫", count=97)],
            ),
        ],
        dimensions=[
            {"dimension": "overall_rating", "status": "available"},
            {"dimension": "long_term_trend", "status": "in_development"},
        ],
        decision_aid="如果你更在意整体安全评级：上东区的数据表现更好。",
        sources=["NYPD 公开数据（模拟）"],
        disclaimer="本分析仅供参考，不替代专业安保建议。",
    )


class TestComparison:
    def test_both_areas_with_ratings(self):
        html = render.render_result(make_comparison(), CFG)
        assert "上东区" in html and "🟢" in html
        assert "唐人街" in html and "🔴" in html
        assert "312" in html and "488" in html

    def test_dimension_statuses_rendered(self):
        html = render.render_result(make_comparison(), CFG)
        assert "available" in html and "in_development" in html

    def test_decision_aid_and_disclaimer(self):
        html = render.render_result(make_comparison(), CFG)
        assert "上东区的数据表现更好" in html
        assert "本分析仅供参考，不替代专业安保建议。" in html


# ---------------------------------------------------------------- 降级

def make_degraded(alternative: bool = True) -> contracts.DegradedResult:
    alt = (
        contracts.AlternativeInfo(
            precinct=19, area="上东区", rating="green", confidence="HIGH",
            sample_size=312, explanation="该警区整体治安良好",
            day_night=contracts.DayNight(day=200, night=112),
        )
        if alternative
        else None
    )
    return contracts.DegradedResult(
        degraded_capability="out_of_coverage",
        message="我们能识别「哥大附近」对应的警区（26），但该区域不在我们的数据覆盖范围内，没有可靠数据支撑分析。",
        alternative_info=alt,
        reselection_invitation="你可以从以下覆盖区域中重新选择：上东区、法拉盛、唐人街、威廉斯堡、布鲁克林高地。",
        general_suggestions=["夜间出行尽量结伴，并提前告知朋友行程"],
        emergency_resources=[VENUE],
        disclaimer="本分析仅供参考，不替代专业安保建议。",
        sources=["NYPD 公开数据（模拟）"] if alternative else [],
        sample_size=312 if alternative else None,
    )


class TestDegraded:
    def test_message_and_invitation_rendered(self):
        html = render.render_result(make_degraded(), CFG)
        assert "哥大附近" in html
        assert "重新选择" in html
        for area in FIVE_AREAS:
            assert area in html

    def test_alternative_info_rendered_when_present(self):
        html = render.render_result(make_degraded(), CFG)
        assert "🟢" in html and "312" in html

    def test_no_alternative_block_when_absent(self):
        html = render.render_result(make_degraded(alternative=False), CFG)
        assert "替代信息" not in html
        assert "🟢" not in html

    def test_suggestions_venues_disclaimer(self):
        html = render.render_result(make_degraded(), CFG)
        assert "夜间出行尽量结伴" in html
        assert "19th Precinct" in html
        assert "本分析仅供参考，不替代专业安保建议。" in html


# ---------------------------------------------------------------- 横切

# ---------------------------------------------------------------- 紧急模式（issue 12 完整版）

def make_emergency(**overrides) -> contracts.EmergencyResult:
    base = dict(
        call_911_prompt="立即拨打 911（无需证件，接通后可免费要求中文翻译）",
        chinese_interpreter_phrase="I need help. Can I have a Chinese interpreter?",
        info_checklist=[
            "你现在的具体位置（街道门牌号、路口或标志性建筑）",
            "发生了什么（用一两句话简明描述事件）",
        ],
        comfort_message="先深呼吸，你现在是安全的。",
        venues=[
            contracts.Venue(
                type="police_station", name="NYPD 19th Precinct", name_zh="纽约市警察局第19分局",
                address="153 East 67th Street, New York, NY 10065", phone="(212) 452-0600",
                hours="24小时", source="https://www.nyc.gov/", verified=True,
            ),
            contracts.Venue(
                type="hospital", name="Lenox Hill Hospital", name_zh="Lenox Hill 医院",
                address="100 East 77th Street, New York, NY 10075", phone="(212) 434-2000",
                hours="急诊24小时", source="http://example.org", verified=True,
            ),
        ],
        non_emergency_contacts=[
            contracts.Venue(
                type="city_services_number", name="311", name_zh="纽约市非紧急市政服务",
                phone="311", hours="24小时", source="https://portal.311.nyc.gov/", verified=True,
            ),
        ],
        sources=["NYPD 公开数据（模拟）"],
        disclaimer="本分析仅供参考，不替代专业安保建议。",
    )
    base.update(overrides)
    return contracts.EmergencyResult(**base)


class TestEmergencyPage:
    """紧急模式完整渲染（issue 12，PRD §6.2 紧急线框）：红色极简、逐字段契约一致。"""

    def test_red_minimal_theme_marker(self):
        # 红色极简：整页挂紧急主题类名（样式层），不是普通结果页样式
        html = render.render_result(make_emergency(), CFG)
        assert "theme-emergency" in html

    def test_big_call_911_button(self):
        html = render.render_result(make_emergency(), CFG)
        assert 'href="tel:911"' in html  # 可直接点击拨打（AC-014）
        assert "立即拨打 911" in html

    def test_chinese_interpreter_phrase_with_translation(self):
        html = render.render_result(make_emergency(), CFG)
        assert "I need help. Can I have a Chinese interpreter?" in html
        assert "中文翻译" in html  # 用语旁给出中文释义（PRD 线框）

    def test_info_checklist_ordered_and_complete(self):
        html = render.render_result(make_emergency(), CFG)
        assert "你现在的具体位置" in html
        assert "发生了什么" in html
        assert "<ol>" in html  # 清单按准备顺序编号呈现

    def test_comfort_message_rendered(self):
        assert "先深呼吸" in render.render_result(make_emergency(), CFG)

    def test_venues_with_phone_address_hours(self):
        # 安全场所清单：名称/地址/电话/营业时间逐字段透出，电话可点击
        html = render.render_result(make_emergency(), CFG)
        assert "NYPD 19th Precinct" in html
        assert "153 East 67th Street" in html
        assert 'href="tel:(212) 452-0600"' in html
        assert "24小时" in html
        assert "Lenox Hill 医院" in html

    def test_venue_verified_marker_and_source(self):
        # 用户故事 32：场所数据来自已核实的警区静态表——已核实标记 + 官方来源透出
        html = render.render_result(make_emergency(), CFG)
        assert "✓ 已核实" in html
        assert "官方来源" in html and "https://www.nyc.gov/" in html

    def test_jump_link_to_venues_per_wireframe(self):
        # PRD §6.2 紧急线框：拨打 911 下方有「查看安全场所」入口，锚点到清单
        html = render.render_result(make_emergency(), CFG)
        assert 'href="#safe-places"' in html
        assert 'id="safe-places"' in html

    def test_non_emergency_contacts_311_rendered(self):
        html = render.render_result(make_emergency(), CFG)
        assert "311" in html
        assert 'href="tel:311"' in html

    def test_no_proximity_words(self):
        # 无定位能力：渲染出的紧急页一律不得出现暗示定位的词（黑名单逐词断言）
        html = render.render_result(make_emergency(), CFG)
        for word in CFG.emergency.proximity_blacklist:
            assert word not in html

    def test_no_profile_sidebar_on_emergency_page(self):
        # 紧急页保持极简：不渲染画像表单/侧边栏（恐慌中不被复杂界面拖慢）
        html = render.render_result(make_emergency(), CFG)
        assert 'action="/profile"' not in html
        assert CFG.profile.notice not in html

    def test_guardrail_page_has_no_profile_sidebar(self):
        result = contracts.GuardrailResult(
            guardrail_kind="weapon_refusal",
            message="我们无法提供武器或器械的选购与携带建议",
            alternatives=["担心出行安全时，优先选择照明好、人流多的主干道"],
            sources=[],
            disclaimer="本分析仅供参考，不替代专业安保建议。",
        )
        assert 'action="/profile"' not in render.render_result(result, CFG)


# ---------------------------------------------------------------- 画像侧边栏 + 固定提示（issue 12）

PROFILE = {"gender": "女生", "identity": "留学生", "scene": ["带娃", "晚归"]}


class TestProfileSidebar:
    """画像侧边栏（issue 12，PRD §6.2 首页线框）：表单采集六维，隐私声明可见。"""

    def test_form_posts_to_profile_route(self):
        html = render.render_home(CFG)
        assert '<form class="profile-form" action="/profile" method="post">' in html

    def test_all_six_dimensions_collected(self):
        html = render.render_home(CFG)
        for name in ("gender", "age", "identity", "english", "duration", "scene"):
            assert f'name="{name}"' in html

    def test_privacy_notice_visible_next_to_form(self):
        # AC-023：画像隐私透明声明与表单同区块可见（措辞易懂转人工抽验）
        html = render.render_home(CFG)
        assert CFG.profile.notice in html
        assert "profile-aside" in html  # 声明与表单在同一侧边栏容器内

    def test_prefilled_from_session_profile(self):
        # 会话内回填：已填维度在下一次渲染时保持（仅内存，零持久化由 app 层断言）
        html = render.render_home(CFG, profile=PROFILE)
        assert 'value="女生" selected' in html
        assert 'value="留学生" selected' in html
        assert 'value="带娃" checked' in html
        assert 'value="晚归" checked' in html

    def test_empty_form_without_profile(self):
        html = render.render_home(CFG)
        assert " selected" not in html
        assert " checked" not in html

    def test_clear_button_present(self):
        html = render.render_home(CFG, profile=PROFILE)
        assert 'action="/profile/clear"' in html

    def test_sidebar_on_safety_result_page(self):
        html = render.render_result(make_safety(), CFG, profile=PROFILE)
        assert 'action="/profile"' in html
        assert CFG.profile.notice in html

    def test_scene_options_from_config_single_source(self):
        # 场景标签选项来自集中配置（人群建议键 + 晚归标记），不硬编码标签词
        html = render.render_home(CFG)
        for tag in CFG.profile.crowd_suggestions:
            assert f'value="{tag}"' in html
        for marker in CFG.profile.late_night_markers:
            assert f'value="{marker}"' in html


class TestProfilePinHint:
    """查询文本内的画像信息（如"我是女生"）：只作用于当次查询 + 可固定提示。"""

    def _safety_with_crowd(self, crowd: str | None) -> contracts.SafetyQueryResult:
        return make_safety(
            extracted=contracts.ExtractedDimensions(area="上东区", crowd=crowd, time=None),
        )

    def test_hint_shown_when_crowd_in_query_text(self):
        html = render.render_result(self._safety_with_crowd("女生"), CFG)
        assert "pin-hint" in html
        assert "可固定到侧边栏" in html
        assert "仅用于本次查询" in html
        assert 'name="add_scene" value="女生"' in html  # 一键固定表单

    def test_hint_posts_to_profile_route(self):
        html = render.render_result(self._safety_with_crowd("女生"), CFG)
        start = html.index("pin-hint")
        segment = html[start : start + 800]
        assert 'action="/profile"' in segment
        assert 'method="post"' in segment

    def test_no_hint_without_crowd_in_query(self):
        html = render.render_result(self._safety_with_crowd(None), CFG)
        assert "pin-hint" not in html

    def test_no_hint_when_crowd_already_pinned(self):
        html = render.render_result(
            self._safety_with_crowd("女生"), CFG, profile={"scene": ["女生"]}
        )
        assert "pin-hint" not in html

    def test_rating_display_unchanged_by_crowd_info(self):
        # 查询内画像信息不改变当次评级展示（ADR-0002 渲染侧：评级区块原样）
        plain = render.render_result(self._safety_with_crowd(None), CFG)
        with_crowd = render.render_result(self._safety_with_crowd("女生"), CFG)
        for marker in ("🟢", "相对安全", "可信度：高"):
            assert marker in plain and marker in with_crowd

    def test_crowd_in_query_not_rendered_into_sidebar(self):
        # 未固定的查询内人群信息不进侧边栏回填（作用域=当次查询）
        html = render.render_result(self._safety_with_crowd("女生"), CFG)
        sidebar = html[html.index("profile-aside") :]
        assert 'value="女生" checked' not in sidebar


class TestDispatcher:
    def test_unknown_type_rejected(self):
        with pytest.raises(TypeError):
            render.render_result(object(), CFG)

    def test_emergency_renders_basics(self):
        html = render.render_result(make_emergency(), CFG)
        assert "911" in html and "先深呼吸" in html
        assert 'href="tel:911"' in html  # PRD §6.2 紧急线框：📞 拨打 911 动作
        assert "本分析仅供参考，不替代专业安保建议。" in html

    def test_guardrail_renders_basics(self):
        result = contracts.GuardrailResult(
            guardrail_kind="weapon_refusal",
            message="我们无法提供武器或器械的选购与携带建议",
            alternatives=["担心出行安全时，优先选择照明好、人流多的主干道"],
            sources=[],
            disclaimer="本分析仅供参考，不替代专业安保建议。",
        )
        html = render.render_result(result, CFG)
        assert "武器" in html
        assert "本分析仅供参考，不替代专业安保建议。" in html
