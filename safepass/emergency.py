"""紧急检测第一层 + 静态紧急组装（spec D7；issue 07 / RALPH T5）。

第一层：关键词静态表检测（config emergency.keywords），优先于一切 LLM 调用，
命中即进无 LLM 静态分支。第二层（兜底）：FC 路由中的 emergency_help 工具
接住不含关键词的紧急表述，路由判定后同样不再生成自由文本。

EmergencyResult 由静态模板（config emergency.*）+ 警区静态表
（fixtures/safe_places/precinct_safe_places.json）直接组装，全程零 LLM：
    查询文本解析出覆盖内警区 → 按警区安全场所清单（便利店/医院/警局）
    否则 → 通用清单（911/311 + 五警局地址电话）
non_emergency_contacts 取静态表通用清单中的 311 市政服务条目。

诚实边界：
    - 系统无定位能力：话术与清单一律禁止出现"最近""离你最近"等词
      （config emergency.proximity_blacklist；装配层守卫 + 测试集双层断言）；
    - 解析出越界/跨警区（静态表无条目）→ 回退通用清单，绝不编造；
    - 未核实的机构（verified=false）按静态表护栏只列机构名（逐字段透出）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from safepass import addressing, config_loader, contracts, degraded, output_pipeline

# 紧急响应用到的数据资产（顶层 sources 标注；条目级 source 逐字段透出）
EMERGENCY_SOURCE_LABEL = "警区安全场所静态表"
# fixtures/safe_places 通用清单中"非紧急协助"条目的类型（当前为 311 市政服务；
# 静态表护栏：无官方来源的机构不录入，社区协助电话待核实后自然进入本过滤）
NON_EMERGENCY_VENUE_TYPE = "city_services_number"


def is_emergency(query_text: str, cfg: config_loader.AppConfig) -> bool:
    """第一层：关键词静态表命中检测（优先于一切 LLM 调用，零 LLM 零画像）。"""
    return any(keyword in query_text for keyword in cfg.emergency.keywords)


def _load_safe_places_doc() -> dict[str, Any]:
    return json.loads(degraded.SAFE_PLACES_PATH.read_text(encoding="utf-8"))


def _select_venue_dicts(
    doc: dict[str, Any], resolved: Iterable[addressing.ResolvedArea]
) -> list[dict]:
    """清单选择：首个单警区且静态表有条目的解析区域 → 按警区清单；
    否则（无区域/越界/跨警区/静态表无条目）→ 通用清单。"""
    for area in resolved:
        if len(area.precincts) != 1:
            continue
        venues = doc["precincts"].get(str(area.precincts[0]), {}).get("venues")
        if venues is not None:
            return list(venues)
    return list(doc["general"]["venues"])


def validate_emergency_core(model: Any) -> None:
    """AC-014 字段断言：911 按钮文案/中文报警用语/安抚话术非空，信息准备清单非空。"""
    for attr in ("call_911_prompt", "chinese_interpreter_phrase", "comfort_message"):
        value = getattr(model, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise output_pipeline.BusinessValidationError(f"emergency 字段 {attr} 不得为空")
    checklist = getattr(model, "info_checklist", None)
    if not checklist or any(not str(item).strip() for item in checklist):
        raise output_pipeline.BusinessValidationError("emergency.info_checklist 不得为空")


def make_proximity_guard(cfg: config_loader.AppConfig) -> output_pipeline.Validator:
    """无定位词守卫：紧急契约全部文本不得出现暗示定位的词（配置驱动）。

    系统无定位能力，出现"最近"类词汇会产生错误的定位预期（PRD 用户故事 34）。
    """
    blacklist = tuple(w for w in cfg.emergency.proximity_blacklist if w)

    def _guard(model: Any) -> None:
        text = _all_text(model)
        for word in blacklist:
            if word in text:
                raise output_pipeline.BusinessValidationError(
                    f"紧急响应出现暗示定位的词「{word}」（系统无定位能力）"
                )

    return _guard


def _all_text(model: Any) -> str:
    """契约里所有文本拼在一起做扫描（含嵌套清单/联系方式/来源）。"""
    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(model.model_dump() if hasattr(model, "model_dump") else model)
    return "\n".join(chunks)


def build_emergency_result(
    resolved: Iterable[addressing.ResolvedArea],
    cfg: config_loader.AppConfig,
) -> contracts.EmergencyResult:
    """装配 EmergencyResult（spec D3/D7）：静态模板 + 警区静态表，全程零 LLM。

    resolved 为查询文本解析出的区域集合（可为空 = 无区域查询历史）。
    按警区清单与通用清单的选择见 _select_venue_dicts；两种来源都逐字段透出，
    未经核实的机构按护栏只有机构名（Venue 可选字段为 None）。
    """
    doc = _load_safe_places_doc()
    venue_dicts = _select_venue_dicts(doc, resolved)
    result = contracts.EmergencyResult(
        is_emergency=True,
        call_911_prompt=cfg.emergency.call_911_prompt,
        chinese_interpreter_phrase=cfg.emergency.chinese_interpreter_phrase,
        info_checklist=list(cfg.emergency.info_checklist),
        comfort_message=cfg.emergency.comfort_message,
        venues=venue_dicts,  # Pydantic 逐字段校验为 Venue
        non_emergency_contacts=[
            contracts.Venue.model_validate(v)
            for v in doc["general"]["venues"]
            if v.get("type") == NON_EMERGENCY_VENUE_TYPE
        ],
        sources=[EMERGENCY_SOURCE_LABEL],
        disclaimer=cfg.disclaimer,
    )
    # 装配层确定性自检：AC-014 字段断言 + 无定位词守卫 + 免责声明，
    # 配置或静态表被破坏时明确失败，绝不带病透出契约。
    output_pipeline.validate_contract(
        result,
        validators=(
            validate_emergency_core,
            make_proximity_guard(cfg),
            output_pipeline.validate_non_empty_disclaimer,
        ),
    )
    return result
