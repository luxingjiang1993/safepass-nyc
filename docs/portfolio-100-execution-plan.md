# SafePass → 作品集 100 分：合并执行计划（coding agent 版）

> **本文地位**：作品集轴（技术 + 产品 / demo 本体）的**唯一执行主轴**。  
> **不含**：公开 URL、运维上线、真人访谈、demo 口播剧本、英文现场讲解、算法白板等非代码项。  
> **与 Phase 2 spec 关系**：`docs/specs/safepass-v2-spec.md` 仍管 M1–M4（eval/数据/信任/部署）。  
> 本计划管的是「满分清单 + T2 锁稳代码项 + 高标准工艺约束」——可与 M1/M3 前端票并行，但 **A1/A2 未落地前不得在对外文案写「AI 建议」**（见 E1）。  
> **「100 分」定义**：硅谷 LLM 应用 / vibe coder 作品集轴封顶（此前主战线约 84–88）；职级轴 Staff/大厂 Senior 另论。

---

## 文首补丁（Agent 开干前必读 · 只追加不删正文）

> 来源：十人模拟评审共识（Karpathy / Willison / Huyen / Hamel / Swyx / Jason Liu / Pocock / Rauch / Howard / Carmack）。  
> **效力**：与下文冲突时，**补丁约束 agent 行为与派票方式**；大神各票 **目标/缺口/做法/DoD/加分原文不得删改**，仅可被本补丁收紧（更早做、更窄改、多一道门）。

### P0. Default path（先读什么）

```
1. 本「文首补丁」全文
2. §8 第 1 波甘特（只看波1）
3. 复制 §9 派票模板 → 只粘贴【单票 ID 那一节】大神原文
4. 按需打开 §1.1 / §1.2【该票相关行】，禁止把本文件 1100+ 行整份塞进 agent 上下文
5. 再动手改代码
```

**禁止**：一上来精读全部 Atlas / 波 3–4 / 竞品长表。

### P1. 派票切片 + 改动半径（Pocock / Carmack）

| 规则 | 要求 |
|------|------|
| 上下文 | **一票一份上下文**：只含该 ID 节 + Borrow 相关行 + 本补丁；禁止整份 execution-plan |
| 波 1 文件半径 | 单票 **最多改 5 个文件**（测试文件另计最多 +5）；超出则拆票 |
| 禁止顺手重构 | 不改无关模块、不升级依赖、不「顺便」换框架 |
| Provenance | 改写自 CASE-* 或 §1.2 模式须标注来源 |

### P2. A1 最小契约草案 + 铁三角表结构（Jason Liu / Chip Huyen）

实现 A1 时须先锁定（可先空实现，但**字段名勿漂**）：

**`SuggestionSkillOut`（草案，正式以 `contracts` / Skill schema 为准）**

| 字段 | 类型（示意） | 说明 |
|------|--------------|------|
| `one_liner` | `str` | ≤ 既有字数上限；须含允许的数据钩子（见 A3） |
| `suggestions` | `list[str]` | 3–5 条；过业务校验 / 黑名单 |
| `suggestion_grounds` | `list[{doc_id, quote}]` | 可选；无则 UI 标「通用建议」；A2 起应可测非空差异 |
| （禁止字段） | — | **不得**含 `rating` / `confidence` / 越界判定；上述仅确定性引擎写出 |

**质本延迟表（A1 合并后必须落仓库，数字可先测后填）**

| 路径 | P50 | P95 | 估 token/次 | 备注 |
|------|-----|-----|-------------|------|
| 无 LLM（`llm_client=None`） | TBD | TBD | 0 | 模板建议 + 明示降级 |
| 有 Skill + 检索 | TBD | TBD | TBD | 主路径 |
| 熔断后 | TBD | TBD | 0 新增 LLM | 调用次数不增加（E4） |

超阈规则：阈值进 `config`；有数之后 `pytest -m perf`（或等价）可红。

**A1 DoD 横切（验收审计 #5-①，隐私口径联动）**：A1 落地时若画像/persona 进入 Skill 的 LLM 调用（请求发送给模型供应商 = 第三方服务），**必须同步修订隐私页「零上传」口径**（`frontend/render.py` `render_privacy` 的「画像不会发送给任何第三方服务」+ `config/app.yaml` `profile.notice`）——对外承诺与实现逐字一致；改实现不改口径 = 红线。当前实现画像确实零 LLM 零上传（审计 #8 已证），本条为 A1 的前置约束。

### P3. A2 当日启动 N1 骨架（Hamel）

| 时机 | 要求 |
|------|------|
| `A2` 合并当日（或紧随的下一票，不得拖过波1收口） | 落地 **N1 最小集**：至少 3 条攻击金标断言 **话术改不了 `rating`** |
| 完整注入报表（武器/间接注入/覆盖免责等） | 仍按 §7 N1 DoD，可在波1末–波2 补满 |
| 与 A2 交叉 | 检索 chunk 间接注入校验与 N1 金标交叉，不互相替代 |

### P4. 对外演示门槛子集（Jeremy Howard）— 未齐也可示人

**可对外演示（作品集轴）** 当且仅当下列验收看板项为真（编号见 §6）；其余项后台继续，**不得**阻塞演示：

| 看板 # | 摘要 |
|--------|------|
| #1 | 主路径建议来自 Skill，且检索可测地改变建议 |
| #2 | 评级/越界/紧急仍零 LLM；画像不变评级可证明 |
| #3 | L2 主指标测生成物（含 actionability/specificity/矛盾） |
| #6 | 首屏可决策 + 追问芯片可发现 |
| #16 | 注入：至少「改不了 rating」骨架绿（见 P3） |
| #17 | 基线对照页可稍后波2；**演示日前尽量有 N2 初稿**，无则口头说明「对照进行中」并记 issue |
| #18 | 一键复现：安全 + 越界 + 紧急（N3） |

**明确**：波 3–4、a11y、引用高亮、失败分类学等 **不是** 演示门闩。

### P5. 波1 最小文件白名单（Karpathy）— 防 Atlas 带跑偏

波1 默认只准动下列集合（测试/cassette/金标夹具除外）；超范围须用户显式批准：

- `safepass/pipeline.py`（`_build_safety_result` / 建议装配）
- `safepass/contracts.py`
- `safepass/output_pipeline.py`
- `safepass/skills/`（或项目既有 skills 目录；新建须在本白名单内）
- 检索模块（`rg "def search"` 定位到的 intel/search 文件，A2）
- 结果页/首页 **模板与静态资源**（D1/D2；stdlib SSR 既有入口）
- `CONTEXT.md` / `README*`（仅 E1 一致性，禁止借机改产品范围）
- `tests/`、`tests/eval/`、相关 fixture（B1/B2/N1/N3）
- `config/app.yaml` + `config_loader`（仅黑名单/钩子/必要开关；**阈值字面量不进 py**）

**波1 不准动**：换前端栈、引入 LangChain/LlamaIndex/服务型 DB、扩警区、改 ADR-0001 评级公式。

---

## 0. 计划怎么用（给 coding agent）

### 0.0 Agent 友好性（读计划时的导航）

| 你想知道 | 去哪一节 |
|----------|----------|
| **开干默认路径 / 改动半径 / 演示门槛** | **文首补丁 P0–P5（最先读）** |
| 做什么、DoD 原文 | §2–§5、§7 |
| **去哪借鉴（产品 URL）**、改哪些文件、禁止抄什么 | **§1.1 Borrow Atlas** |
| **去哪借鉴（高星 GitHub）**、借鉴什么 / 别抄什么 | **§1.2 GitHub Borrow Atlas** |
| 只看 S# 短名 | §1 表（不够开工，必须回 §1.1 + 相关 §1.2） |
| 派票格式 | §9（含 Borrow 必填栏；可同时填 §1.1 与 §1.2）；**须遵守文首 P1** |

### 0.1 三层结构（禁止搞反）

| 层 | 是什么 | 不是什么 |
|----|--------|----------|
| **L0 宪法** | `CLAUDE.md` + ADR-0001/0002 + 唯一接缝 `execute_query` | 不可被本计划推翻 |
| **L1 主轴** | 下文 **§2–§5 波次** = 大神满分清单全文（目标/缺口/做法/DoD/加分） | 不可用「竞品偷取表」替换 |
| **L2 工艺约束** | **§1.1**（产品味道）+ **§1.2**（开源实现模式）+ Craft S# | 只改「做成什么样」，不增 P0 epic；无 URL/路径则不算可执行 Craft；**禁止**为借鉴而把 LangChain/LlamaIndex/服务型 DB 塞进主路径 |

### 0.2 相对旧「偷取表」的优化（必读）

1. **偷取表降级为 Craft Constraint**，不再冒充 backlog。  
2. **T2 代码杀手锏前移**：注入专测、裸 RAG 对照、一键复现 —— 绑在波 1 末 / 波 2 初，不挂到「有空再做」。  
3. **无竞品仍必做**整包沉到 **§7**，每张票仍可独立派发。  
4. **间接注入**：A2「检索进建议」的校验必须防 chunk 投毒（Jason Liu 刀），不只放在对抗金标里。  
5. **铁三角数字**：有 Skill 后重测，挂在 A1/E3 DoD，不只写散文。  
6. **够用就停**：波 4 是边际；波 1+§7 关键评测未绿，禁止提前啃 A8/动效。

### 0.3 红线 / Won't（做了反而难满 100）

| 不做 | 原因 |
|------|------|
| LLM 参与评级/越界/可信度 | 自毁核心卖点（D12 / ADR） |
| 为炫技上多 Agent 循环 / 重排层（无评测证明前） | 复杂度税 |
| 换 React/Next 大前端 | 偏离零服务叙事；ROI 低 |
| 盲目扩全市警区 | 稀释深度，变薄 |
| 运行时直连 Socrata / 重依赖可观测平台 | 破可复现与红线 |
| 路径级安全假装可做 | 诚实降级是资产 |
| 用合成用户冒充真人证据 | 诚信归零 |
| 抄 Citizen 实时 UGC 恐慌流 | 信任自杀 |
| 把 GeoSure 黑箱全球分 / 运行时 MCP 当评级源 | 破确定性评级 + fixture 可复现 |
| NeighborhoodScout 式 80 模型重做评级 | 无 eval 证明前禁止 |

### 0.4 唯一判定

- 行为回归：`pytest tests/ -q` 全绿（基线不破）。  
- 生成/评测：`tests/eval/`（及本计划新增 marker）按票 DoD。  
- **没有「看起来对了」**。

### 0.5 关键接缝与现状缺口（开工前默认事实）

- 唯一接缝：`safepass/pipeline.py` → `execute_query(...)`。  
- 现状：`_build_safety_result` 的建议来自配置 `safety_general` / `crowd_suggestions` 重排；`one_liner` 偏「区域：灯色」；`intel.search(query)` **未**喂进用户可见建议。  
- Skill / 输出控制：经现有 `output_pipeline`；熔断/`llm_client=None` → 明示模板降级。  
- 阈值/黑名单/警区：只活在 `config/app.yaml`，经 `config_loader`。

### 0.6 高标准对外叙事（只写 README/一页纸，不当 backlog）

> 评分工艺学 Walk Score，依据呈现学 Perplexity，情报结构学 Crisis24，场景维度意识学 GeoSure；评级坚持确定性，对标 Redfin 式诚实边界。

---

## 1. Craft Constraints（S# / T#）— 工艺参照，不是独立史诗

派票时在票尾附加一行：`Craft: S1, S3`（可选）。Agent **不得**为 S# 单独开「对齐 GeoSure」类票。

| ID | 源（高标准） | 偷的行为（改写） | 主要绑到 |
|----|--------------|------------------|----------|
| S1 | Perplexity | 建议/one_liner 旁可核对依据；无依据标「通用建议」；换 query 建议应变 | A2, A4, B1 |
| S2 | Walk Score | 分→固定人话标签；短、可核对；methodology 可读 | A3, C1, D1 |
| S3 | Crisis24 简报槽 | 首屏固定：评级 / 人话解释 / one_liner / 建议；细节折叠 | D1, D6 |
| S4 | GeoSure 维度意识 | 女性/夜间等进**建议与解释**，**不进**评级公式 | A5, C2 |
| S5 | SpotCrime methodology | 可审计：阈值、样本档、「分不代表什么」 | C1, C4, G3 |
| S6 | Redfin「不做」 | Kill list + must_not_claim + 免责同源 | E6, F1, B3, N1 |
| S7 | Life360 主路径 | 结论区清晰 + 追问芯片可发现 | D2, D5 |
| S8 | TripIt 风险偏好感 | 对比页「更在意总体/夜间/某类」改话术（规则即可） | A6 |
| S9 | Perplexity 点击溯源 | 依据→原文片段；失败降级 doc 名 | A8 |
| T1 | T2-A1 | 注入/越狱/间接注入专测；**改不了 rating** | 波1末 / §7 N1 |
| T2 | T2-A2 | 裸 LLM / 无约束 RAG / SafePass 三列对照 | §7 N2 |
| T3 | T2-A3 | 一键审阅者路径 ≤15 分钟 | §7 N3 |
| T4 | T2-A5 | 质×本×延迟铁三角 + 熔断可见 | E3, E4, A1 附件 |
| T5 | T2-A6/A7 | 模式名片 + Manager 一页纸（仓库文物） | G1 附属 |
| T6 | T2-A9 | 竞品诚实定位页 | G 附属 |

---

## 1.1 Agent Borrow Atlas（必读）— 去哪借鉴、改写进哪、禁止抄什么

> **诚实声明**：仅写「Craft: S1」对 coding agent **不够**。  
> 开工任一绑了 Craft 的票，必须按本表执行：**打开 URL / 读仓库路径 → 对照「观察清单」→ 只改写「偷」列 → 落点「改这些文件」→ 遵守「禁止」**。  
> 外部站只有**公开页文案/信息架构/方法论叙述**可借鉴；**禁止**粘贴闭源 JS/CSS/二进制进仓库。

### 1.1.0 本仓库优先（代码改写的第一站）

外部竞品教「产品味道」；**可运行的改写源优先本仓**：

| 用途 | 路径（以仓库根为基准；若目录未检出则先 `glob`/`dir` 确认） | 改写进 SafePass |
|------|--------------------------------------------------------------|-----------------|
| L2 judge / groundedness 等 | `可用来参考的代码案例/CASE-openevals使用/`（见 `docs/specs/safepass-v2-spec.md` M1） | `tests/eval/`；**逐文件标注 provenance** |
| 声明式评估参考 | `可用来参考的代码案例/CASE-投顾AI助手（效果评估）/deepeval_wealth_advisor.py` | 仅作评估维度灵感，不强制引入 deepeval 运行时 |
| Skill / 输出管线（已有） | `safepass/output_pipeline.py`、`safepass/contracts.py` | A1 扩展，不另起框架 |
| 建议装配现状（将被替换） | `safepass/pipeline.py` → `_build_safety_result` / `_personalized_suggestions` | A1/A2 主改点 |
| 检索 | `safepass/` 内 intel/search 相关模块（开工前 `rg "def search"` 定位） | A2 把返回 chunk 注入 Skill 上下文 |
| 配置与黑名单 | `config/app.yaml`、`safepass/config_loader.py` | 阈值/映射/黑名单只加这里 |
| 前端 SSR | 仓库内 stdlib HTTP/模板入口（开工前 `rg "SafetyQueryResult|one_liner"` 定位模板） | D1/D2/A4/D3 |
| 宪法与棘轮 | `CLAUDE.md`、`CONTEXT.md`、`docs/adr/0001-*.md`、`docs/adr/0002-*.md` | E1/E5/G3 |

**Agent 开工仪式（每票）**：

1. `rg` / 读本节「改这些文件」——先定位真实路径，再改。  
2. 若票含 Craft S#：用 WebFetch/浏览器打开下表 URL，只读「观察清单」。  
3. 实现后跑该票 DoD 命令；最后 `pytest tests/ -q`。

---

### 1.1.1 外部高标准参照（按 S#）

#### S1 / S9 — Perplexity（依据 / 溯源）

| | |
|--|--|
| **打开** | https://www.perplexity.ai/ （任问一句事实题，看答案旁引用形态） |
| **观察** | 每条可核对断言旁有可点来源；无来源时不装成有来源；追问会改答案焦点 |
| **偷** | `suggestion_grounds[{doc_id,quote}]`；UI 小号「依据」行；无 grounds → 文案「通用建议」；A8 点击后展示原文片段 |
| **禁止** | 实时全网搜索；把网页当 NYPD 事实；抄其前端组件 |
| **改这些文件** | `safepass/contracts.py`（grounds 字段）；Suggestion Skill 输入打包；`pipeline` 把 `intel.search` top-3 写入上下文；结果页模板渲染 grounds；A8 另加原文 lookup |
| **绑票** | A2, A4, B1, A8 |

#### S2 — Walk Score（分→人话 + methodology）

| | |
|--|--|
| **打开** | https://www.walkscore.com/methodology ；任地址页看分数旁英文标签（如 Walker's Paradise） |
| **观察** | 单一数字 + **固定**人话带；methodology 页讲衰减/数据源/局限；标签不是 LLM 散文 |
| **偷** | `rating_rationale` 确定性拼装；one_liner 允许的数据钩子集合（配置化）；信任页/ README 公式说明结构 |
| **禁止** | 引入 Walk Score API；用 LLM 生成灯色标签；把阈值写进 py |
| **改这些文件** | `pipeline` / 纯函数评级旁拼 rationale；`config/app.yaml` 钩子词典；前端首屏；`docs/` methodology 短文 |
| **绑票** | A3, C1, D1 |

#### S3 — Crisis24（情报简报槽位）

| | |
|--|--|
| **打开** | https://www.crisis24.com/solutions/travel-risk-management （产品叙述：行前简报 / 风险档 / 行动） |
| **观察** | 先结论档与行动，细节后置；槽位稳定，不靠聊天流 |
| **偷** | 首屏五槽：评级 / 人话解释 / one_liner / 建议 /（紧急时资源）；图表默认折叠；D6 透明条 |
| **禁止** | GPS 追踪、员工行程管理、企业 dashboard 密度 |
| **改这些文件** | 结果页模板/CSS 层级；契约字段只读渲染；折叠控件 |
| **绑票** | D1, D6 |

#### S4 — GeoSure（场景维度，不当评级源）

| | |
|--|--|
| **打开** | https://geosure.ai/ ；https://geosure.ai/faq （Women's / Nighttime 等维度叙述） |
| **观察** | 多维安全（女性/夜间等）是**产品问题轴**；分数方法论很长——**我们只偷问题轴，不偷其分** |
| **偷** | Skill 输入强制 profile + 时段；建议文案覆盖夜间/独处等；细时段桶 + 低样本 unknowns |
| **禁止** | GeoSure MCP/API 进运行时；用其 1–100 分替换 ADR-0001；LLM 生成评级 |
| **改这些文件** | Skill 提示词与 schema；`data_agent` 时段桶（config）；A5 测试「rating 相等 suggestions 不等」 |
| **绑票** | A5, C2 |

#### S5 — SpotCrime（可审计 methodology）

| | |
|--|--|
| **打开** | https://spotcrime.io/methodology ；https://spotcrime.io/blog/how-to-evaluate-crime-data-api |
| **观察** | 双层分叙事、刷新频率、局限、「分不代表什么」；教客户如何审计数据产品 |
| **偷** | 信任页/ADR/README 的章节骨架；敏感性表（离线脚本）；缺数据不当好事的话术 |
| **禁止** | 接入 SpotCrime 付费 API 当主数据（MVP/作品集轴用 fixture/NYPD）；抄其商业评分公式 |
| **改这些文件** | `docs/` 或法律/信任页；`scripts/` 敏感性扫表；`CLAUDE.md` 棘轮若出事 |
| **绑票** | C1, C4, G3 |

#### S6 — Redfin（诚实不做）

| | |
|--|--|
| **打开** | https://www.redfin.com/news/neighborhood-crime-data-doesnt-belong-on-real-estate-sites/ |
| **观察** | 公开写清**为何不做**犯罪热力：偏差、漏报、强化歧视风险 |
| **偷** | README Kill list 句式；`must_not_claim`；免责与契约 `sources`/`time_range` 同源测试 |
| **禁止** | 把「红线社区」叙事写进建议；用犯罪分暗示某族群 |
| **改这些文件** | README；免责模板；金标 `must_not_claim`；F1 漂移测试 |
| **绑票** | E6, F1, B3, N1 |

#### S7 — Life360（主路径可发现）— 行为参照，非实现参照

| | |
|--|--|
| **打开** | 应用商店 Life360 产品页 / 官网主价值句（家庭定位类——**只看信息层级**） |
| **观察** | 一个主结论区 + 明显次级行动；不靠用户会写高级查询 |
| **偷** | 追问芯片文案与位置；Hero 一句差异化（有 Skill 后再写 AI） |
| **禁止** | 家庭追踪、后台定位、付费 SOS 流程 |
| **改这些文件** | 首页/结果页模板；芯片 → follow_up 预填 |
| **绑票** | D2, D5 |

#### S8 — TripIt × GeoSure（偏好阈值感）

| | |
|--|--|
| **打开** | GeoSure 博文：TripIt Neighborhood Safety Score（搜 `TripIt GeoSure Neighborhood Safety Score`）；或 https://geosure.ai/blog/ 下相关文 |
| **观察** | 用户可设「我能接受的风险」→ 超阈才提醒；维度可拆 |
| **偷** | 对比页三个权重芯片 → **确定性**改写 `decision_aid`；⚪ 不给「谁更好」 |
| **禁止** | 推送/地理围栏运行时；用 LLM 重写对比结论冒充数据 |
| **改这些文件** | 对比页模板 + 纯函数/模板选择；契约 `decision_aid` |
| **绑票** | A6 |

---

### 1.1.2 无外部竞品时的「借鉴」规则（§7 包）

| 包 | 去哪借鉴 | 改哪里 |
|----|----------|--------|
| N1 注入 | 本仓 guardrail/emergency 测试；OWASP LLM Top 10 概念（勿整页抄进代码） | `tests/eval/` 或 `tests/` 攻击金标 + 报表 |
| N2 基线 | 自己写三列脚本；禁止为对照引入 LangChain「重依赖」进主路径（对照可脚本级临时依赖，主 app 不进） | `docs/baseline-vs-safepass.md` + `scripts/` |
| N3/N6 | `README` 现有安装段；`CLAUDE.md` pickle protocol=5 | `scripts/demo_queries.py` 或等价；`docs/reproducibility.md` |
| N4 脏输入 | 现有 `output_pipeline` 校验测试风格 | 参数化测试扩到 Skill 输出 |
| N5 debug | D6 字段超集 | 查询参数 `debug=1` + 模板旁路 |
| B4/B5 | `CASE-openevals使用` + 本仓 fixture 检索 | `tests/eval/`、`tests/` 检索回归 |
| C3 中文 | 仅 config 映射表；可参考 NYPD 罪名中译惯例，**人工表** | `config/app.yaml` + charts/建议共用 |
| D3 状态态 | 本仓已有 degraded/emergency 页 | 模板补齐 + `degradation_notice` 首屏 |

---

### 1.1.3 波 1 票 → 借鉴速查（agent 剪贴板）

| 票 | 先打开/先读 | 再改 |
|----|-------------|------|
| A1 | `output_pipeline.py`、`contracts.py`、`pipeline.py` `_build_safety_result`；Craft S2 URL | 新建/填充 `safepass/skills/`（或项目既有 skills 目录）；接主路径 |
| A2 | `rg "def search"`；S1 Perplexity 观察；棘轮：community_info 不排序 | search → Skill 上下文 + grounds；间接注入校验 |
| A3 | S2 methodology；one_liner 校验 | Skill 或规则填空 + 金标钩子 |
| B1/B2 | `CASE-openevals使用`；v2 spec M1 | `tests/eval/` 咬合 Skill 输出 |
| D1 | S3 观察槽位 | 结果页模板层级 |
| D2 | S7 观察主次行动 | 芯片预填 |
| E1 | `CONTEXT.md`、README、`skills/` | 三处一致；无 Skill 删「AI 建议」话术 |

---

## 1.2 GitHub Borrow Atlas（追加）— 高星开源、功能同构

> **地位**：与 §1.1 **并列**的借鉴入口。§1.1 = 产品/方法论公开页；§1.2 = **GitHub 高星仓**（领域可不同，要求 **feature 同构** + 硅谷水准）。  
> **星数**：录入时经 `gh api` 核对（约 2026-09 量级）；agent 可再查，但不得用「0★ marketing RAG demo」冒充标杆。  
> **总规则**：
> 1. **借鉴** = 读示例/文档/测试组织方式 → **改写**进本仓既有接缝（`output_pipeline` / `tests/eval/` / Skill schema）。  
> 2. **别抄** = 禁止整库 vendoring、禁止为主路径新增重框架（无 ADR）、禁止引入服务型向量库/DB、禁止多 Agent 循环（见 §0.3 Won't）。  
> 3. 对外叙事仍用 GeoSure / Walk Score / Perplexity；**对内改写代码**优先本节高星仓 + 本仓 `可用来参考的代码案例/`。

### 1.2.0 与 §1.1 怎么分工

| 来源 | 教什么 | 典型用法 |
|------|--------|----------|
| §1.1 竞品 URL | 用户可见味道（引用行、首屏槽、Kill list 句式） | UI / 文案 / methodology 页 |
| §1.2 GitHub | 可运行模式（结构化重试、红队用例、RAG 指标拆分） | Skill / eval / guardrail / 检索回归 |
| 本仓 CASE-* | 已指定 provenance（尤其 openevals） | 按 v2 spec 标注来源路径 |

---

### 1.2.1 约束生成 / Skill 输出契约（→ A1）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [567-labs/instructor](https://github.com/567-labs/instructor) | 13.8k | Pydantic 结构化输出；校验失败有限重试；错误信息回灌 | 不必把 instructor 整库加进依赖；模式写进现有 `output_pipeline` |
| [dottxt-ai/outlines](https://github.com/dottxt-ai/outlines) | 15.7k | 结构化约束生成思路（schema 硬约束） | 不换推理栈；不强制 outlines 运行时 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 19.7k | 类型端到端、工具/边界清晰的 API 品味 | **禁止**为炫技迁移整框架进 SafePass 主路径 |

**Agent 动作**：打开 instructor「validation retry」文档/示例 → 对照 A1 Skill = 提示词 + schema + 业务校验 + `output_pipeline` 重试。

---

### 1.2.2 Eval / 红队 / RAG 度量（→ B1–B5, N1, N2）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | 24.9k | **红队/注入用例分类**；多模型对照矩阵；CI 门形态（叙事：used by OpenAI/Anthropic） | 主应用不必 Node 化；YAML 攻击集**改写**为 pytest/金标即可 |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | 18.1k | 在 pytest 里挂 faithfulness 等门禁的组织方式 | 可不绑 Confident 云；指标阈值进本仓 config |
| [vibrantlabsai/ragas](https://github.com/vibrantlabsai/ragas) | 15.6k | context precision/recall、faithfulness：拆「检索 vs 生成」 | 作维度/公式灵感；L2 主实现仍按 CASE-openevals / v2 spec |
| [openai/evals](https://github.com/openai/evals) | 19.4k | eval 注册表、金标目录组织 | 体量大，只偷套件结构，勿整仓导入 |
| [langchain-ai/openevals](https://github.com/langchain-ai/openevals) | 1.2k | **v2 spec 已点名**；evaluator 接缝清晰 | 按 provenance **改写**进 `tests/eval/`，勿整仓 vendoring；星少但官方接缝优先于野鸡 demo |

**Agent 动作（N1）**：优先阅读 promptfoo red-team 文档中的攻击类别 → 改写成「诱导改评级 / 武器建议 / 间接注入 / 覆盖免责」金标；**评级字段必须断言不可被话术改写**。

---

### 1.2.3 Guardrail / 可编程护栏（→ B3, N1, F2）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [NVIDIA-NeMo/Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) | 7.1k | 对话护栏拓扑：拒绝 / 改写 / 旁路；**校验在生成后、可确定性** | **禁止**引入 Colang 全家桶进主路径 |
| [guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails) | 7.4k | 输出 validators 组合、失败即拒 | 对齐现有 `BusinessValidationError`，不要平行造第二套校验框架 |

**对齐宪法**：评级 / 越界 / 可信度仍零 LLM；护栏只挡生成建议与路由旁路。

---

### 1.2.4 混合检索 + 引用接地（→ A2, A4, B4）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [facebookresearch/faiss](https://github.com/facebookresearch/faiss) | 40.9k | 官方用法与限制（你们已用） | 遵守 ASCII 路径棘轮；勿升级协议导致跨环境炸 |
| [run-llama/llama_index](https://github.com/run-llama/llama_index) | 52k | Hybrid / RRF **示例与 notebook**（只读）；检索评测组织 | **禁止**把 LlamaIndex 塞进主路径（复杂度税 / Won't） |
| [FlagOpen/FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) | 12.1k | 检索/重排评测习惯；embedding 实验记录方式 | 换模型必须走 N6 版本钉 |
| [AnswerDotAI/RAGatouille](https://github.com/AnswerDotAI/RAGatouille) | 4.0k | ColBERT 晚期交互（可选深化） | 波 1–2 不必上；无评测证明不加 |
| [onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx) | 32.0k | 企业问答产品：**混合检索 + 带引用答案**的信息架构 | 体量巨大；**禁止 fork**；只读引用 UX / 权限叙事 |

**降级说明（不当标杆）**：`Utkarsh272/rag-grounded`、`huseyinkaplandev/production-rag-evals` 等 ≈0★ 仓——可作「abstention / grounds 契约」小品文，**不得**写入「硅谷高星参照」对外叙事。

---

### 1.2.5 成本 / 多模型路由（→ E3, E4, T4, B6）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 58.2k | 统一调用、**成本/token 字段**、降级与路由叙事 | 不必替换现有 `llm_client`；熔断仍挂本仓包装器 |

---

### 1.2.6 工程哲学 / 小而硬 / 官方配方（→ E1, E6, N3, G1）

| 仓库 | Stars（约） | **借鉴什么** | **别抄什么** |
|------|------------:|--------------|--------------|
| [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | 37.8k | 「编程 LM 而非堆 prompt」——对照确定性后置 + Skill 契约 | 不强制引入 DSPy 运行时 |
| [simonw/llm](https://github.com/simonw/llm) | 12.5k | CLI 小工具、可复现、插件边界（Willison） | 不把 SafePass 改成 CLI 产品 |
| [anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks) | 52.5k | 官方 notebook：工具、引用、评估配方 | 只读配方；注意许可与别大段粘贴 |
| [openai/openai-cookbook](https://github.com/openai/openai-cookbook) | 75.8k | RAG / eval / structured outputs 官方例 | 同上 |

---

### 1.2.7 默认不引进主栈（高星但撞红线）

| 仓库 | Stars（约） | 为何只「看一眼」 |
|------|------------:|------------------|
| langchain-ai/langchain、langgraph | 14万+ / 4万+ | 星高；§0.3：无评测证明前不多 Agent / 重框架 |
| microsoft/graphrag | 35.9k | 图谱重；扩覆盖会稀释 MVP |
| vercel/ai | 26.6k | 流式/引用 UX 可看；坚持 stdlib SSR，不换 Next |
| chroma-core/chroma、qdrant/qdrant | 2.9万 / 3.4万 | 服务型向量库 ↔ 禁服务型 DB；索引继续文件 + FAISS |

---

### 1.2.8 清单票 → GitHub 借鉴速查（与 §1.1.3 互补）

| 票 | 先打开（GitHub） | **借鉴** | **别抄 / 落点** |
|----|------------------|----------|-----------------|
| A1 | instructor 校验重试例；可选 pydantic-ai README | schema + 失败重试 | 写进 `output_pipeline` + skills；不引整框架 |
| A2 / A4 | onyx（产品引用形态，只读）；llama_index hybrid 例（只读） | grounds 契约；query→chunk→建议 | 主路径自研接缝；community_info 不参与排序 |
| B1 / B2 | ragas 维度说明 + openevals + CASE-openevals | faithfulness / 矛盾维度 | `tests/eval/`；关 Skill 主指标须变差 |
| B4 | FlagEmbedding / llama_index 检索评测 notebook | Recall@k 金标组织 | pytest 检索回归；改索引能红 |
| B3 / F2 / N1 | **promptfoo red-team**；NeMo Guardrails 概念 | 攻击分类；后置确定性拒绝 | 金标 + 现有 validator；不装 Colang |
| N2 | promptfoo 多模型对照 | 裸 LLM / 无约束 RAG / SafePass 三列 | `docs/baseline-vs-safepass.md`；对照脚本勿污染主 app 依赖 |
| E3 / E4 / T4 / B6 | litellm 成本字段思路 | 质本延迟表；熔断后调用次数不增 | 本仓熔断包装器 + README 表 |
| E1 / G1 / N3 | simonw/llm 品味；openai/anthropic cookbooks | 小而硬、一键可跑、Kill list | README / demo_queries；不换产品形态 |

---

## 2. 第 1 波（冲 90）— 必须连续做完

> 大神原话：第 1 波把你们从「强数据系统」拉到「真 AI 应用」。  
> **本波结束门闩**：验收看板 #1 #3 #6 + E1；并启动 §7 的 N1（注入）与 N3（一键复现）——见 §2.9。

优先级含义（大神原表）：

| 优先级 | 含义 | 对作品集分贡献（粗估） |
|--------|------|------------------------|
| P0 | 不做则到不了 90 | +8～12 |
| P1 | 90→95 主力 | +4～6 |
| P2 | 95→98 | +2～3 |
| P3 | 98→100 | +1～2 |

---

### A1. P0 — 落地 Suggestion Skill（主路径真正接 LLM 建议）

- **目标**：用户可见的「贴心建议 / one_liner」来自受约束生成，不再只是 `safety_general` 重排。  
- **缺口**：`skills/` 空壳；`_build_safety_result` 用配置模板。  
- **做法**：Skill = 提示词 + Pydantic 输出 + 业务校验；输入打包：评级摘要、`top5`、昼夜、三维/画像、检索 top-3 摘要；经现有 `output_pipeline`；熔断/`llm_client=None` → 明示模板降级。  
- **DoD**：注入真实/fake client 时建议可区分；`llm_client=None` 仍出合法契约；评级比特级不变（既有 invariance 测试仍绿）。  
- **加分**：补上「AI 应用」而非「数据仪表盘」的核心叙事。  
- **Craft**：S2（one_liner 可核对方向）；完成后重测 T4 三路径。  
- **Agent 注意**：阈值/黑名单只读 yaml；LLM **零接触** rating / confidence / out-of-coverage。

---

### A2. P0 — 混合检索必须 query-conditioned 进入建议

- **目标**：`intel.search(query)` 改变建议内容；检索不再是「测得到、用户感不到」。  
- **缺口**：`community_info` 按警区确定性装配；`search()` 未喂进建议。  
- **做法**：建议上下文注入 top-3 chunk；可选契约字段 `suggestion_grounds: list[{doc_id, quote}]`；community_info 可保留警区锚定。  
- **DoD**：同一警区、不同 query（诈骗 vs 夜间），建议/`grounds` 可测差异；金标 `must_mention` 能命中检索事实。  
- **加分**：证明 RAG 是产品路径，不是简历关键词。  
- **Craft**：S1。  
- **额外硬约束（优化项）**：校验器须拒绝「检索 chunk 试图改写评级/取消免责」的间接注入；与 N1 金标交叉。community_info **不参与检索排序**（CLAUDE.md 棘轮）。

---

### A3. P0 — `one_liner` 数据钩子化（仍短、仍可校验）

- **目标**：一句话含「可核对」信息（夜间偏高 / 某类案件突出 / 相对全市），不是「区域：黄灯」。  
- **做法**：Skill 生成或确定性模板二选一（有 LLM 用 Skill，无则规则填空）；继续字数上限 + 空话/恐慌黑名单。  
- **DoD**：金标断言 one_liner 含至少一类允许的数据钩子；与 `charts`/`ratio` 不矛盾。  
- **加分**：首屏决策速度（产品）+ 可证伪（技术）。  
- **Craft**：S2。

---

### B1. P0 — L2 咬合「生成建议」，禁止测模板自嗨

- **目标**：groundedness / 幻觉率反映 Skill 输出，不是 `safety_general`。  
- **做法**：金标带 `must_mention` / `must_not_claim` 对准建议与 one_liner；模板降级路径单独 marker，不计入主 groundedness。  
- **DoD**：关掉 Skill 改回纯模板时，主指标应明显变差或套件失败；README 口径写清。  
- **加分**：Hamel 标准下的真 eval。  
- **Craft**：S1。

---

### B2. P0 — 增补质量维度：actionability + specificity + 矛盾检测

- **目标**：除 groundedness/幻觉外，能量化「能照做」「提到本区数据」「不与 charts 矛盾」。  
- **做法**：规则特征（含数字/时间/offense 名）+ LLM-judge 维度；矛盾用确定性核对（提及「夜间更安全」但 night>>day → fail）。  
- **DoD**：三类指标进 README 或 eval 工件；有回归门。  
- **加分**：从 1 个虚荣指标 → 质量仪表盘。

---

### D1. P0 — 结果页首屏信息架构

- **目标**：首屏 = 评级 + 人话解释 + one_liner + 3 条建议；图表/community/来源默认折叠。  
- **DoD**：窄屏一屏内可见结论与建议；快照/断言锁层级。  
- **加分**：从资料页 → 决策页（Rauch/Howard）。  
- **Craft**：S3。  
- **注**：若 C1 `rating_rationale` 尚未做，首屏「人话解释」可用现有字段确定性拼装占位，但波 2 必须换真 C1。

---

### D2. P0 — 追问/对比能力可发现（芯片）

- **目标**：结果页露出「女生晚上呢？」「和法拉盛比呢？」等；后端能力被产品化。  
- **做法**：芯片 = 预填 query 或 follow_up；紧急页不显示（保持极简）。  
- **DoD**：点击后契约类型符合预期的前端/集成测试。  
- **加分**：交互深度，不靠用户会写追问。  
- **Craft**：S7。

---

### E1. P0 — 叙事与代码对齐：有 Skill 就进主路径，否则删 CONTEXT/包描述

- **目标**：消灭「文档承诺 > 代码」的面试地雷。  
- **DoD**：`skills/`、CONTEXT、README 三处一致。  
- **加分**：诚信；避过「课程作业感」。  
- **硬规则**：A1 未合并前，禁止 Hero/README 写「AI 建议」；只能写数据评级 + 即将/已用模板建议。

---

### 2.9 波 1 结束强制附带（优化：T2 杀手锏前移）

下列三项 **不属于**「可推迟的 P3」，须在波 1 收口后立刻开工（可与波 2 首日并行），完整条文见 **§7**：

| 包 ID | 大神来源 | 一句话 |
|-------|----------|--------|
| N1 | T2-A1 | Prompt Injection / 越狱 / 间接注入专测 |
| N2 | T2-A2 | Naive 基线对照页（可与 N1 同周） |
| N3 | T2-A3 | 一键复现审阅者路径 |

**波 1 自测（大神「稳」定义子集，作品集轴）**：

1. 主路径建议来自 Skill，且检索可测地改变建议。  
2. 评级/越界/紧急仍零 LLM；画像不变评级有自动证明。  
3. L2 主指标测生成物；含 actionability/specificity/矛盾。  
4. 首屏可决策 + 追问芯片可发现。  
5. 故意关掉 Skill → 主 L2 指标变差或测试红。

---

## 3. 第 2 波（90 → 95）

> 大神：第 2 波进入同侪前 5%。  
> **本波必须含 §7 全包中的评测/中文/状态态/回归门/脏输入/debug/版本钉（见各条引用）。**

---

### A4. P1 — 建议旁「依据」溯源行

- **目标**：每条建议下小号文字：依据 Top offense / 昼夜比 / 知识句。  
- **做法**：UI 渲染 `grounds`；无 grounds 的模板降级建议标注「通用建议」。  
- **DoD**：抽检 10 条：有依据 ↔ 无依据视觉可分；依据文本可在 fixture/检索结果中找到。  
- **加分**：信任与 Willison 式「小而硬」。  
- **Craft**：S1。

---

### A5. P1 — 画像差异「可感知且可证明」

- **目标**：有无画像 / 不同场景，建议明显不同；评级不变。  
- **做法**：Skill 输入强制带 profile+extracted；前端可选「对比：无画像 vs 当前画像」折叠（本地二次请求或同页双栏仅建议区）。  
- **DoD**：自动化：同区两 profile，`rating` 相等、`suggestions` 不全等；人工：晚归女生能看出夜间/独处相关。  
- **加分**：ADR-0002 从测试走进产品演示。  
- **Craft**：S4。

---

### B3. P1 — 负例 / 对抗金标专表（偏见、武器、恐慌、越界编造、套话）

- **目标**：安全域作品必须展示「会拒绝、会降级、会不编」。  
- **做法**：独立报表：guardrail 命中率、越界零编造率、空话拦截率；与主金标分开。  
- **DoD**：每类 ≥N 条（建议 ≥10）；全绿；文档有一张覆盖矩阵图。  
- **加分**：安全产品差异化；面试追问「怎么防胡说」有答卷。  
- **Craft**：S6；与 **N1 注入专测** 报表可分可链。

---

### B4. P1 — 检索质量单独测：Recall@k / nDCG 小组

- **目标**：证明 hybrid 不是玄学。  
- **做法**：20–40 条「query → 应命中 doc_id」标注；断言 top-3 命中；BM25-only vs hybrid 对比表（可手工一次写入 README）。  
- **DoD**：检索回归可 `pytest`；改索引能红。  
- **加分**：检索工程可信度。  
- **打包**：详见 §7.1（无竞品必做·评测）。

---

### B5. P1 — Judge 校准包（人工盲评小样本）

- **目标**：降低「Qwen 考 Qwen」嫌疑（不上线也能做）。  
- **做法**：抽 15–20 条人工标 0/1；算与 judge 一致率；阈值写入 eval 文档。  
- **DoD**：一致率与分歧案例列表进仓库；低于阈值则改 judge prompt 并锁版本。  
- **加分**：eval 成熟度，逼近 95+。  
- **打包**：§7.1。

---

### C1. P1 — 评级「人话解释层」（零 LLM）

- **目标**：一行说清：相对全市倍数、样本档、为何 ⚪。  
- **做法**：契约加 `rating_rationale: str` 或前端用已有字段拼装；公式可展开。  
- **DoD**：⚪ / 绿 / 黄 / 红 各有快照测试；与 ADR-0001 一致。  
- **加分**：认知友好；色盲友好之上的「脑友好」。  
- **Craft**：S2, S5。

---

### C2. P1 — 时段切片产品化（不止总 day/night）

- **目标**：查询含「晚上 10 点」时，建议与解释对齐更细时段（若数据支持）。  
- **做法**：data_agent 增加可配置时段桶；无足够样本 → unknowns 诚实说。  
- **DoD**：有时段 query 与无时段 query 输出可测差异；低样本强制 unknowns。  
- **加分**：三维提取从「抽到了」变成「用上了」。  
- **Craft**：S4。

---

### C3. P1 — Offense 中文本地化与「用户语言」对齐

- **目标**：Top5 与建议使用同一中文罪名体系，避免英文法律名吓跑用户。  
- **做法**：配置映射表；建议与 charts 共用。  
- **DoD**：映射全覆盖 fixture 类型；未知类型显式「其他」不吞掉。  
- **加分**：中文用户产品完成度。  
- **打包**：§7.2（无竞品必做·中文）。

---

### D3. P1 — 空态 / 加载 / 部分失败的产品文案

- **目标**：无结果、熔断降级、提取失败、索引缺失，各有明确态（你们有部分，需对齐生成降级）。  
- **DoD**：每态有测试或快照；降级必带 `degradation_notice` 且首屏可见。  
- **加分**：完成度与信任。  
- **打包**：§7.3（无竞品必做·状态态）。

---

### D4. P1 — 视觉层级「作品集级」但不换栈

- **目标**：在 stdlib SSR 约束下：字体、间距、结论字重、紧急主题、法律页统一；去系统默认「后台表单」感。  
- **注意**：避免紫渐变/通用 AI 皮肤；安全产品偏冷静清晰。  
- **DoD**：移动端不断版；关键态截图进仓库或快照。  
- **加分**：产品力观感（不靠 React）。

---

### D5. P1 — 首页价值主张一句话 + 覆盖诚实

- **目标**：Hero：品牌 + 一句「中文安全情报；数据评级，AI 只建议」+ 查询框 + 五区入口。  
- **DoD**：文案与产品实际一致（**有 Skill 后才能写「AI 建议」**）。  
- **加分**：3 秒理解差异化。  
- **Craft**：S7。

---

### E2. P1 — 契约版本意识

- **目标**：`SafetyQueryResult` 增 `grounds` 等字段时有版本注释/changelog；前端兼容策略写清。  
- **DoD**：短 `docs/adr` 或 changelog 一节。  
- **加分**：API 品味。

---

### E3. P1 — 性能信封文档化（本地可测）

- **目标**：一张表：查询 P95、紧急 P95、无 LLM 路径、有 Skill 路径、索引内存粗值。  
- **做法**：已有 `pytest -m perf` 则投影到 README；Skill 后重测。  
- **DoD**：数字可复跑；超阈红。  
- **加分**：Carmack 式「知道墙在哪」。  
- **Craft**：T4。

---

### F1. P1 — 免责/口径与结果页字段同源

- **目标**：免责页写的时间范围、数据来源与契约 `sources`/`time_range` 一致。  
- **DoD**：单一事实源 config；漂移测试。  
- **Craft**：S6。

---

### F2. P1 — Guardrail 覆盖矩阵可视化

- **目标**：一张表：输入类型 → 形态（emergency/guardrail/degraded/safety）。  
- **DoD**：与测试用例 ID 链接。  
- **加分**：安全设计可 review。  
- **打包**：§7.1。

---

### G1. P1 — README 顶栏：架构一图 + 三项～六项指标 + Kill list + 本地 3 命令

- **DoD**：新人 10 分钟能跑通并理解「LLM 不评级」。  
- **Craft**：T5, T6, S6。

---

### G2. P1 — 前后「建议路径」对照说明（一页）

- **目标**：写清：曾用配置建议 → 现用 Skill+检索；附不变式（评级不变）。  
- **加分**：成长与判断力。

---

### 波 2 另绑 §7（必须出现在本波看板）

| 包 | 内容 |
|----|------|
| N1–N3 | 若波1末未完成则本波 Day1 blocker |
| N4 | 脏输入 / Skill 输出属性测试（T2-A10） |
| N5 | `?debug=1`（T2-A13） |
| N6 | 版本钉死清单（T2-A11） |
| N7 | 建议变更回归门（= B7，可提前做壳） |

---

## 4. 第 3 波（95 → 98）

### A6. P2 — 对比 `decision_aid` 升级为「偏好可读」

- **目标**：对比页支持「更在意总体 / 夜间 / 某类案件」时话术变化（可用确定性规则，不必 LLM）。  
- **做法**：UI 三个权重芯片 → 重排或改写 `decision_aid` 模板；缺数据维度保持 `in_development`。  
- **DoD**：切换芯片，辅助句变化可测；⚪ 侧仍不给「谁更好」。  
- **加分**：对比从报表变成决策工具。  
- **Craft**：S8。

---

### A7. P2 — 建议反重复与场景覆盖矩阵

- **目标**：3–5 条覆盖不同行动类型（防范 / 路线习惯 / 求助 / 社区资源），不三句同义。  
- **做法**：Skill schema 加 `category` 枚举；校验器要求类别多样性；提示词给覆盖矩阵。  
- **DoD**：校验失败会重试；金标检查类别集合。  
- **加分**：生成质量从「通顺」到「有结构」。  
- **打包**：§7.4（回归门相关校验）。

---

### B6. P2 — 生产模型兼容套件可一键跑（结果可登记，不强制线上）

- **目标**：同一金标可切 DeepSeek；工件与 Qwen 基线并排。  
- **DoD**：脚本 + 文档；无 key 时 skip 并说明；有 key 时产出 diff 表。  
- **加分**：「换模型是评估决策」叙事闭环。

---

### B7. P2 — 建议变更的回归门（prompt/skill 改动不能静默漂）

- **目标**：改提示词必须跑 L2 子集。  
- **做法**：`tests/eval` marker；CI 本地钩子或文档强制命令；基线指纹。  
- **DoD**：故意改坏 prompt → 红。  
- **加分**：工程纪律到生成层。  
- **打包**：§7.4。

---

### C4. P2 — 敏感度/阈值透明（配置即文档）

- **目标**：作品集可展示「0.7/1.3 不是拍脑袋」——附简单敏感性说明（改阈值时档位如何动）。  
- **做法**：脚本对真实 fixture 扫阈值邻域，产出静态表进 `docs/`（非运行时）。  
- **DoD**：表可复现；与 city_mean 同源。  
- **加分**：数据科学品味，面试加分项。  
- **Craft**：S5。

---

### C5. P2 — 地址歧义消解 UX（仍用别名表，不上 Geocoding）

- **目标**：「中城」「哥大附近」等已有降级；对「多别名撞车」给出可选列表而非静默挑一个。  
- **做法**：解析层返回 candidates；前端让用户点选；点选前不出评级。  
- **DoD**：构造歧义 fixture；契约或前端流可测。  
- **加分**：产品诚实与交互成熟度。

---

### C6. P2 — 覆盖边界可视化（非地图也可）

- **目标**：首页/结果页说清「我们覆盖这 5 区；你查的是 X；越界会怎样」。  
- **做法**：覆盖清单 + 本次命中警区；越界页对比「若在覆盖内你会看到什么结构」。  
- **DoD**：文案快照；与 config 警区列表单一事实源。  
- **加分**：scope 叙事主动，防「toy」攻击。

---

### D6. P2 — 「本次查询用了什么」透明条

- **目标**：展示：命中警区、数据时间范围、是否 LLM 建议、是否熔断、检索是否命中。  
- **DoD**：字段来自契约；无隐私泄露。  
- **加分**：工程师审美 + 用户信任。  
- **Craft**：S3；可与 N5 debug 共用字段，debug 更细。

---

### D7. P2 — 对比页与安全页视觉语法统一

- **目标**：同一套评级呈现、同一套折叠、同一套免责。  
- **DoD**：共享渲染 partial；测试锁。

---

### E4. P2 — 成本熔断在「有 Skill」后的行为演示态

- **目标**：熔断后：评级/数据仍在，建议变模板且首屏明示——生成接上后这才是完整故事。  
- **DoD**：测试断言调用次数不再增加 + UI 可见 notice。  
- **Craft**：T4。

---

### E5. P2 — 棘轮表续写

- **目标**：每引入 Skill/检索进建议，若出事故就加棘轮一行（只增不改）。  
- **DoD**：CLAUDE.md 表有对应行。

---

### F3. P2 — 恐慌/绝对化用语持续收紧

- **目标**：生成建议上线后，黑名单与 NEG 用例同步扩张。  
- **DoD**：故意注入恐慌词 → 校验失败。

---

### G3. P2 — ADR 补两篇

- 建议：`0003-suggestion-skill-with-retrieval.md`（为何 LLM 建议、为何检索进建议、为何熔断回模板）  
- 建议：`0004-eval-dimensions.md`（为何这些指标、judge 局限）  
- **加分**：Staff 沟通方式。  
- **Craft**：S5。

---

## 5. 第 4 波（98 → 100）— 边际；波 1–2 未绿禁止提前

### A8. P3 — 引用高亮（检索句在知识原文可定位）

- **目标**：点击依据 → 展示原文片段（仍 SSR 即可）。  
- **DoD**：doc_id + span 可解析；解析失败不崩，降级为仅 doc 名。  
- **加分**：逼近「严肃情报产品」质感。  
- **Craft**：S9。

---

### B8. P3 — 失败分类学（taxonomy）工件

- **目标**：每次 eval 产出错误类型直方图（路由错 / 检索未命中 / 建议空话 / 矛盾 / 越界泄漏）。  
- **DoD**：JSON 工件 + 一页 markdown 解释。  
- **加分**：Staff 味的质量思维（仍不必上线）。

---

### C7. P3 — 属性测试 / 边界测试加固评级引擎

- **目标**：对 sample_size、ratio 边界做 property-based 或参数化穷尽。  
- **DoD**：边界邻域全绿；与 config 档位一致。  
- **加分**：内核从「测过」到「难写坏」。

---

### C8. P3 — 知识库按场景加厚（仍可确定性解析）

- **目标**：15 篇 → 按诈骗/夜间/通勤/仇恨/报案 主题加深，而非盲目扩警区。  
- **DoD**：fixture 自检仍锁格式；检索金标同步更新。  
- **加分**：RAG 内容质量，而非堆模型。

---

### D8. P3 — 无障碍再进一步

- **目标**：已有色盲友好；补键盘焦点、对比度、`aria` 于芯片/折叠。  
- **DoD**：基本 a11y 清单打勾（人工即可）。

---

### D9. P3 — 微动效 2～3 处（克制）

- **目标**：结论出现、紧急切入、折叠展开的层级感；不要粒子/光晕。  
- **DoD**：`prefers-reduced-motion` 可关。

---

### E6. P3 — 「Kill list」产品化（写在 README）

- **目标**：公开不做：路径级安全、全市覆盖、登录画像、LLM 评级、服务型 DB……  
- **加分**：判断力展示；防 scope 膨胀。  
- **Craft**：S6, T6。

---

### E7. P3 — 可执行样例（notebook 或 `scripts/demo_queries.py`）

- **目标**：5 条固定 query 打印契约摘要（含边界），一键跑。  
- **DoD**：离线；与金标子集对齐。  
- **加分**：面试官/审阅者低摩擦。  
- **注**：与 N3 一键复现可合并实现，避免两个入口。

---

### F4. P3 — 隐私声明与画像表单的「最小必要」再审

- **目标**：六维是否都在 Skill 输入用上；未用的维度考虑隐藏（减认知负担）。  
- **DoD**：文档：维度 → 消费点映射；未消费不采集。

---

### G4. P3 — 失败案例集（精选 8～12 个）

- **目标**：展示系统「不会」什么；附正确契约形态。  
- **加分**：比只晒 happy path 更像 100 分。

---

## 6. 「100 分」验收看板（作品集轴）

| # | 验收项 | 波次 |
|---|--------|------|
| 1 | 主路径建议来自 Skill，且检索可测地改变建议 | 1 |
| 2 | 评级/越界/紧急仍零 LLM；画像不变评级有自动证明 | 守门 |
| 3 | L2 主指标测生成物；含 actionability/specificity/矛盾 | 1 |
| 4 | 对抗金标专表全绿 | 2 |
| 5 | 检索有独立回归 | 2（B4/§7） |
| 6 | 首屏可决策 + 追问芯片可发现 | 1 |
| 7 | 溯源或等价透明依据 | 2 |
| 8 | 熔断/无 LLM 时明示模板建议 | 2 |
| 9 | README 指标+架构+Kill list 与代码一致 | 2 |
| 10 | 性能信封可复跑 | 2 |
| 11 | Judge 小样本校准有记录 | 2（B5/§7） |
| 12 | ADR 覆盖「为何 Skill / 为何这些 eval」 | 3 |
| 13 | 失败案例集 + 失败分类学工件 | 4 |
| 14 | 歧义地址 / 覆盖诚实 / 时段用数据 | 3–4 |
| 15 | a11y + 克制动效 + 引用高亮等边际 | 4 |
| 16 | **注入拦截率报表全绿；改不了 rating** | 1末–2（N1） |
| 17 | **基线对照页：幻觉/越界显著优于裸 RAG** | 2（N2） |
| 18 | **陌生环境 ≤15 分钟跑通安全+越界+紧急** | 1末–2（N3） |

### 大神团对「满 100」的一句话（保留）

- **Karpathy**：满分 = 约束下的生成闭环，不是更多模型。  
- **Hamel**：满分 = 指标能打假，不能只会报喜。  
- **Rauch**：满分 = 打开结果页 5 秒能决策。  
- **Pocock**：满分 = 每条建议改进都有布尔 DoD。  
- **Swyx**：满分 = 仓库让人 10 分钟懂你的 AI 工程观。

**整合结论（大神原话）**：  
第 1 波把你们从「强数据系统」拉到「真 AI 应用」；第 2 波进入同侪前 5%；第 3–4 波用深度、诚实与文物感去啃最后 2–5 分。  
按此清单做完，在**技术+产品的 vibe/作品集轴**上可以严肃地瞄 **98–100**；若仍缺上线与真人，那是另一根轴的分，不是这份清单的失败。

---

## 7. 附录：无竞品仍必做打包（省事包）

> **用途**：下列项**没有**高标准 C 端竞品可抄，但大神清单 / T2 锁稳明确要求。  
> Coding agent：**不要**去找竞品对标；按 DoD 直接做。  
> 派票建议：每条一张票，标题用 `N# — 短名`，body 复制本节原文。

---

### 7.1 评测科学包

#### N1 — Prompt Injection / 越狱 / 间接注入专测（T2-A1）【极高】

T2 应用岗几乎必问：「用户恶意输入怎么办？」  
SafePass 是安全情报——**没有注入评测 = 专业度穿帮**。

- 做一组攻击金标：诱导改评级、诱导给出武器/违法建议、通过「知识文档」间接注入、试图覆盖免责声明。  
- 期望：guardrail / 校验 / 降级；**评级字段不可被话术改写**。  
- **DoD**：独立报表「注入拦截率」；故意放松校验会红。  
- **为何锁 T2**：这比再做一个炫技 Agent 更能让 hiring manager 签字。  
- **绑票**：A2 校验交叉；B3 报表可链接、勿合并成一锅粥。

#### N2 — Naive 基线对照（T2-A2）【极高】

T2 要的是判断力，不是框架名。

- 同一 20 条金标：`裸 LLM` / `无约束 RAG` / `当前 SafePass` 三列：幻觉率、越界编造、评级一致性。  
- 结论写成一页：`docs/baseline-vs-safepass.md`（数字 + 3 个失败样例）。  
- **DoD**：页存在；SafePass 在幻觉/越界两项显著优于裸 RAG；评级一致性列 SafePass = 100%（确定性路径）。  
- **为何锁 T2**：直接回答「你和会调 API 的人差在哪」。

#### B4 复述（检索回归）— 见 §3 B4

- 20–40 条 query→doc_id；top-3 命中可 pytest；改索引能红；BM25-only vs hybrid 表可进 README。

#### B5 复述（Judge 校准）— 见 §3 B5

- 15–20 条人工 0/1；一致率+分歧列表进仓库；低于阈值改 judge prompt 并锁版本。

#### F2 复述（Guardrail 矩阵）— 见 §3 F2

- 输入类型 → emergency/guardrail/degraded/safety；链到测试用例 ID。

#### B2/B1 咬合 — 见 §2

- 主指标必须测 Skill 生成物；关 Skill → 主指标变差或红。

---

### 7.2 中文产品完成度包

#### C3 — Offense 中文本地化（全文见 §3 C3）

- **目标**：Top5 与建议同一中文罪名体系。  
- **做法**：`config/app.yaml`（或专表）映射；建议与 charts 共用。  
- **DoD**：fixture 类型全覆盖；未知 → 显式「其他」不吞掉。  
- **Agent 禁令**：不要为「学 GeoSure 多语言」引入运行时翻译 API；本地表即可。

---

### 7.3 状态态 / 降级可见包

#### D3 — 空态 / 加载 / 部分失败（全文见 §3 D3）

- 无结果、熔断降级、提取失败、索引缺失各有明确态。  
- **DoD**：每态测试或快照；`degradation_notice` 首屏可见。  
- **与 E4 对齐**：有 Skill 后熔断 = 数据仍在 + 模板建议 + 明示。

#### E4 复述 — 见 §4 E4

- 断言 LLM 调用次数不再增加 + UI notice。

---

### 7.4 回归门包

#### B7 — 建议变更回归门（全文见 §4 B7）

- 改提示词/Skill 必须跑 L2 子集；基线指纹；**故意改坏 prompt → 红**。

#### A7 — category 多样性校验（全文见 §4 A7）

- schema `category` 枚举；多样性失败重试；金标查类别集合。  
- 与 B7 一起防止「通顺但同义反复」静默漂。

#### E5 — 棘轮续写（全文见 §4 E5）

- Skill/检索进建议若出事故 → `CLAUDE.md` 棘轮表只增不改。

---

### 7.5 脏输入 / 契约健壮性包

#### N4 — 契约模糊测试 / 属性测试扩到 Skill 输出（T2-A10）【中】

乱输入、超长输入、中英混杂、emoji、复读机——输出仍合法契约或明确 guardrail。  
T2 线上全是脏输入；这是「像干过活」的信号。

- **DoD**：参数化或 hypothesis/属性测试覆盖上述类；非法时 emergency/guardrail/degraded 之一，**禁止**半残 SafetyQueryResult；rating 在安全路径仍只由确定性引擎写出。  
- **与 N1 分工**：N1 = 语义攻击；N4 = 垃圾/畸形输入。

#### C7（波4）— 评级引擎边界属性测试 — 见 §5 C7

- sample_size、ratio 边界；可与 N4 分票。

---

### 7.6 Debug 审阅包

#### N5 — 前端「工程师可读」隐藏调试信息（T2-A13）【中低】

`?debug=1`：路由意图、检索 doc_id、是否熔断、Skill 重试次数。  
面试现场改问题、对着 debug 讲——T2 现场感极强。  
**默认关闭**，不影响普通用户。

- **DoD**：无 debug 时页面零泄露；有 debug 时字段来自服务端契约/安全摘要，不含 API key；紧急页仍极简（可不显示或只显示形态名）。  
- **与 D6**：D6 是用户透明条；N5 是工程师层，更细。

---

### 7.7 版本钉 / 可复现包

#### N6 — 版本钉死清单（T2-A11）【中】

`requirements` 锁版本 + 索引 protocol=5 故事 + embedding 模型名钉死。  
「换机器指标漂移」是 T2 红旗；你们已有棘轮，要写成审阅者 30 秒能懂。

- **DoD**：一页 `docs/reproducibility.md`（或 README 一节）：Python 依赖锁定方式、pickle protocol=5、embedding 模型标识、FAISS ASCII 路径约束、cassette/judge 版本锁定指针；陌生人按文档可复现波1 指标量级。  
- **与 N3**：N3 是「能跑」；N6 是「换机器不漂」的说明与锁定。

#### N3 — 一键复现「审阅者路径」（T2-A3）【极高】

邀约前/面试前，对方若跑不起来，T2 直接折损。

- 单一命令：装依赖（或 Docker）→ 跑 5 条固定 query → 打印契约摘要 + 打开本地页。  
- 明确：无 key 走确定性路径；有 key 走 Skill。  
- **Windows 可跑**（作者环境是 Windows）。  
- **DoD**：文档写明命令；无 key 路径全绿；与 E7 `demo_queries.py` 宜合并，避免双入口。  
- **为何锁 T2**：降低「作品造假/只能作者机器跑」的先验怀疑。

---

### 7.8 本附录派票速查表

| 票 ID | 短名 | 最早波次 | 依赖 |
|-------|------|----------|------|
| N1 | 注入专测 | 1末/2 | A1 建议有主路径更佳；可先测「改不了 rating」 |
| N2 | 基线对照 | 2 | A1+A2 后数字才有杀伤力 |
| N3 | 一键复现 | 1末/2 | 与 E7 合并设计 |
| N4 | 脏输入模糊测 | 2 | A1 Skill 输出契约稳定后 |
| N5 | debug=1 | 2 | D6 字段可复用 |
| N6 | 版本钉清单 | 2 | 与 N3 同周 |
| B4 | 检索回归 | 2 | 索引/fixture 稳定 |
| B5 | Judge 校准 | 2 | B1 跑通后 |
| C3 | 罪名中文 | 2 | charts/建议共用映射 |
| D3 | 状态态 | 2 | 与 E4/A1 降级对齐 |
| B7 | prompt 回归门 | 2–3 | B1 存在后即可做壳 |
| A7 | category 多样性 | 3 | A1 schema 可演进 |
| F2 | Guardrail 矩阵 | 2 | 链现有测试 ID |

---

## 8. 推荐执行顺序（优化后甘特语义）

```
第 1 波（冲 90）
  A1 → A2（含间接注入校验）→ A3
  B1 → B2
  D1 → D2
  E1
  立刻排队：N3（一键复现壳）→ N1（注入；可与 N3 并行）

第 2 波（90→95）
  N2 基线对照（A1/A2 已绿后）
  A4 A5 | B3 B4 B5 | C1 C2 C3 | D3 D4 D5
  E2 E3 | F1 F2 | G1 G2
  N4 N5 N6 | B7 壳 | E4

第 3 波（95→98）
  A6 A7 | B6 B7满 | C4 C5 C6 | D6 D7 | E5 | F3 | G3

第 4 波（98→100）
  A8 B8 C7 C8 D8 D9 E6 E7 F4 G4
```

> **文首补丁覆盖**：派票须遵守 P0–P5；甘特上 N1 按 **P3**（A2 当日启动「改不了 rating」骨架），完整 N1 报表仍可波1末–波2 补满；对外演示门闩见 **P4**，勿等波4。

---

## 9. Agent 派票模板（复制即用）

```markdown
## 标题
{ID} — {短名}

## 来源
docs/portfolio-100-execution-plan.md §{x}

## 目标 / 缺口 / 做法 / DoD / 加分
（粘贴该节大神原文，禁止缩写掉 DoD）

## Craft（可选但若绑定则必填 Borrow）
- Craft IDs: S# / T#
- **必须打开（产品 URL / 本仓路径）**：从 §1.1 复制
- **必须打开（GitHub，若本票在 §1.2.8 有行）**：从 §1.2 复制仓库链接
- **观察清单**：从 §1.1 复制
- **借鉴什么 / 别抄什么**：§1.1「偷/禁止」+ §1.2 对应表两列（必填，禁止只写仓名）

## 允许改动
- 列出目录/文件（优先用 §1.1「改这些文件」，开工前 rg 确认）；阈值只进 config/app.yaml
- 凡改写自 `可用来参考的代码案例/` 或 §1.2 开源模式的文件：在代码或 PR 注释标注 provenance（路径或 repo URL + 学了哪一段）

## 禁止
- LLM 改评级/越界/可信度
- 运行时直连外部数据 API
- 为本票引入新框架（无 ADR）——尤其 LangChain / LlamaIndex / 服务型向量库 / NeMo Colang 全家桶
- 粘贴第三方闭源实现进仓库；整库 vendoring 高星开源仓
- 用 0★ marketing RAG demo 冒充 §1.2 标杆

## 验证
- pytest tests/ -q
- （本票额外命令）

## 完成承诺
- （布尔句，来自 DoD）
```

---

## 10. 文档维护

- 本计划只增补「完成勾选」或勘误；**不擅自删大神 DoD 原文**。  
- 若与 `safepass-v2-spec.md` 冲突：宪法与 ADR 优先；其次 v2 spec 的 M1–M4 范围；本计划负责作品集轴增量。  
- **§1.1** = 产品/方法论公开页借鉴权威入口；**§1.2** = 高星 GitHub 功能同构借鉴权威入口；二者互补，不互相替代。  
- 竞品 URL 只读公开页；GitHub 只读示例/文档并**改写**进本仓接缝；**禁止**把第三方闭源或整库开源实现粘进仓库。  
- §1.2 星数为录入时量级；漂移不影响「借鉴什么/别抄什么」列，除非仓归档或许可变更。  
- 若本仓 `可用来参考的代码案例/` 未检出，agent 须先向用户确认路径，不得假装已改写 openevals。
