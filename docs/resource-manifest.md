# SafePass NYC 资料清单（Resource Manifest）

> **用途**: AI 自助查询与下载的唯一入口。任何素材先查本清单再动手；清单外的资源禁止下载
> **从属**: 服务 `docs/specs/safepass-nyc-mvp-spec.md` v1.2（D11/D11a）与 `docs/archive/ralph-mvp-pool.md`（T0–T8，已归档）
> **维护规则**: 每完成一项下载/生成，更新 §G 状态表；新增素材必须先在本清单登记（来源、本地路径、护栏）
> **日期**: 2026-09-04

---

## A. 使用约定

1. **先查后下**：按 §B（本地直读）→ §C（T0 素材）→ §D（外部源）→ §E（参考代码）→ §F（依赖）顺序查询
2. **来源可溯**：所有外部数据必须带来源标注落盘（文件名或 manifest 登记），无来源的数据不得进入 fixture
3. **诚实护栏**：凡"未核实/未记载"的条目，落盘时原样标注，禁止补全编造（spec D11 两条护栏）
4. **尊重条款**：NYPD/NYC Open Data 数据遵循各门户使用条款；个体受害者信息不落库（NEG-002）

---

## B. 项目内文档（本地直读，禁止修改）

| 文件 | 路径 | 用途 |
|------|------|------|
| 领域词汇表 | `CONTEXT.md` | 术语唯一权威（安全评级/可信度/越界查询/追问/Skill/输出控制管线） |
| PRD v2.0 | ~~`指导文档/SafePass_NYC_PRD_v2.0.md`~~（课程材料，已存档不随仓库分发） | 产品需求与 12 项决策的唯一来源（其决策已由 spec v1.2 全部承接） |
| ADR-0001 | `docs/adr/0001-rating-relative-threshold.md` | 评级=相对阈值+样本量门控 |
| ADR-0002 | `docs/adr/0002-profile-never-changes-rating.md` | 画像只进建议层 |
| 实施规格 v1.2 | `docs/specs/safepass-nyc-mvp-spec.md` | 实现与测试的唯一规格（含 D10 参考代码映射、D11/D11a 数据资产、D12 越界后置） |
| Ralph 任务池 | `RALPH.md` | 循环协议、T0–T8、Sensor 准入门 |
| 本文档 | `docs/resource-manifest.md` | 素材清单（本文件） |

## C. T0 三件套素材明细（Ralph T0 的输入）

### C1. 模拟 NYPD 数据集（脚本生成，无下载）

- **落盘路径**: `data/mock_nypd/`（CSV 或 SQLite，T0 实现者二选一，spec D11a）
- **生成方式**: 确定性脚本（禁 LLM），字段结构对齐 NYPD Complaint Data（见 D1/D2 字段规范）
- **硬性格式要求**: 警区号、犯罪类型（felony/misdemeanor 级）、时间戳（可判定昼夜）、来源标注字段
- **覆盖义务**: 评级四档 + 样本量各档（含 <10 ⚪ 案例）+ 0.7×/1.3× 边界附近案例（spec D11）
- **状态**: ☐ 未生成

### C2. 警区安全场所静态表（人工搜集，逐条核验）

- **落盘路径**: `data/safe_places/precinct_safe_places.json`（建议结构：`{precinct: {venues: [{type, name, address, phone, hours, source, verified}]}, general: {...}}`）
- **搜集条目模板**（每警区）：24h 便利店 ≥2、医院/急诊 ≥1、警局 1（含地址电话）；通用清单：911、311、五警局地址电话
- **来源优先级**: ①NYPD 官网警局页（D3）②机构官网 ③Google Maps 等地图服务（需二次核验）
- **核验规则**: 电话未核实 → `verified: false` 且只列机构名（F7-4 规则）；来源写入 `source` 字段
- **状态**: ☐ 未搜集（5 警区 × 模板条目 + 通用清单）

| 警区 | 中文名 | 条目采集状态 |
|------|--------|-------------|
| 19 | 上东区 | ☐ |
| 109 | 法拉盛 | ☐ |
| 5 | 唐人街 | ☐ |
| 90 | 威廉斯堡 | ☐ |
| 84 | 布鲁克林高地 | ☐ |

### C3. RAG 知识库文档 15 篇（人工撰写/搜集）

- **落盘路径**: `data/knowledge_base/*.md`（15 个文件 + 构建索引脚本 → FAISS/BM25 索引落盘 `data/knowledge_base/index/`）
- **建议目录**（5 警区 × 3 主题 = 15 篇；每篇标注信息来源，未记载项写"未记载"）：
  1. `{警区}` 区域安全概况与华人特定注意事项（含仇恨犯罪记录记载情况）
  2. `{警区}` 日常防范与华人常见诈骗提醒（电话诈骗/换汇诈骗）
  3. `{警区}` 紧急资源与中文服务（中文警员记载情况、社区组织、法律援助——无官方来源的不列电话）
- **撰写护栏**: 事实必须有来源；推测性内容标注"经验性建议"；警区中文警员等敏感信息无记载就写"未记载"（F7-3）
- **状态**: ☐ 未撰写（可按"骨架先行"策略：先写带"未记载"标注的骨架，RAG 链路即可测，内容后补）

## D. 外部数据源（下载链接与阶段归属）

> **阶段声明**: MVP 只用模拟数据（C1），外部真实数据 Phase 2 才接入（spec Out of Scope）。以下链接在 MVP 阶段的用途仅为**字段结构参考**与**内容核实**，不进入产品数据流。

| # | 数据集 | 链接 | MVP 用途 | 状态 |
|---|--------|------|---------|------|
| D1 | NYPD Complaint Data Historic | `https://data.cityofnewyork.us/Public-Safety/NYPD-Complaint-Data-Historic/qgea-i56i`（Socrata API: `https://data.cityofnewyork.us/resource/qgea-i56i.json`） | C1 字段结构规范（犯罪类型/警区/时间戳字段命名对齐） | ☐ |
| D2 | NYPD Complaint Data Current (YTD) | `https://data.cityofnewyork.us/Public-Safety/NYPD-Complaint-Data-Current-Year-to-Date-/5uac-w243`（ID 待下载前核验） | 同上，现行年度格式 | ☐ |
| D3 | NYPD 警局列表（precinct 地址电话） | `https://www.nyc.gov/site/nypd/bureaus/patrol/precincts-landing.page` | C2 警局条目官方来源（19/109/5/90/84 各警局页） | ☐ |
| D4 | NYPD Hate Crimes | 门户搜索 `https://data.cityofnewyork.us/browse?q=NYPD%20Hate%20Crimes`（数据集 ID 未核验，以门户搜索结果为准，勿硬记 ID） | C3 仇恨犯罪记载的结构参考 | ☐ |
| D5 | NYC 官方数据门户 | `https://opendata.cityofnewyork.us/` / `https://data.cityofnewyork.us` | 以上全部入口 | ☐ |
| D6 | 311/911 官方说明 | `https://portal.311.nyc.gov/` | C2 通用清单文案与号码核实 | ☐ |

**下载前核验规则**: 链接访问失败或数据集 ID 不符 → 从 D5 门户搜索数据集全名进入，**以页面实际 URL 为准**，并更新本表；禁止凭记忆拼 URL 下载。

## E. 参考代码索引（实现时按 spec D10 改写，不从头写）

> **存档说明（2026-09-05）**: `参考代码/` 目录为课程材料，因版权不可再分发已从仓库移除。下表保留原路径作 provenance 记录（MVP 各模块的改写出处）。

| 用途 | 路径（相对 `参考代码/`） |
|------|--------------------------|
| FC 路由 | `06_模型如何规划并调用工具/examples/openai_native_tool_calling.py`；`CASE-Function Calling/assistant_ticket_bot-3.py`；`CASE-私募基金运作指引问答助手（反应式）/fund_qa_langchain.py` |
| 输出控制管线 | `11_实战课：接入IM的旅游规划Agent/examples/helper_planning.py`；`RAG-cy/src/prompts.py`；`CASE-智能投研助手（深思熟虑）/deliberative_research_langgraph.py` |
| 混合检索 | `RAG-cy/src/retrieval.py`（双路召回+索引落盘模式）；~~`RAG-cy/src/reranking.py`~~（MVP 禁用） |
| Skill 提示词模板 | `05_实战_科技新闻简报/examples/helper.py`；`11_实战课/examples/helper_planning.py`；`12_模型驱动的决策模式及复杂回路设计（上）/examples/product_plan_patterns.py` |
| 工具注册 | `07_管理Agent的行动能力——注册、工具池与动态装载/examples/action_manager_example.py` |
| 会话状态 | `11_实战课/examples/demo_4_多轮对话.py` |
| 紧急关键词层 | `CASE-私募基金运作指引问答助手（反应式）/fund_qa_langchain.py` |
| 评级复算验收模式 | `10_让模型生成并运行指令——独立执行环境设计/examples/s05_model_instruction_end_to_end.py`；`10_.../examples/tests/test_course_contract.py` |
| 评估/观测（可选） | `CASE-openevals使用/*.py`；`CASE-langfuse使用/1-hybrid_wealth_advisor_qwen_agent_langfuse.py` |
| 依赖版本参考 | 各目录 `requirements.txt`（`RAG-cy`、`11_实战课` 为主） |

## F. 工具与依赖清单

| 类别 | 项 | 说明 |
|------|----|------|
| 必装 Python 包 | `pytest`、`faiss-cpu`、`rank-bm25`、`pydantic`、`json-repair` | 版本参考 E 节 requirements |
| 向量 embedding | `sentence-transformers`（本地模型） | 禁 API 依赖，保证离线（spec D11a） |
| 模型 API | 任一 OpenAI 兼容端点 | 仅 cassette 录制时需一次真实调用；测试回放不调用 |
| 存储 | SQLite（可选）/ 文件系统 | **禁止** MySQL/PG/向量数据库服务（D11a 显式排除） |
| 版本管理 | 无 git（网盘目录即版本载体） | fixture 与索引文件随目录同步 |

## G. 下载/生成状态登记（执行后更新）

| 素材 | 类型 | 获取方式 | 目标路径 | 状态 | 完成日期 |
|------|------|---------|---------|------|---------|
| C1 模拟数据集 | 生成 | 确定性脚本 `scripts/generate_fixtures.py` | `fixtures/nypd/`（mock_nypd.csv + manifest.json；实施时落在 fixtures/ 而非本表原写的 data/mock_nypd/） | ✅ 已生成 | 2026-09-04 |
| C2 安全场所表 | 人工搜集 | §C2 模板 + D3/D6 来源 | `fixtures/safe_places/precinct_safe_places.json` | ✅ 已录入 | 2026-09-04 |
| C3 知识文档 15 篇 | 人工撰写 | §C3 目录 + 护栏 | `fixtures/knowledge/*.md` | ✅ 已撰写 | 2026-09-04 |
| C3 检索索引 | 生成 | FAISS+BM25 构建脚本 `scripts/build_index.py` | `fixtures/index/` | ✅ 已生成 | 2026-09-04 |
| D1 字段规范参考 | 下载 | §D 链接 | `data/reference/nypd_complaint_schema.txt` | ☐ 未开始 | |

**变更日志**

| 日期 | 变更 |
|------|------|
| 2026-09-04 | 初版（v1.0）：B–G 六节，T0 三件套与外部源全部登记 |
| 2026-09-04 | §G 登记 T0 完成：三件套落盘 `fixtures/`（nypd / safe_places / knowledge / index），自检集 `tests/test_fixtures.py` 32 项全绿；config 的 city_mean_per_100k 已回填 144.6328 |
