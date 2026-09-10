"""十槽自制单色 SVG 插画（票 09 / D4）。

纯字符串：零 I/O、无位图、无 emoji。用 currentColor 随主题变色；
不按安全灯配犯罪叙事图。测试只锁 data-illustration 标记，不锁 path。
"""

from __future__ import annotations

# 槽名稳定：首页 / 覆盖内页眉 / 越界 / 紧急 / 空态 / 熔断 /
# 防线 / 对比 / 隐私法律 / 无法解析
SLOTS = (
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

# 各槽几何不同，语义靠页面文案；SVG 只做冷静简报氛围
_SVGS: dict[str, str] = {
    "home": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M8 28 L32 10 L56 28 V54 H40 V38 H24 V54 H8 Z"/>'
        "</svg>"
    ),
    "safety-header": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<rect x="10" y="12" width="44" height="40" rx="3"/>'
        '<path d="M18 24 H46 M18 34 H40 M18 44 H36"/>'
        "</svg>"
    ),
    "out-of-coverage": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<circle cx="32" cy="32" r="22"/>'
        '<path d="M20 20 L44 44"/>'
        "</svg>"
    ),
    "emergency": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M32 10 L54 50 H10 Z"/>'
        '<path d="M32 26 V38 M32 44 V46"/>'
        "</svg>"
    ),
    "empty": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<rect x="12" y="16" width="40" height="32" rx="2"/>'
        '<path d="M22 32 H42"/>'
        "</svg>"
    ),
    "fuse": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M14 32 H26 L30 20 L38 44 L42 32 H50"/>'
        "</svg>"
    ),
    "guardrail": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M32 10 L50 18 V34 C50 46 40 54 32 56 C24 54 14 46 14 34 V18 Z"/>'
        "</svg>"
    ),
    "comparison": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<rect x="8" y="14" width="20" height="36" rx="2"/>'
        '<rect x="36" y="14" width="20" height="36" rx="2"/>'
        "</svg>"
    ),
    "legal": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M18 12 H40 L48 20 V52 H18 Z"/>'
        '<path d="M40 12 V20 H48 M24 30 H42 M24 38 H38"/>'
        "</svg>"
    ),
    "unparseable": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="48" height="48" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true">'
        '<circle cx="32" cy="32" r="22"/>'
        '<path d="M24 28 Q32 20 40 28 M24 40 Q32 48 40 40" '
        'stroke-linecap="round"/>'
        "</svg>"
    ),
}


def mark(slot: str) -> str:
    """返回带 data-illustration 的插画块；未知槽名立即失败（不静默）。"""
    if slot not in _SVGS:
        raise KeyError(f"未知插画槽：{slot!r}（合法：{', '.join(SLOTS)}）")
    return (
        f'<div class="illustration" data-illustration="{slot}" aria-hidden="true">'
        f"{_SVGS[slot]}</div>"
    )
