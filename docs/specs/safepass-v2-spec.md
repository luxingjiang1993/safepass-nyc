# SafePass NYC — Phase 2 Spec v2（M1 eval 套件 → M4 部署）

> 状态：待 `/to-tickets` 拆票。
> 输入：grilling Q1–Q10 已收官（决策落 `CONTEXT.md` 新词条 / `docs/roadmap.md` / `docs/phase2-skills.md`）。
> 前身：`docs/specs/safepass-nyc-mvp-spec.md` v1.2 为历史档案，正文不动；本文件是其 Phase 2 续篇。
> 语言：正文中文，章节名保留 spec 模板原文以便跨项目识别。

## Problem Statement

MVP 已收口（335 测试绿），但它是一个"只能在开发者自己机器上自嗨"的产品，从用户（项目作者，兼未来面试官视角的观众）角度看有四个过不去的坎：

1. **质量无法证明**：LLM 生成的建议、检索相关性、幻觉率没有任何度量。换生产模型（DeepSeek）是否有 eval 兼容性，没有证据。面试叙述里"质量好"是空话。
2. **数据是假的**：评级跑在模拟 NYPD 数据上，"真实 NYPD 数据驱动"这条产品故事不成立。
3. **上线即裸奔**：生产 LLM 没有日预算熔断，一次异常流量就能把 $5/日烧穿；超限后行为未定义。
4. **没有"真实运营"**：无公开 URL、无隐私/免责页、无真人用户证据。作品集叙述缺最后一块拼图。

## Solution

按 `docs/roadmap.md` 四个里程碑推进，每个里程碑有明确出口标准：

- **M1 eval 套件**：L1 确定性断言（进 pytest 基线）+ L2 LLM-judge（独立 `tests/eval/`，judge=dev 模型 DashScope，考官考生同源）+ 50 条金标（3 维覆盖矩阵）+ judge 版本锁定。出口：套件全绿，README 有三项指标基线。
- **M2 数据 + 成本**：真实数据 adapter（Socrata 单向管道，运行时永不直连外部 API）+ 熔断/限流/成本上报三件套（$5/日，超限走无 LLM 降级且明示）。出口：真实 fixture 入库；熔断可测；老测试不破。
- **M3 信任 + 用户**：隐私页/免责页 + 前端作品集级打磨 + 合成用户预检 + 真人 5 人访谈（发现 issue 化）。
- **M4 部署**：Hetzner + Docker + Caddy HTTPS + 域名 + UptimeRobot。出口：公开 URL 可访问；"真实运营五条"全部兑现。

## User Stories

### M1 — eval 套件与金标

1. As a 开发者，I want 金标查询集按「查询形态 × 5 核心警区 × 数据场景」3 维矩阵覆盖，so that 回归测试不会漏掉任何一种合法输入形态。
2. As a 开发者，I want 金标中越界查询占 20%，so that D12 诚实降级分支有持续的回归保护。
3. As a 开发者，I want 金标中低样本 ⚪ 与画像敏感场景合占 30%，so that 样本量门控与 ADR-0002（画像永不改评级）不被悄悄破坏。
4. As a 开发者，I want 每条金标带 L1 期望断言，so that 评级/越界/结构化字段的回归可以全自动跑在 pytest 基线里。
5. As a 开发者，I want 每条金标带 L2 期望标签（must_mention / must_not_claim），so that 生成质量可以逐条判定而不是凭感觉。
6. As a 开发者，I want L2 judge 改写在 CASE-openevals 的 evaluator 之上，so that 不从头造评估轮子。
7. As a 开发者，I want L2 judge 用 dev 模型（DashScope Qwen），so that 考官考生同源，评估口径稳定可复现。
8. As a 开发者，I want judge 的模型与提示词版本锁定，so that 评估基准不随依赖升级悄悄漂移。
9. As a 开发者，I want L2 套件独立放在 `tests/eval/` 且 judge 调用走 cassette 离线回放，so that 评估在 CI/离线环境可跑。
10. As a 开发者，I want README 记录三项指标基线（路由准确率 / groundedness / 幻觉率），so that 质量叙述有数字可查。
11. As a 项目作者，I want 用 eval 套件单独验证 DeepSeek 生产模型的兼容性，so that 换模型是"跑了评估"的决定，不是赌博。
12. As a 面试官视角的观众，I want 看到「L1 确定性断言 + L2 LLM-judge」的两层评估架构，so that 我理解这个产品如何控制生成质量。

### M2 — 真实数据与成本三件套

13. As a 运营者，I want 从 NYC Open Data（Socrata API）拉取真实 NYPD 犯罪数据，so that 评级建立在真实数据上。
14. As a 运营者，I want adapter 是手动/月更运行的离线脚本，so that 运行时零外部依赖、可复现性不破。
15. As a 运营者，I want 入库前校验（缺字段 / 时间越界 / 警区不在清单）不合格即拒收，so that 脏数据不会静默污染评级。
16. As a 运营者，I want 真实数据落 `fixtures/nypd_real/` 且来源可溯，so that 数据资产符合 resource-manifest 的诚实护栏。
17. As a 运营者，I want 日预算熔断挂在 LLM 客户端接缝上（生产 $5/日），so that 预算超限时当天剩余请求自动走无 LLM 降级。
18. As a 用户，I want 降级响应明示（结构化数据照出、建议降级为模板文本且明确标注），so that 我绝不会把模板建议当成 AI 分析。
19. As a 运营者，I want 限流与成本上报（文件级日志）随熔断一起落地，so that 烧钱之前先有刹车和里程表。
20. As a 开发者，I want 熔断行为可注入 fake client 测试，so that "超限降级"是测试断言而不是口头承诺。
21. As a 项目作者，I want 老测试在接入真实数据后不破，so that M2 是增量演进不是重写。

### M3 — 信任面与用户证据

22. As a 访客，I want 隐私页说明画像零持久化、零上传，so that 我敢填个人情境。
23. As a 访客，I want 免责页说明数据口径与免责声明，so that 我知道这份分析的边界。
24. As a 访客，I want 前端达到作品集级打磨（排版、空态、错误态、移动端可读），so that 这个产品看起来值得信任。
25. As a 项目作者，I want 合成用户在真人访谈前做预检，so that 访谈脚本先被低成本地戳一遍。
26. As a 项目作者，I want 合成用户产出只作开发参考，so that 它永远不会冒充真人证据。
27. As a 项目作者，I want 5 人真人访谈的发现 issue 化，so that 反馈进入正常 triage 流程而不是散落在笔记里。
28. As a 面试官视角的观众，I want 看到「合成用户预检 + 真人访谈」的证据链，so that 用户研究部分可信。

### M4 — 部署与真实运营

29. As a 运营者，I want 单一 Dockerfile 打包全应用（stdlib 前端 + pipeline），so that 部署形态与"零服务架构"故事一致。
30. As a 运营者，I want Caddy 自动 HTTPS + 自有域名，so that 公开 URL 是正式产品形态。
31. As a 运营者，I want 生产环境注入 DeepSeek 客户端（OpenAI 兼容端点，env 配置），so that 线上生成型 Agent 跑生产模型。
32. As a 运营者，I want UptimeRobot 外部探活，so that 宕机有人告诉我而不是等用户抱怨。
33. As a 运营者，I want "真实运营五条"全部兑现，so that "真实在线运营"这句叙述成立。
34. As a 项目作者，I want 部署配置（Dockerfile/Caddyfile）进仓库且有静态校验，so that 基础设施可 review 可复现。
35. As a 面试官视角的观众，I want 仓库即简历（spec/ADR/票据三件套 + 干净 commit 历史），so that 我不需要演示也能被评估。

## Implementation Decisions

### 全局架构

- **接缝不变**：行为面唯一接缝仍是 `execute_query(查询文本, 会话画像, 会话状态)`。Phase 2 新增三个边缘接缝，均不破坏既有注入模式：
  1. 成本熔断挂在 `LLMClient` 协议注入点（包装器模式，测试注入 fake client 记数）；
  2. 数据 adapter 的 HTTP 层可注入（Socrata 响应用录制 fixture 回放）；
  3. L2 judge 是独立可注入客户端（走 cassette）。
- **配置集中**：新增阈值（限流窗口、校验规则、eval 档位）一律进 `config/app.yaml`，代码经 `config_loader` 读取；`token-budget.json` 承载日预算（生产 $5/日）。红线不变：阈值字面量不出 `config/app.yaml`（fixture 例外）。
- **红线沿用**：LLM 不参与评级/可信度/越界判定；禁服务型数据库；持久化=文件；测试离线可跑。

### M1 — eval 套件

- **金标（Golden Set）**：50 条人工标注基准查询，落 fixture 文件。覆盖矩阵：查询形态（新查询/对比追问/细节追问/越界，越界 20%）× 5 核心警区 × 数据场景（正常/低样本 ⚪/画像敏感，后两者合占 30%）。每条带 L1 期望断言 + L2 期望标签（must_mention/must_not_claim）。
- **L1**：金标的确定性断言参数化进 `tests/` 现有 pytest 基线，打 `execute_query`，断言契约字段（评级/可信度/越界标记/结构化字段）。零新增接缝。
- **L2**：独立 `tests/eval/` 目录。evaluator 改写自参考代码 `可用来参考的代码案例/CASE-openevals使用`（groundedness/hallucination/answer-relevance 等 evaluator 的改写，来源路径逐组件标注）。judge = dev 模型（DashScope），judge 调用走 cassette 离线回放；judge 模型名 + 提示词模板版本锁定（进 config）。
- **指标**：套件产出三项指标——路由准确率（L1）、groundedness（L2）、幻觉率（L2）——写入 README 作为基线。
- **生产模型验证**：同一套件可指向 DeepSeek 跑兼容性验证（人工或受限环境执行，结果登记 README），不阻塞离线基线。

### M2 — 数据 adapter 与成本三件套

- **数据 adapter**：`scripts/fetch_nypd.py`，单向管道：Socrata API → 校验 → 落 `fixtures/nypd_real/`。手动/月更运行，运行时永不直连外部 API。入库校验：缺字段 / 时间越界 / 警区不在清单 → 拒收并报告。来源标注落盘（resource-manifest §A 诚实护栏）。
- **成本熔断（Cost Fuse）**：包装 `LLMClient` 的熔断器，日预算从 `token-budget.json` 读（生产 $5/日）。超限后当日剩余请求走无 LLM 降级：结构化数据照出、建议降级为模板文本，响应必须明示降级、不静默。
- **限流 + 成本上报**：请求级限流（窗口参数进 config）；成本上报走文件级方案（JSONL 成本日志落盘），不引入 Langfuse/LangSmith 进运行时。
- **真实数据切换**：真实 fixture 入库后，prod 数据路径切换到 `fixtures/nypd_real/`（config 数据目录切换），mock fixture 保留为测试资产；`city_mean_per_100k` 需按真实数据重算并回填 config（评级可复现性约束）。

### M3 — 信任面与用户证据

- **隐私页 / 免责页**：前端新增两个静态页路由（继续 stdlib http.server + 服务端渲染，零新依赖）。隐私页：画像零持久化、零上传、会话随进程消失。免责页：数据口径、免责声明、紧急资源。
- **前端打磨**：作品集级排版、空态/错误态文案、移动端可读性。紧急红页与画像侧栏（issue 11+12 已交付）风格统一。
- **合成用户（Synthetic User）**：LLM 扮演用户 persona 的预检脚本（dev-only，走输出控制管线模式），用于访谈脚本预检与金标输入扩充。产出标注"开发参考"，不替代真人证据。
- **真人访谈**：5 人（项目作者执行，agent 不入循环）；发现清单 issue 化后走五标签 triage（`docs/agents/triage-labels.md`）。

### M4 — 部署

- **容器化**：单一 Dockerfile（多阶段：deps → index 构建 → runtime），全应用一个容器，与零服务架构一致；docker-compose 可选（仅本机便利，生产单容器）。
- **HTTPS**：Caddy 反代，自动证书；域名解析至 Hetzner VPS。
- **生产模型接线**：前端 app 的 `llm_client=None` 默认值在生产容器内经 env（`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`）注入 DeepSeek 客户端；dev/test 继续 fake/cassette。
- **监控**：UptimeRobot 外部探活公开 URL；文件级运行/成本日志持续落盘。
- **真实运营五条**（本 spec 对 roadmap M4 出口标准的操作化定义）：
  1. 公开 HTTPS URL（自有域名）外部可访问；
  2. 生产路径由真实 NYPD 数据驱动（adapter 数据生效，非 mock）；
  3. $5/日成本熔断在线生效，超限降级明示；
  4. UptimeRobot 监控在线 + 运行/成本日志可查证；
  5. 隐私页与免责页公开可访问。

## Testing Decisions

- **好测试的标准**：只测外部行为，不测实现细节。L1 断言只碰 `execute_query` 返回契约的字段与值；L2 只碰「输入金标 → judge 分数 → 指标聚合」；熔断测试只碰「注入 fake client + 预算状态 → 响应行为」。
- **L1**：金标参数化进 pytest 基线（prior art：`tests/test_skeleton.py` 的契约断言、`tests/test_rating_engine.py` 的档位断言）。唯一判定仍是 `pytest tests/ -q` 全绿。
- **L2**：`tests/eval/` 独立目录（不进默认基线，单独 marker/命令跑）；judge 走 cassette（prior art：`safepass/llm_client.py` 的录制回放与指纹校验）。指标聚合结果与 README 基线对账。
- **成本熔断**：注入记数 fake client + 操纵预算状态文件，断言：超限后 LLM 调用数不再增长、降级响应带明示标记、结构化数据照出（prior art：`tests/test_degraded.py` 的降级断言模式）。
- **数据 adapter**：Socrata 响应用录制 fixture 注入 HTTP 层；断言校验拒收路径（缺字段/时间越界/警区不在清单）与入库产物结构（prior art：`tests/test_fixtures.py` 的 32 项 fixture 自检）。
- **前端页面**：沿用 `tests/test_frontend_render.py` / `tests/test_frontend_app.py` 的渲染与目录快照模式。
- **部署**：Dockerfile/Caddyfile 静态校验（关键指令存在性、端口一致性）+ 冒烟脚本（容器起得来、首页 200）；真机验收属人工出口标准，不进 pytest。

## Out of Scope

- Phase 3 候选（`docs/roadmap.md`）：地理编码扩覆盖（Google Geocoding 直连）、Langfuse 自托管、金标 50→150。
- 登录体系与画像持久化（CONTEXT.md：随登录体系在后续 Phase 设计）。
- 服务型数据库、MCP、LangChain/Langfuse SDK 进运行时（`docs/phase2-skills.md` 明确不用）。
- 多语言（英文界面）、移动端原生应用。
- MVP spec v1.2 的任何修订（历史档案）。

## Further Notes

- **拆票**：`/to-tickets` 将本 spec 拆为 tracer-bullet 票据（M1–M4），每张声明 blocking edges 并标注执行方式（`/implement` 默认 / `/ralph` 仅限机械票）。
- **Ralph 候选票**：cassette 批量补录、adapter 入库运行、金标批量断言生成——有明确布尔完成承诺的机械票。
- **token 预算**：`token-budget.json` 的 `daily_cost_budget_usd` 在 M2 落熔断时设为 5。
- **参考代码 provenance**：凡改写自 `可用来参考的代码案例/` 的组件（L2 evaluator 为主），实现时逐组件标注来源路径（`docs/phase2-skills.md` 硬性要求）。
- **完成承诺对齐**：Ralph 任务登记 `RALPH.md` 时，完成承诺引用本 spec 的出口标准。
