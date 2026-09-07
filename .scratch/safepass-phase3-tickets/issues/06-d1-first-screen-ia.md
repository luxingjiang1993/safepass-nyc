# 06 — D1 结果页首屏信息架构

## 执行方式 / 并行组
- **方式：/implement**（前端视觉需人工在环看效果）
- **依赖**：无（逻辑独立；one_liner 先用现有字段占位，A3 合并后自动升级）
- **并行组**：槽 1，与 A1（#16）、N3（#25）三窗口并行
- **文件独占**：frontend/（D2 等本票合并）
- **阻塞**：D2（#22）

## 来源
docs/portfolio-100-execution-plan.md §2 D1 + 文首补丁 P6

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：首屏 = 评级 + 人话解释 + one_liner + 3 条建议；图表/community/来源默认折叠。
- **DoD**：窄屏一屏内可见结论与建议；快照/断言锁层级。
- **加分**：从资料页 → 决策页（Rauch/Howard）。
- **Craft**：S3。
- **注**：若 C1 `rating_rationale` 尚未做，首屏「人话解释」可用现有字段确定性拼装占位，但波 2 必须换真 C1。

## Phase 3 开赛定案（P6，效力优先）

1. 「人话解释」= A3 的确定性 one_liner（数据钩子模板）；「3 条建议」= A1 Skill 正文（无 LLM 时模板建议同样进此布局）。
2. 降级态必须首屏可见（`degradation_notice` 已有，核对布局位置）。
3. 建议区渲染 `grounds` 的占位结构（A4 波 2 才填 UI 文案，但本票先把渲染槽留出）。

## Craft
- Craft IDs: S3
- **必须打开（产品 URL）**：https://www.crisis24.com/solutions/travel-risk-management
- **观察清单**：先结论档与行动，细节后置；槽位稳定，不靠聊天流
- **借鉴什么 / 别抄什么**：借首屏五槽（评级/人话解释/one_liner/建议/紧急资源）与默认折叠；禁止 GPS 追踪、企业 dashboard 密度

## 允许改动
- `frontend/render.py`（结果页模板层级）
- `frontend/style.css`（首屏/折叠样式）
- 结果页相关模板文件
- `tests/`（快照/结构断言）

## 禁止
- 换前端栈（stdlib SSR 不变）
- 改契约字段语义（只读渲染）

## 验证
- `python -m pytest tests/ -q`

## 完成承诺
- 窄屏一屏内可见评级+one_liner+3 条建议；图表/community/来源默认折叠；快照断言锁层级；降级横幅首屏可见；基线全绿。
