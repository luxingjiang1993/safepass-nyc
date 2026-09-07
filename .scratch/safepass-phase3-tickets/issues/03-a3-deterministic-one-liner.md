# 03 — A3 one_liner 确定性数据钩子化

## 来源
docs/portfolio-100-execution-plan.md §2 A3 + 文首补丁 P6 + docs/adr/0003-suggestion-generation-architecture.md

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：一句话含「可核对」信息（夜间偏高 / 某类案件突出 / 相对全市），不是「区域：黄灯」。
- **做法**：Skill 生成或确定性模板二选一（有 LLM 用 Skill，无则规则填空）；继续字数上限 + 空话/恐慌黑名单。
- **DoD**：金标断言 one_liner 含至少一类允许的数据钩子；与 `charts`/`ratio` 不矛盾。
- **加分**：首屏决策速度（产品）+ 可证伪（技术）。
- **Craft**：S2。

## Phase 3 开赛定案（P6，效力优先）

1. **定案 = 确定性模板填空**：LLM 不写 one_liner（ADR-0003）。「Skill 生成」分支废弃。
2. 钩子词典（允许的数据钩子集合）只进 `config/app.yaml`；与建议正文共用同一钩子数据源（A1 验收硬项同源）。
3. 可在 A1 之前并行开工（不依赖 Skill）。
4. 字数上限 30 字（契约已锁，AC-005）+ 空话/恐慌黑名单沿用并收紧。

## Craft
- Craft IDs: S2
- **必须打开（产品 URL）**：https://www.walkscore.com/methodology ；任地址页看分数旁英文标签（如 Walker's Paradise）
- **观察清单**：单一数字 + 固定人话带；标签不是 LLM 散文；methodology 可读
- **借鉴什么 / 别抄什么**：借「固定人话标签 + 可核对」；禁止用 LLM 生成灯色标签、禁止把阈值写进 py

## 允许改动
- `safepass/pipeline.py`（one_liner 确定性装配）
- `config/app.yaml` + `safepass/config_loader.py`（钩子词典/黑名单）
- `tests/`（金标断言 one_liner 钩子 + 与 charts/ratio 不矛盾）

## 禁止
- LLM 参与 one_liner 生成
- 钩子/黑名单/字数阈值字面量进 py（红线 1）

## 验证
- `python -m pytest tests/ -q`

## 完成承诺
- 金标断言 one_liner 含至少一类允许的数据钩子且与 charts/ratio 不矛盾；LLM 调用路径零参与 one_liner；基线全绿。
