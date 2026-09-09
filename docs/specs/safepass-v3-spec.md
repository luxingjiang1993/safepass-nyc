# SafePass NYC — Phase 3 Spec v3（波 1：真 AI 建议 + 质量咬合 + 首屏决策 + T2 杀手锏）

> 状态：**波 1 已收口**（2026-09-09）；**波 2 第一刀已收口**（同日）；**波 2 第二刀已收口**（2026-09-10）。GitHub `#16`–`#34` 已关；唯一判定 `python -m pytest tests/ -q` = **735** 绿。P4 演示门闩 `#1/#2/#3/#6/#16/#18` 为真；看板 `#17`（N2 基线对照）已绿。权威 spec = `docs/specs/safepass-v3-wave2-second-knife-spec.md`。HEAD 波 1：N1 `1cf5295`、N3 `b0b0f27`。**禁止再开/再做 N1 骨架、N3 一键复现、N2/A4 第一刀、第二刀 C1/B4/N4/D5/C6。** 波 2 其余票与后 100 分三模式未经点名不得自行开票。
> 输入：10 张票（GitHub #16–#25，本地镜像 `.scratch/safepass-phase3-tickets/issues/`）+ `docs/portfolio-100-execution-plan.md`（唯一执行主轴，仅参考；未切票部分以该文为准）文首补丁 P6（Phase 3 开赛定案，grilling 2026-09-07）+ `docs/adr/0003-suggestion-generation-architecture.md`。
> **权威顺序：票 > 本 spec > 执行计划正文**。切票时逐张经 grill-me-with-docs 复盘，票文 = 派票瞬间的最终裁决；本 spec 只是 10 张票的可读总览与执行投影，不是独立契约——与票冲突处以票为准，票与执行计划冲突处亦以票为准（执行计划 §2/§2.9/§7 原文可能未被切票逐字采纳）。
> 前身：`docs/specs/safepass-v2-spec.md`（M1–M4 已交付）为历史档案，正文不动；本文件是其 Phase 3 续篇。
> 语言：正文中文，章节名保留 spec 模板原文以便跨项目识别。

## Problem Statement

MVP + Phase 2 已把产品推到「数据评级 + eval + 真实运营」的确定性高地上（波 1 开工时约 587 测试绿），但从作品集轴看当时还有五个过不去的坎：

1. **用户看不到「AI」**：建议仍是 `safety_general` 配置模板的重排，one_liner 是「区域：灯色」；`intel.search(query)` 可测但用户感不到。产品在观众眼里是数据仪表盘，不是 AI 应用（Hamel/Karpathy）。
2. **质量度量测错对象**：L2 groundedness/幻觉率测的是模板路径的输出，Skill/生成物一旦接入，现有度量就「测模板自嗨」；指标只有单个维度，没有 actionability / specificity / 矛盾检测。
3. **首屏是资料页不是决策页**：结论与建议折叠在图表/社区信息之后，5 秒做不了决策；后端已支持的追问/对比能力没有露出入口，用户得自己会写高级查询。
4. **叙事与代码会脱节**：「AI 建议」字样的对外承诺（README/CONTEXT/隐私页三处）与实现、与 ADR-0003 画像口径必须逐字一致，否则是面试地雷。
5. **审阅者视角的信任赤字（T2）**：陌生环境能不能一键复现、话术/注入能不能篡改评级，这两件事没有证据之前，「作品只能作者机器跑 / 评级是 LLM 拍的」的先验怀疑无法反驳。

## Solution

按执行计划 **第 1 波 + N1/N3 骨架**（即 P6 停点范围，10 张票）推进，四组 + 收口：

- **A 组 — 建议生成主路径**（ADR-0003 四定案：LLM 措辞 + 数据定调 / 画像不出进程 / one_liner 确定性 / 两路径对照）：
  - **A1 Suggestion Skill**：3–5 条建议正文 = LLM 措辞；输出契约强制 `grounds` + 数据钩子；`llm_client=None`/熔断 → 明示模板降级；评级比特级不变。
  - **A2 检索进建议**：`intel.search(query)` top-3 注入建议上下文，`suggestion_grounds` 填非空；校验器拒绝检索 chunk 的间接注入（改不了 rating）。
  - **A3 one_liner 确定性钩子化**（✅ 已合并）：LLM 不写 one_liner；确定性模板 + 钩子词典（只进 `config/app.yaml`）填空；字数上限 + 黑名单。
- **B 组 — 质量咬合生成物**：**B1** 金标 `must_mention`/`must_not_claim` 对准建议；同一金标跑 Skill 路径与模板路径，**Skill 主指标 ≥ 模板才收口**，两路径对照数字进 README；模板降级路径单独 marker 不计主指标。**B2** 增补 actionability / specificity / 矛盾检测（矛盾 = 确定性核对，LLM 不判定）。
- **D 组 — 首屏决策**：**D1** 首屏 = 评级 + one_liner + 建议 + 降级横幅，图表/community/来源默认折叠，窄屏一屏可决策。**D2** 追问/对比芯片（细节→`detail`、对比→`comparison`，复用 follow_up 预填，紧急页不显示）。
- **E1 — 波 1 收口票**：skills/、CONTEXT.md、README 三处对建议主路径的描述一致；隐私页口径与 ADR-0003 一致（一字不改）。
- **N 组 — T2 杀手锏骨架**：**N1** ≥3 条「话术改不了 rating」攻击金标断言 + 拦截率报表工件（独立于主金标）；**N3** 一条命令 Windows 无 key 跑通 5 条固定 query（安全 + 越界 + 紧急）。

**出口标准（P4 演示门闩）**：波 1 收口日（2026-09-09）验收看板 #1/#2/#3/#6/#16/#18 已为真；#17（N2）于波 2 第一刀收口（`#26`）。波 2 其余起按面试日程滚动决策（P6 停点），波 3/4 不预支。未经用户点名不得把 N4–N6 或波 2 其余票当「还没做的第一刀」。

## User Stories

### A 组 — 建议生成主路径（A1/A2/A3）

1. As a 用户，I want 建议正文来自受约束生成的 Skill 而非模板重排，so that 我能看到 AI 应用的实质内容。
2. As a 用户，I want 无 LLM / 熔断降级时仍拿到合法契约且响应明示降级，so that 我绝不会把模板建议当成 AI 分析。
3. As a 开发者，I want 注入真实/fake client 时输出可区分，so that 「Skill 生效」是可测断言而不是信仰。
4. As a 用户，I want 建议旁携带可解析的依据（`suggestion_grounds: [{doc_id, quote}]`，无依据时标「通用建议」），so that 每条可核对断言都有出处（S1 Perplexity 形态）。
5. As a 用户，I want 同一区域问「诈骗」与问「晚上安不安全」得到不同建议，so that 检索是产品路径而不是简历关键词。
6. As a 用户，I want 页面最显眼的一句话（one_liner）是含数据钩子的人话标签，so that 5 秒内可核对、可决策（S2 Walk Score 形态）。
7. As a 开发者，I want 金标断言 one_liner 含至少一类允许的数据钩子且与 charts/ratio 不矛盾，so that one_liner 永远可证伪。
8. As a 隐私视角的用户，I want 六维画像永不进入发给模型供应商的请求体，so that 隐私页「零上传」已审计口径一字不改（ADR-0003）。
9. As a 开发者，I want 评级/可信度/越界判定零 LLM 参与、比特级不变（既有 invariance 测试绿），so that D12 确定性后置不被生成层破坏。
10. As a 开发者，I want 校验器拒绝「检索 chunk 试图改写评级/取消免责」的间接注入，so that RAG 引入不放大注入面（与 N1 交叉）。

### B 组 — 质量咬合生成物（B1/B2）

11. As a 面试官视角的观众，I want L2 groundedness/幻觉率测的是 Skill 输出，so that 数字反映真实主路径（Hamel：指标能打假）。
12. As a 项目作者，I want 同一金标的两路径对照（Skill vs 确定性模板）数字进 README，so that 「LLM 值得上」是实测结论不是预设（Skill 主指标 ≥ 模板才收口）。
13. As a 开发者，I want 模板降级路径单独 marker、不计入主 groundedness，so that 降级表现不稀释主路径质量口径。
14. As a 用户，I want 建议「能照做」（actionability）、「提到本区数据」（specificity）可量化，so that 质量仪表盘不止一个虚荣指标。
15. As a 用户，I want 建议文本与 charts/ratio 的「夜间更安全」类矛盾被确定性核对抓住，so that 数据自洽不靠 LLM 自觉。

### D 组 — 首屏决策（D1/D2）

16. As a 用户，I want 首屏 = 评级 + one_liner + 3 条建议 + 降级横幅，图表/community/来源默认折叠，so that 打开结果页 5 秒能决策（Rauch）。
17. As a 开发者，I want 快照/结构断言锁首屏层级，so that 信息架构不会悄悄退化。
18. As a 用户，I want 结果页露出「女生晚上呢？」「和法拉盛比呢？」芯片，so that 追问/对比能力可发现、不靠我会写高级查询（S7 Life360）。
19. As a 开发者，I want 芯片点击后契约类型符合预期（细节追问 → `detail`、对比追问 → `comparison`）有集成测试，so that 前端入口与后端能力不脱钩。
20. As a 紧急场景的用户，I want 紧急页保持极简、不显示芯片，so that 紧急路径不被干扰。

### E1 — 叙事与代码对齐

21. As a 面试官视角的观众，I want skills/、CONTEXT.md、README 三处对建议主路径的描述与代码一致，so that 「文档承诺 > 代码」的地雷不存在。
22. As a 隐私视角的用户，I want README/隐私页不得暗示画像参与 LLM 个性化（零上传口径），so that 对外承诺与实现逐字一致。

### N 组 — T2 杀手锏（N1/N3）

23. As a 面试官视角的观众，I want ≥3 条攻击金标证明「话术改不了 rating」且故意放松校验会红，so that 评级的安全性是可运行证据。
24. As a 陌生环境中的审阅者，I want 一条命令在 Windows 无 key 环境跑通 5 条固定 query（安全 + 越界 + 紧急）并打印契约摘要 + 打开本地页，so that 作品不被怀疑「只能作者机器跑」。

## Implementation Decisions

### 架构（ADR-0003，效力优先于执行计划正文）

- **LLM 措辞 + 数据定调**：`SuggestionSkillOut`（P2 草案正式化，以 `contracts`/Skill schema 为准）——

  | 字段 | 约束 |
  |------|------|
  | `one_liner` | A3 确定性模板产出，**LLM 零参与**；含允许的数据钩子 |
  | `suggestions` | `list[str]` 3–5 条；过业务校验/黑名单 |
  | `suggestion_grounds` | `list[{doc_id, quote}]`；A1 字段必立（可空 = UI 标「通用建议」），A2 起非空可测 |
  | 禁止字段 | 不得含 `rating`/`confidence`/越界判定——仅确定性引擎写出 |

- **画像不出进程**：Skill 输入打包不含六维画像（A1/A2 硬项）；画像只在本机确定性加权/排序；隐私页「零上传」口径不改。
- **one_liner 确定性**：A3 模板填空 + 钩子词典；钩子/黑名单/字数阈值（30 字，AC-005）只进 `config/app.yaml`（红线 1）。
- **降级**：熔断 / `llm_client=None` → 明示模板降级（复用既有 `output_pipeline` 生成→解析→校验→有限重试；仍不过降级）。
- **community_info 只走 meta 警区锚定，不参与检索排序**（CLAUDE.md 棘轮行，A2 禁止触碰）。

### 执行矩阵与文件纪律（P6/P1/P5）

- 槽位：槽 1 = A1/D1/N3；槽 2 = A2/D2；槽 3 = A3/B1/N1；槽 4 = B2/E1（B2 先、E1 后）。A1→A2/B1/E1；A2→B1/N1/A3（pipeline 让位）；D1→D2；B1→B2；B2→E1。
- 方式：`/ralph` 仅限机械票（A3 ✅、N3），其余 `/implement`（人工在环）。headless 注意 `env -u ANTHROPIC_MODEL`。
- 单票 ≤5 代码文件 + ≤5 测试文件；禁止顺手重构/升级依赖（P1）。
- 波 1 文件白名单（P5）：`pipeline.py`、`contracts.py`、`output_pipeline.py`、`safepass/skills/`、检索模块、结果页模板与静态资源、README/CONTEXT（仅 E1）、tests/eval/ 与 fixture、`config/app.yaml` + `config_loader`。波 1 不准动：前端栈、LangChain/LlamaIndex/服务型 DB、扩警区、ADR-0001 评级公式。
- A2 开工第一动作 = 对金标 `must_mention` 事实跑召回探针（top-3 命中），结果落盘再建；不过则把 C8 知识库加厚提上滚动日程。

### Eval 与数据（B1/B2/N1）

- 金标修订：`fixtures/eval/golden_set_v1.json` 的 `must_mention`/`must_not_claim` 对准建议与 one_liner（B1 独占期，B2/E1 等合并）。
- 两路径对照：B1 落地 Skill/模板开关 runner，README 质量基线表主指标 = Skill 路径 + 两路径对照表；B2 三类新维度（actionability/specificity/矛盾）与 B1 同表；矛盾核对 = 确定性实现（数据事实 vs 建议文本），LLM 判定禁止。
- **cassette 棘轮**：改提示词/口径/数据世界（judge 请求内嵌证据文本随数据漂移）→ 必须重录 L2 cassette（`python scripts/record_l2_cassette.py`，需网络 + key + 预算）并跑 `python -m pytest tests/eval -q`；重录禁用模型混用（dev = qwen-flash）。
- N1 骨架：独立攻击 fixture 文件，与主金标分离；评级断言须带「故意放松校验会红」负向验证。

## Testing Decisions

- **唯一判定不变**：行为回归 `python -m pytest tests/ -q` 全绿（波 1 收口基线 **663**，随票递增；含 A3 one_liner 钩子断言 `tests/test_a3_one_liner_hooks.py` 四类：金标精确相等/允许钩子集合成员/与 `rating_explainable_basis` 逐字一致/⚪ 零钩子）。基线按 conftest `collect_ignore` 不含 `tests/eval`。
- **L2 套件**：`python -m pytest tests/eval -q` 独立跑（judge 走 cassette 离线回放；qwen-flash 重录后 groundedness 0.980 / relevance 1.000 / 幻觉率 0.000）。B1 合并后主指标咬合 Skill 输出；重录必须遵守 cassette 棘轮。
- **每票 DoD 布尔化**：Ralph 任务登记 `RALPH.md` 时引用本 spec 出口标准；N3 完成承诺 = Windows 无 key 实跑 `python scripts/demo_queries.py`（与 E7 合并设计避免双入口）。
- **负向验证先行**：N1「话术改不了 rating」须演示放松校验 → 攻击金标红；B1 模板降级路径不计主指标。
- **好测试标准沿用**：只测外部行为（`execute_query` 契约字段/值），不测实现细节（v2 spec Testing Decisions 同款）。

## Out of Scope

本 spec 只承诺波 1（10 张票）目标态。以下均不在承诺内：

- **执行计划 §3–§5 波 2–4 全部**（A4 溯源行、A5 画像差异、B3–B5、C1–C8、D3–D9、E2–E7、F1–F4、G1–G4，约 40 项）与 §7 未切包（N2 基线对照、N4–N6）——P6 停点：波 2 起按面试日程滚动决策；原文仍在 `portfolio-100-execution-plan.md`，随时可按 §9 模板补票。
- N1 攻击类别再扩面（骨架已交付：9 条金标 + `docs/n1-injection-report.md`，issue #24）——完整分类学仍属波 2 可选，不是缺口。
- roadmap.md「Phase 3」旧条目（地理编码扩覆盖 / Langfuse 自托管 / 金标 50→150）——另行 grilling 后才会进场。
- 非代码轴：公开 URL 运维、真人访谈、demo 口播（执行计划明示不含；M4 已交付项归 v2 spec）。
- 换前端栈、扩警区、ADR-0001 评级公式修订、服务型数据库、运行时直连外部数据 API（P5 / 红线 / v2 spec Out of Scope 同款）。
- MVP v1.2 与 v2 spec 的任何修订（历史档案）。

## Further Notes

- **拆票已完成**：GitHub issues #16–#25（波 1，本地 `.scratch/safepass-phase3-tickets/`）；波 2 第一刀 #27/#28/#26（本地 `.scratch/safepass-phase4-tickets/`）；波 2 第二刀 #30–#34（本地 `.scratch/safepass-wave2-second-knife/`）。与执行计划对应关系见各票「来源」。禁止整份 1100+ 行计划塞 agent 上下文（P0）。
- **现状台账**：波 1 十票 + 波 2 第一刀 `#27`/`#28`/`#26` + 第二刀 `#30`–`#34` 均已合并并关 GitHub issue。L2 cassette 已按 qwen-flash 重录（C1b `#33` 因 `rating_rationale` 再录一次）。模型全线 qwen-flash。唯一判定 735 绿。下一动作 = 用户点名波 2 其余或后 100 分；不是第 4 波或三模式。禁止重做 N2/A4/C1/B4/N4/D5/C6。
- **golden 口径**：B1 修订 golden_set_v1.json 时，优先覆盖现有金标已覆盖的追问形态（细节/对比），不发明新查询类型（D2 芯片文案同源）。
- **完成承诺对齐**：RALPH.md 登记新任务时，完成承诺引用本 spec 的出口标准与「唯一判定」命令（`python -m pytest tests/ -q`，直跑 `pytest` 会 ModuleNotFoundError）。
