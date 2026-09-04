"""前端纯渲染层（issue 11 基础 + issue 12 紧急完整版/画像侧边栏，spec D1）。

本模块是**纯渲染**：零 I/O、零业务逻辑。所有数字/结论/文案逐字段来自
safepass/contracts.py 判别联合与集中配置；评级标签复用后端单一事实源
degraded.RATING_LABELS；可信度星级（CONTEXT.md 档位映射）是表现层常量——
图标与文字并存，安全评级不靠颜色传达（色盲可区分，结构层）。

布局参考 PRD §6.2 ASCII 线框（首页 / 查询结果页 / 紧急模式）。图表是纯
HTML/CSS 横向条形图 + 白天/夜间对比，数字与契约 charts 字段逐字段一致；
⚪ 时契约 charts 为 null，本模块整体不渲染图表区块（AC-022）。

issue 12 追加（纯渲染层职责）：
    紧急模式：红色极简整页（body.theme-emergency，样式层），大 911 按钮、
    中文报警用语 + 中文释义、信息准备清单、安抚话术、按警区/通用安全场所
    清单（含地址/营业时间，电话可点击）、311 等非紧急协助；紧急页不渲染
    画像侧边栏（极简不被复杂界面拖慢）。
    画像侧边栏：表单采集六维（性别/年龄/身份/英语水平/来美时长/场景标签），
    场景标签选项来自集中配置（profile.crowd_suggestions 键 + late_night_
    markers），不硬编码标签词；隐私声明（profile.notice，AC-023）与表单同
    区块可见。画像回填只是渲染会话态，零持久化由 app 层可观测断言守护。
    固定提示：查询文本内的人群信息（extracted.crowd）未固定进画像时，给出
    「可固定到侧边栏」提示（POST /profile add_scene）；提示是附加横幅，
    评级区块原样渲染（ADR-0002）。

UX 主观项（语气温暖、可信度感知、窄屏实机、无障碍抽验）转人工验收清单。
"""

from __future__ import annotations

import html
from typing import Any

from safepass import addressing, config_loader, contracts
from safepass.degraded import RATING_LABELS

# 可信度星级（CONTEXT.md 词汇：可信度档 → 星级映射；表现层常量）
CONFIDENCE_STARS = {
    "HIGH": "⭐⭐⭐⭐⭐",
    "MODERATE": "⭐⭐⭐☆☆",
    "LOW": "⭐⭐☆☆☆",
}

# 可信度档位的中文呈现（PRD §6.2 线框「可信度：中等 ⭐⭐⭐☆☆」；表现层映射，
# 档位名本身（HIGH/MODERATE/LOW）是后端契约值，逐字来自配置样本量档）
_CONFIDENCE_LABELS = {
    "HIGH": "高",
    "MODERATE": "中等",
    "LOW": "低",
}

# 画像表单选项（spec D5 六维；表现层常量——与后端消费相关的场景标签除外，
# 后者来自集中配置，见 _scene_options）
_PROFILE_GENDERS = ("女生", "男生", "其他", "不愿透露")
_PROFILE_AGES = ("18岁以下", "18-25", "26-35", "36-50", "50岁以上", "不愿透露")
_PROFILE_IDENTITIES = ("留学生", "新移民", "上班族", "游客", "家长", "老人")
_PROFILE_ENGLISH_LEVELS = ("不会英语", "基础日常", "工作流利")
_PROFILE_DURATIONS = ("刚来（1年以内）", "1-5年", "5年以上")

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="{body_class}">
<main class="page">
{body}
</main>
</body>
</html>
"""


def _esc(text: Any) -> str:
    """全部用户可见文本经 HTML 转义（契约字段也不可信，渲染层统一出口）。"""
    return html.escape(str(text), quote=True)


def _page(title: str, body: str, body_class: str = "") -> str:
    return _PAGE.format(title=_esc(title), body=body, body_class=_esc(body_class))


def _disclaimer(text: str) -> str:
    return f'<footer class="disclaimer">⚠️ {_esc(text)}</footer>'


def _back_link() -> str:
    return '<nav><a class="back" href="/">← 返回</a></nav>'


# ---------------------------------------------------------------- 画像侧边栏（issue 12）

def _scene_options(profile: dict[str, Any] | None, cfg: config_loader.AppConfig) -> list[str]:
    """场景标签选项：集中配置（人群建议键 + 晚归标记）为单一事实源，已固定但
    不在配置内的值（如查询内人群信息一键固定）追加在末尾，保持可见可回显。"""
    options = list(dict.fromkeys([*cfg.profile.crowd_suggestions.keys(), *cfg.profile.late_night_markers]))
    stored = (profile or {}).get("scene") or []
    options.extend(tag for tag in stored if tag not in options)
    return options


def _select(name: str, label: str, options: tuple[str, ...], profile: dict[str, Any] | None) -> str:
    current = (profile or {}).get(name, "")
    opts = ['    <option value="">未选择</option>']
    opts.extend(
        f'    <option value="{_esc(opt)}"{" selected" if opt == current else ""}>{_esc(opt)}</option>'
        for opt in options
    )
    return f'  <label class="profile-field">{_esc(label)}\n  <select name="{_esc(name)}">\n{chr(10).join(opts)}\n  </select>\n  </label>'


def _profile_sidebar(profile: dict[str, Any] | None, cfg: config_loader.AppConfig) -> str:
    """画像侧边栏（PRD §6.2 首页线框）：六维表单 + 隐私声明同区块可见（AC-023）。

    纯渲染：回填值只是渲染会话态；零持久化/零上传由 app 层可观测断言守护。
    """
    fields = "\n".join(
        [
            _select("gender", "性别", _PROFILE_GENDERS, profile),
            _select("age", "年龄", _PROFILE_AGES, profile),
            _select("identity", "身份", _PROFILE_IDENTITIES, profile),
            _select("english", "英语水平", _PROFILE_ENGLISH_LEVELS, profile),
            _select("duration", "来美时长", _PROFILE_DURATIONS, profile),
        ]
    )
    stored_scene = _pinned_scene_tags(profile)
    boxes = "\n".join(
        f'    <label><input type="checkbox" name="scene" value="{_esc(tag)}"'
        f'{" checked" if tag in stored_scene else ""}> {_esc(tag)}</label>'
        for tag in _scene_options(profile, cfg)
    )
    clear_form = (
        '\n  <form class="profile-clear" action="/profile/clear" method="post">\n'
        '    <button type="submit">清除画像</button>\n  </form>'
        if profile else ""
    )
    return f"""<aside class="profile-aside">
  <h2>🙋 我的情况（可选）</h2>
  <p class="profile-notice">🔒 {_esc(cfg.profile.notice)}，我们不会保存或上传。</p>
  <form class="profile-form" action="/profile" method="post">
{fields}
  <fieldset class="profile-scene">
    <legend>场景标签（可多选）</legend>
{boxes}
  </fieldset>
  <button type="submit">保存画像</button>
  </form>{clear_form}
</aside>"""


def _pinned_scene_tags(profile: dict[str, Any] | None) -> list[str]:
    """画像中已固定的场景标签（list 值逐条；其他形态防御性忽略）。"""
    scene = (profile or {}).get("scene")
    return list(scene) if isinstance(scene, list) else []


def _pin_hint(result: contracts.SafetyQueryResult, profile: dict[str, Any] | None) -> str:
    """查询文本内人群信息的固定提示（spec 用户故事 19）：仅当次查询作用域，
    提示可固定到侧边栏；附加横幅，不改变当次评级展示（ADR-0002）。"""
    crowd = result.extracted.crowd
    if not crowd or crowd in _pinned_scene_tags(profile):
        return ""
    return f"""<section class="pin-hint">
  <p>检测到你的查询里提到了「{_esc(crowd)}」——该信息仅用于本次查询，可固定到侧边栏，让后续查询自动带上。</p>
  <form action="/profile" method="post">
    <input type="hidden" name="add_scene" value="{_esc(crowd)}">
    <button type="submit">固定到侧边栏</button>
  </form>
</section>"""


# ---------------------------------------------------------------- 首页

def render_home(cfg: config_loader.AppConfig, profile: dict[str, Any] | None = None) -> str:
    """首页（PRD §6.2 线框 1）：问候 + 查询输入 + 五个核心警区一键快速查询
    + 画像侧边栏（会话级，可选）。

    快速查询按钮是零输入查询链接（`/query?q=<规范中文名>`），区域清单来自
    配置别名表（addressing.canonical_names，顺序稳定），不硬编码警区。
    """
    names = addressing.canonical_names(cfg)
    buttons = "\n".join(
        f'    <a class="quick-btn" href="/query?q={_esc(name)}">📍 {_esc(name)}</a>'
        for name in names.values()
    )
    body = f"""<header class="hero">
  <h1>🛡️ SafePass NYC</h1>
  <p class="tagline">你的纽约安全管家</p>
</header>
<section class="greeting">
  <p>你好呀 👋</p>
  <p>不管是租房、通勤还是晚上回家，<br>有安全方面的疑问都可以问我～</p>
</section>
<form class="query-form" action="/query" method="get">
  <input type="text" name="q" placeholder="比如：上东区晚上安全吗？我是女生" aria-label="输入你的安全问题">
  <button type="submit">查询</button>
</form>
<section class="quick">
  <h2>快速查询</h2>
  <div class="quick-grid">
{buttons}
  </div>
</section>
{_profile_sidebar(profile, cfg)}
{_disclaimer(cfg.disclaimer)}"""
    return _page("SafePass NYC", body)


# ---------------------------------------------------------------- 图表

def _bar(label: str, count: int, max_count: int) -> str:
    """单条横向条形：宽度为相对 max 的百分比，数值以文字并排呈现（不靠长度 alone）。"""
    pct = 100 if max_count <= 0 else round(count / max_count * 100)
    return (
        f'<div class="bar-row"><span class="bar-label">{_esc(label)}</span>'
        f'<span class="bar-track"><span class="bar-fill" style="width:{pct}%"></span></span>'
        f'<span class="bar-value">{count}</span></div>'
    )


def _top5_bars(top5: list[contracts.OffenseCount]) -> str:
    """犯罪类型 Top5 横向条形组（数字与契约逐字段一致）。"""
    max_top = max((t.count for t in top5), default=0)
    return "\n".join(_bar(t.offense_type, t.count, max_top) for t in top5)


def _day_night_bars(dn: contracts.DayNight) -> str:
    """白天/夜间对比条形组（数字与契约 day_night 逐字段一致）。"""
    max_dn = max(dn.day, dn.night, 1)
    return f'{_bar("白天", dn.day, max_dn)}\n{_bar("夜间", dn.night, max_dn)}'


def _charts_block(charts: contracts.Charts) -> str:
    """📈 数据可视化（AC-022）：犯罪类型 Top5 横向条形图 + 白天/夜间对比。

    数字逐字段来自契约；调用方保证 charts 非 null（⚪ 时契约为 null，
    本区块整体不渲染）。
    """
    return f"""<details class="charts">
  <summary>📈 数据可视化</summary>
  <h3>犯罪类型 Top 5</h3>
  <div class="bars">
{_top5_bars(charts.top5_types)}
  </div>
  <h3>白天 / 夜间对比</h3>
  <div class="bars">
{_day_night_bars(charts.day_night)}
  </div>
</details>"""


# ---------------------------------------------------------------- 安全结果

def _confidence_block(result: contracts.SafetyQueryResult, cfg: config_loader.AppConfig) -> str:
    """可信度星级 + 动态样本量文案（AC-009：星级与档位映射一致，样本量为真实命中数）。"""
    if result.confidence_tier is None:
        return ""
    tier = result.confidence_tier
    stars = CONFIDENCE_STARS.get(tier, "")
    label = _CONFIDENCE_LABELS.get(tier, tier)
    template = cfg.confidence_explanations.get(tier, "基于本次查询命中的 {n} 条记录")
    return (
        f'<p class="confidence">可信度：{_esc(label)} '
        f'<span class="stars" aria-hidden="true">{stars}</span></p>'
        f'<p class="sample">{_esc(template.format(n=result.sample_size))}</p>'
    )


def _community_info_block(info: dict[str, Any]) -> str:
    """华人社区信息（AC-015 渲染侧）：逐字段透出，未记载项的统一标注原样呈现。"""
    parts = ['<section class="community"><h2>🏮 华人社区信息</h2>']
    if info.get("hate_crime"):
        parts.append(f'<p>仇恨犯罪记录：{_esc(info["hate_crime"])}</p>')
    alerts = info.get("scam_alerts") or []
    if alerts:
        items = "\n".join(f"    <li>{_esc(a)}</li>" for a in alerts)
        parts.append(f'  <h3>诈骗提醒</h3>\n  <ul>\n{items}\n  </ul>')
    if info.get("chinese_officer"):
        parts.append(f'<p>中文服务：{_esc(info["chinese_officer"])}</p>')
    resources = info.get("community_resources") or []
    if resources:
        items = "\n".join(
            f'    <li>{_esc(r.get("name", ""))}'
            f'（<a href="{_esc(r.get("source", ""))}">官方来源</a>）</li>'
            for r in resources
        )
        parts.append(f'  <h3>社区资源</h3>\n  <ul>\n{items}\n  </ul>')
    parts.append("</section>")
    return "\n".join(parts)


def _venue_label(v: contracts.Venue) -> str:
    """场所名称：中文名（原名）优先，与 _venues_block / 紧急清单同一形状。"""
    return _esc(v.name) if not v.name_zh else f"{_esc(v.name_zh)}（{_esc(v.name)}）"


def _venues_block(title: str, venues: list[contracts.Venue]) -> str:
    if not venues:
        return ""
    items = []
    for v in venues:
        phone = f' · <a href="tel:{_esc(v.phone)}">{_esc(v.phone)}</a>' if v.phone else ""
        items.append(f"    <li>{_venue_label(v)}{phone}</li>")
    return f'<section class="venues"><h2>{_esc(title)}</h2>\n  <ul>\n{chr(10).join(items)}\n  </ul>\n</section>'


def render_safety(
    result: contracts.SafetyQueryResult,
    cfg: config_loader.AppConfig,
    profile: dict[str, Any] | None = None,
) -> str:
    """覆盖区内查询结果页（PRD §6.2 线框 2），逐区块对应契约字段。

    profile = 会话画像：只用于侧边栏回填与固定提示（纯渲染），评级区块
    与画像零相关（ADR-0002 的渲染侧体现）。
    """
    header = (
        f'<header class="result-head rating-{_esc(result.rating)}">\n'
        f'  <p class="rating">{_esc(RATING_LABELS[result.rating])}</p>\n'
        f'  <h1>{_esc(result.area)}</h1>\n'
        f'  <p class="precinct">警区 {_esc(result.precinct)} · 基于本次查询命中的 {_esc(result.sample_size)} 条记录</p>\n'
        f'{_confidence_block(result, cfg)}\n'
        f'</header>'
    )
    # 评级可解释依据：per-100k 与市均值倍数（⚪ 时契约为 null，不渲染）
    basis = ""
    if result.rating_explainable_basis is not None:
        basis = (
            f'<p class="basis">评级依据：该警区犯罪率（per 100k）约为全市均值的 '
            f'{result.rating_explainable_basis:.2f} 倍</p>'
        )
    one_liner = f'<section class="one-liner"><h2>📋 一句话总结</h2><p>{_esc(result.one_liner)}</p></section>'

    dimensions = ""
    if result.dimensions:
        items = "\n".join(f"    <li><strong>{_esc(d.get('dimension', ''))}</strong>：{_esc(d.get('value', ''))}</li>" for d in result.dimensions)
        dimensions = f'<details class="dimensions" open><summary>📊 具体情况</summary>\n  <ul>\n{items}\n  </ul>\n</details>'

    suggestions = ""
    if result.suggestions:
        items = "\n".join(f"    <li>✅ {_esc(s)}</li>" for s in result.suggestions)
        suggestions = f'<details class="suggestions" open><summary>💡 贴心建议</summary>\n  <ul>\n{items}\n  </ul>\n</details>'

    charts = _charts_block(result.charts) if result.charts is not None else ""

    unknowns = ""
    if result.unknowns:
        items = "\n".join(f"    <li>{_esc(u)}</li>" for u in result.unknowns)
        unknowns = f'<details class="unknowns" open><summary>🤷 我不知道的</summary>\n  <ul>\n{items}\n  </ul>\n</details>'

    community = _community_info_block(result.community_info) if result.community_info else ""
    venues = _venues_block("🚨 紧急资源", result.emergency_resources)

    sources_items = "\n".join(f"    <li>{_esc(s)}</li>" for s in result.sources)
    meta = (
        f'<section class="sources"><h2>数据来源与覆盖时间</h2>\n'
        f'  <p>覆盖时间：{_esc(result.time_range)}</p>\n  <ul>\n{sources_items}\n  </ul>\n</section>'
    )

    body = "\n".join(
        part
        for part in (
            _back_link(), header, basis, _pin_hint(result, profile), one_liner, dimensions,
            suggestions, charts, community, unknowns, venues, meta,
            _profile_sidebar(profile, cfg),
            _disclaimer(result.disclaimer),
        )
        if part
    )
    return _page(f"{result.area} — SafePass NYC", body)


# ---------------------------------------------------------------- 对比

def _area_card(area: contracts.AreaSummary) -> str:
    return f"""<article class="area-card rating-{_esc(area.rating)}">
  <h2>{_esc(RATING_LABELS[area.rating])} {_esc(area.area)}</h2>
  <p>警区 {_esc(area.precinct)} · 样本 {_esc(area.sample_size)} 条</p>
  <div class="bars">
{_day_night_bars(area.day_night)}
  </div>
  <div class="bars">
{_top5_bars(area.top5_types)}
  </div>
</article>"""


_DIMENSION_STATUS_LABELS = {
    "available": "available（可对比）",
    "in_development": "in_development（开发中）",
}


def render_comparison(
    result: contracts.ComparisonResult,
    cfg: config_loader.AppConfig,
    profile: dict[str, Any] | None = None,
) -> str:
    """双区对比视图（ComparisonResult 契约；F3-2 维度表 + F3-4 决策辅助）。"""
    cards = "\n".join(_area_card(a) for a in result.areas)
    dim_rows = "\n".join(
        f'    <li>{_esc(d.get("dimension", ""))}：'
        f'{_esc(_DIMENSION_STATUS_LABELS.get(d.get("status", ""), d.get("status", "")))}</li>'
        for d in result.dimensions
    )
    decision = f'<p class="decision-aid">{_esc(result.decision_aid)}</p>' if result.decision_aid else ""
    sources_items = "\n".join(f"    <li>{_esc(s)}</li>" for s in result.sources)
    body = f"""{_back_link()}
<header class="result-head"><h1>🔀 区域对比</h1></header>
<section class="compare-grid">
{cards}
</section>
<details class="dimensions" open><summary>📊 对比维度</summary>
  <ul>
{dim_rows}
  </ul>
</details>
{decision}
<section class="sources"><h2>数据来源</h2>
  <ul>
{sources_items}
  </ul>
</section>
{_profile_sidebar(profile, cfg)}
{_disclaimer(result.disclaimer)}"""
    return _page("区域对比 — SafePass NYC", body)


# ---------------------------------------------------------------- 降级

def render_degraded(
    result: contracts.DegradedResult,
    cfg: config_loader.AppConfig,
    profile: dict[str, Any] | None = None,
) -> str:
    """诚实降级视图（DegradedResult 契约）：说明 + 替代信息 + 重新选择邀请。

    单边越界时越界侧只有 out_of_coverage 说明，覆盖侧真实评级作替代信息（F3-5）。
    """
    alt = result.alternative_info
    alternative_block = ""
    if alt is not None:
        stars = CONFIDENCE_STARS.get(alt.confidence or "", "")
        confidence = f' · 可信度 {_esc(_CONFIDENCE_LABELS.get(alt.confidence or "", alt.confidence))} {stars}' if alt.confidence else ""
        explanation = f'<p>{_esc(alt.explanation)}</p>' if alt.explanation else ""
        alternative_block = f"""<section class="alternative">
  <h2>📍 替代信息：{_esc(alt.area)}（警区 {_esc(alt.precinct)}）</h2>
  <p class="rating">{_esc(RATING_LABELS[alt.rating])} · 样本 {_esc(alt.sample_size)} 条{confidence}</p>
{explanation}
  <div class="bars">
{_day_night_bars(alt.day_night)}
  </div>
</section>"""

    names = addressing.canonical_names(cfg)  # 覆盖区清单同首页来源（配置别名表）
    choices = "\n".join(
        f'    <a class="quick-btn" href="/query?q={_esc(name)}">📍 {_esc(name)}</a>'
        for name in names.values()
    )
    invitation = (
        f'<section class="reselect"><h2>🧭 重新选择</h2>\n'
        f'  <p>{_esc(result.reselection_invitation)}</p>\n'
        f'  <div class="quick-grid">\n{choices}\n  </div>\n</section>'
    )

    suggestions = ""
    if result.general_suggestions:
        items = "\n".join(f"    <li>✅ {_esc(s)}</li>" for s in result.general_suggestions)
        suggestions = f'<details class="suggestions" open><summary>💡 通用建议</summary>\n  <ul>\n{items}\n  </ul>\n</details>'

    venues = _venues_block("🚨 紧急资源", result.emergency_resources)

    sources = ""
    if result.sources:
        items = "\n".join(f"    <li>{_esc(s)}</li>" for s in result.sources)
        sources = f'<section class="sources"><h2>数据来源</h2>\n  <ul>\n{items}\n  </ul>\n</section>'

    body = "\n".join(
        part
        for part in (
            _back_link(),
            f'<header class="result-head degraded"><h1>🛠️ 暂时无法给出完整分析</h1></header>',
            f'<section class="degraded-message"><p>{_esc(result.message)}</p></section>',
            alternative_block, invitation, suggestions, venues, sources,
            _profile_sidebar(profile, cfg),
            _disclaimer(result.disclaimer),
        )
        if part
    )
    return _page("SafePass NYC", body)


# ---------------------------------------------------------------- 紧急（issue 12 完整版）

def _emergency_venue_list(venues: list[contracts.Venue]) -> str:
    """安全场所/协助清单条目：名称（中英）、地址、营业时间、可点击电话逐字段透出；
    已核实标记与官方来源同步呈现（用户故事 32：数据来自已核实的警区静态表）。"""
    items = []
    for v in venues:
        meta = " · ".join(
            part for part in (
                _esc(v.address) if v.address else "",
                _esc(v.hours) if v.hours else "",
                '<span class="verified">✓ 已核实</span>' if v.verified else "",
                f'<a href="{_esc(v.source)}">官方来源</a>' if v.source else "",
            ) if part
        )
        meta_str = f"<br><small>{meta}</small>" if meta else ""
        phone = f'<br><a href="tel:{_esc(v.phone)}">📞 {_esc(v.phone)}</a>' if v.phone else ""
        items.append(f"    <li>{_venue_label(v)}{meta_str}{phone}</li>")
    return "\n".join(items)


def render_emergency(result: contracts.EmergencyResult) -> str:
    """紧急模式页（issue 12，PRD §6.2 紧急线框）：红色极简整页（body.theme-
    emergency，样式层），恐慌场景下大按钮优先、信息分层最少。

    逐字段对应 EmergencyResult 契约：911 引导 / 中文报警用语（附中文释义）/
    信息准备清单（有序）/ 安抚话术 / 按警区或通用安全场所清单 / 311 与社区
    协助电话。不渲染画像侧边栏与返回链接——极简不被复杂界面拖慢（AC-013）。
    """
    checklist = "\n".join(f"    <li>{_esc(item)}</li>" for item in result.info_checklist)
    venues = (
        f'<section class="emergency-venues" id="safe-places"><h2>🏪 可以前往的安全场所</h2>\n'
        f'  <ul>\n{_emergency_venue_list(result.venues)}\n  </ul>\n</section>'
        if result.venues else ""
    )
    contacts = (
        f'<section class="emergency-contacts"><h2>☎️ 非紧急协助</h2>\n'
        f'  <ul>\n{_emergency_venue_list(result.non_emergency_contacts)}\n  </ul>\n</section>'
        if result.non_emergency_contacts else ""
    )
    jump = (
        '<p class="emergency-jump"><a href="#safe-places">🏪 查看安全场所清单</a></p>'
        if result.venues else ""
    )
    sources = ""
    if result.sources:
        items = "\n".join(f"    <li>{_esc(s)}</li>" for s in result.sources)
        sources = f'<section class="sources"><h2>数据来源</h2>\n  <ul>\n{items}\n  </ul>\n</section>'
    body = f"""<header class="result-head emergency">
  <h1>🚨 紧急模式</h1>
  <p class="emergency-lead">如果你现在处于危险中，请立即拨打 911。保持冷静，你正在做正确的事。</p>
</header>
<p class="call-911-big"><a href="tel:911">📞 拨打 911</a></p>
{jump}
<p class="call-911-note">{_esc(result.call_911_prompt)}</p>
<p class="comfort">{_esc(result.comfort_message)}</p>
<section class="phrase-block"><h2>用中文报警怎么说</h2>
  <p class="phrase">“{_esc(result.chinese_interpreter_phrase)}”</p>
  <p class="phrase-zh">（我需要帮助。能给我安排一位中文翻译吗？）</p>
</section>
<section><h2>保持冷静，提供以下信息</h2>
  <ol>
{checklist}
  </ol>
</section>
{venues}
{contacts}
{sources}
{_disclaimer(result.disclaimer)}"""
    return _page("🚨 紧急模式 — SafePass NYC", body, body_class="theme-emergency")


def render_guardrail(result: contracts.GuardrailResult) -> str:
    """负例防线拒绝视图（GuardrailResult 契约：拒绝 + 转向，绝不边拒绝边分析）。"""
    alternatives = "\n".join(f"    <li>{_esc(a)}</li>" for a in result.alternatives)
    alt_block = (
        f'<section><h2>你可以这样继续</h2>\n  <ul>\n{alternatives}\n  </ul>\n</section>'
        if result.alternatives else ""
    )
    body = f"""{_back_link()}
<header class="result-head"><h1>🛡️ SafePass NYC</h1></header>
<section class="guardrail-message"><p>{_esc(result.message)}</p></section>
{alt_block}
{_disclaimer(result.disclaimer)}"""
    return _page("SafePass NYC", body)


# ---------------------------------------------------------------- 判别联合分发

def render_result(
    contract: contracts.ResponseContract,
    cfg: config_loader.AppConfig,
    profile: dict[str, Any] | None = None,
) -> str:
    """判别联合分发（五种形态全覆盖；未知类型明确失败，不静默兜底）。

    profile = 会话画像，只传给常规查询视图（侧边栏回填 + 固定提示）；紧急/
    防线页保持极简，不渲染画像表单。
    """
    if isinstance(contract, contracts.SafetyQueryResult):
        return render_safety(contract, cfg, profile)
    if isinstance(contract, contracts.ComparisonResult):
        return render_comparison(contract, cfg, profile)
    if isinstance(contract, contracts.DegradedResult):
        return render_degraded(contract, cfg, profile)
    if isinstance(contract, contracts.EmergencyResult):
        return render_emergency(contract)
    if isinstance(contract, contracts.GuardrailResult):
        return render_guardrail(contract)
    raise TypeError(
        f"未知响应契约形态：{type(contract).__name__}（渲染层只消费 contracts.ResponseContract 判别联合）"
    )
