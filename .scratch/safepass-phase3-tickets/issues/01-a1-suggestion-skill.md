# 01 — A1 Suggestion Skill 主路径（LLM 措辞 + 数据定调）

## 来源
docs/portfolio-100-execution-plan.md §2 A1 + 文首补丁 P2/P6 + docs/adr/0003-suggestion-generation-architecture.md

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：用户可见的「贴心建议 / one_liner」来自受约束生成，不再只是 `safety_general` 重排。
- **缺口**：`skills/` 空壳；`_build_safety_result` 用配置模板。
- **做法**：Skill = 提示词 + Pydantic 输出 + 业务校验；输入打包：评级摘要、`top5`、昼夜、三维/画像、检索 top-3 摘要；经现有 `output_pipeline`；熔断/`llm_client=None` → 明示模板降级。
- **DoD**：注入真实/fake client 时建议可区分；`llm_client=None` 仍出合法契约；评级比特级不变（既有 invariance 测试仍绿）。
- **加分**：补上「AI 应用」而非「数据仪表盘」的核心叙事。
- **Craft**：S2（one_liner 可核对方向）；完成后重测 T4 三路径。
- **Agent 注意**：阈值/黑名单只读 yaml；LLM **零接触** rating / confidence / out-of-coverage。

## Phase 3 开赛定案（P6，效力优先）

1. **验收硬项**：输出契约强制携带 grounds（`suggestion_grounds: list[{doc_id, quote}]`，可先空但字段必须立）与数据钩子（A3 模板同源钩子）；校验不过 → 有限重试 → 仍不过降级确定性模板。
2. **画像剔除**：输入打包**不得**含六维画像（ADR-0003）；画像只在本机确定性加权/排序。补丁 P2 的「改隐私页口径」路径废弃——隐私页一字不改。
3. **范围外**：one_liner 不在本票（A3 确定性票）；检索注入是 A2。
4. 本票接线须预留「两路径对照」开关（B1 需要同一 query 跑 Skill 路径与模板路径）。

## Craft
- Craft IDs: S2
- **必须打开（产品 URL）**：https://www.walkscore.com/methodology （任地址页看分数旁固定英文标签）
- **观察清单**：单一数字 + 固定人话带；methodology 页讲衰减/数据源/局限；标签不是 LLM 散文
- **借鉴什么 / 别抄什么**：借「分→固定人话标签、可核对」进建议契约与钩子；禁止引入 Walk Score API、禁止用 LLM 生成灯色标签、禁止阈值写进 py

## 允许改动
- `safepass/skills/`（新建 suggestion skill：提示词 + schema + 业务校验）
- `safepass/pipeline.py`（`_build_safety_result` 建议装配接 Skill 主路径）
- `safepass/contracts.py`（grounds 字段、建议契约）
- `safepass/output_pipeline.py`（复用生成→解析→校验→有限重试）
- `config/app.yaml` + `safepass/config_loader.py`（黑名单/钩子/开关；阈值只进 yaml）
- `tests/` + 相关 fixture（fake client 注入、None 降级、评级比特级不变）

## 禁止
- LLM 改评级/越界/可信度
- 画像进入发给模型供应商的请求体
- 运行时直连外部数据 API；为本票引入新框架（无 ADR）
- 改动隐私页/免责页文案

## 验证
- `python -m pytest tests/ -q`
- 本票新增测试全离线（fake client / cassette）

## 完成承诺
- 真实/fake client 注入时建议可区分，且 `llm_client=None` 仍出合法契约、评级比特级不变、既有 512 基线全绿、新增测试全绿。
