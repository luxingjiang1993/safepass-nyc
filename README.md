# SafePass NYC — 工程骨架与环境说明

> 产品文档：MVP 以 `docs/specs/safepass-nyc-mvp-spec.md`（v1.2，历史档案）为准；Phase 2 见 `docs/specs/safepass-v2-spec.md`（M1–M4，已交付）；Phase 3 波 1 见 `docs/specs/safepass-v3-spec.md`（**已收口**）；波 2 第二刀见 `docs/specs/safepass-v3-wave2-second-knife-spec.md`（**已收口**，GitHub `#16`–`#34` 已关）。MVP 任务池（已归档）见 `docs/archive/ralph-mvp-pool.md`；领域词汇见 CONTEXT.md；架构决策见 `docs/adr/`。
> 本文档只回答：**产品主路径是什么、目录里有什么、环境怎么搭、命令怎么跑**。

## 产品主路径（叙事与代码对齐，E1/ADR-0003）

一句话：查询地点 → NYPD 数据 + 混合检索 → 四级安全评级 → **AI 建议**（LLM 措辞、数据定调）+ 场景化追问。LLM 与确定性的分工是本项目最核心的架构决策（ADR-0003），对外承诺与代码逐字一致：

| 环节 | 谁来做 | 承诺 |
|------|--------|------|
| 安全评级 / 可信度 / 越界判定 / 紧急检测 | **纯函数，零 LLM**（ADR-0001/0002，红线 2） | 同输入同输出，可复算可解释 |
| `one_liner` 核心结论行 | **确定性模板 + 数据钩子填空，LLM 零参与** | 首屏最显眼的一行不可被注入污染 |
| 建议正文（3–5 条） | **Suggestion Skill = 唯一由 LLM 生成的用户可见文本** | 输出契约强制携带可核对的检索依据（`suggestion_grounds`：quote 逐字命中检索原文 + doc_id 闭合）；业务校验不过 → 有限重试 → 仍不过降级确定性模板。降级明示不静默：契约 `suggestions_source` 标注来源；熔断/网络故障另置 `llm_degraded` + 用户可见降级横幅 |
| 混合检索（FAISS + BM25 → RRF top-3）/ 追问细分（followup.classify） | **确定性，零 LLM** | 检索排序与追问承接不依赖模型自觉 |
| 用户画像（性别/身份/场景标签） | **永不离开服务进程** | 不进入任何 LLM 请求体（SuggestionPack 结构上无画像字段），只在本机做建议排序与时间提示；隐私页「零上传」口径见 `/privacy` |

质量数字（L1 金标 / groundedness / 幻觉率等七项）见下文「质量基线」一节，单一事实源 = eval 套件工件，README 只作投影。

## 环境要求

| 项 | 要求 |
|----|------|
| Python | **3.11 – 3.13**（不要用 3.14：`faiss-cpu` 无 3.14 预编译 wheel，会退化为源码编译失败） |
| OS | Windows / macOS / Linux 均可；测试必须能离线通过 |
| 数据库 | **无**（spec D11a：不装 MySQL/PostgreSQL/向量数据库服务；SQLite 单文件可选） |

## 环境搭建（首次）

```bash
# 1. 创建虚拟环境（以 Python 3.12 为例）
python -m venv .venv

# 2. 激活
.venv\Scripts\activate          # Windows cmd / PowerShell
source .venv/Scripts/activate   # Windows Git Bash
source .venv/bin/activate       # macOS / Linux

# 3. 安装依赖
pip install -U pip
pip install -r requirements.txt
```

首次安装 `sentence-transformers` 会连带安装 PyTorch（体积较大），属正常；embedding 模型在首次构建索引时本地下载，之后离线可用。

## 质量基线（M1 eval 套件，spec v2）

七项指标随 eval 套件产出，README 只作投影，单一事实源 = 套件工件（改动指标须重跑套件并同步本表，漂移由 `tests/test_readme_baselines.py` 守住）：

| 指标 | 基线（Skill 路径主指标） | 对照（模板路径，同子集） | 口径（分子/分母） | 复算 |
|------|------|------|------|------|
| L1 金标通过率 | 100%（50/50） | — | 全字段断言通过的金标条目数 / 金标条目总数（契约类型/警区/越界降级分支与金标 expect 逐条一致；命名刻意不叫"路由准确率"——L1 断言的是全契约字段，路由只是其中一轴） | `python -m pytest tests/test_golden_set.py -q` 全绿即 100% |
| groundedness（L2） | 1.000 | 1.000 | Skill 路径 groundedness judge 分数之和 / Skill 覆盖子集条目数（B1 口径：分母 = suggestions_source=skill 的条目，eligible 24 条中实际 22 条，覆盖数受 config `eval.skill_coverage_min` 护栏；judge 口径 v5 把 Skill 建议的事实性声明纳入判定，grounds 引文只作依据、不构成声明） | `python -m pytest tests/eval -q` cassette 回放，工件 `fixtures/eval/l2_results_v1.json` |
| 幻觉率（L2） | 0.000 | 0.045 | hallucinated=true 的条目数 / 同 Skill 覆盖子集条目数（二元判定，judge = qwen-flash，prompt 版本锁定进 config） | 同上 |
| relevance（L2） | 1.000 | 1.000 | 同 Skill 覆盖子集 relevance judge 分数之和 / 子集条目数 | 同上 |
| actionability（B2） | 1.000 | 1.000 | 命中动作词表的建议条目占比（确定性规则特征，词表 = config `eval.quality.action_verbs`；下限护栏——模板通用建议同款命中，此维度不区分两路径） | 同上 |
| specificity（B2） | 0.911 | 0.000 | 建议条目与任一 grounds 引文共享 ≥ config `eval.quality.anchor_min_chars` 字公共子串的占比（确定性 union 匹配；纯最长公共子串不校验类别——地名/作案手法/通用措辞都计命中，保守的「本区情报锚定覆盖下限」；模板路径无 grounds 恒 0） | 同上 |
| 矛盾率（B2） | 0.000 | 0.000 | 夜间方向断言与 charts 昼夜计数矛盾的条目占比（确定性算术核对，LLM 零参与，P6 定案 2；否定表达与疑问句豁免） | 同上 |

- 两路径对照（B1，issue 04）：主指标 = Skill 路径 Skill 覆盖子集（22/24，覆盖数受 config 护栏；模板降级路径 28 条单列 marker、不计入主 groundedness）；对照列 = 同一子集跑确定性模板路径（零管线 LLM）。收口条件 = 主指标 Skill ≥ 模板（hallucination/矛盾率取 ≤），由 `python -m pytest tests/eval -q` 机器断言（工件 `comparison.comparison_ok`）——打不过就迭代到打得过再收，不修 DoD。
- B2 质量维度（issue 05）：actionability/specificity/矛盾率三维全部确定性实现（规则特征 + 算术核对，LLM 零参与——宪法①⑤ + P6 定案 2），不新增 judge 调用；回归门 = config `eval.quality` 的 min_*/max_*，由 `python -m pytest tests/eval -q` 机器断言。
- C1b（issue 33）：覆盖内契约增 `rating_rationale` 后 judge 请求指纹变化，已重录 `l2_judge*.json` / `l2_skill.json` 与 `fixtures/eval/l2_results_v1.json`；judge 提示词版本未改；N2 三列 cassette 未动；L2 仍不进默认 `tests/` 收集。
- L2 套件离线可跑（judge 与 Skill 调用走 cassette 回放，零真实 API）；录制工件 `fixtures/eval/l2_results_v1.json` 由 `python scripts/record_l2_cassette.py` 一次性产出（需真实 `DASHSCOPE_API_KEY`）。
- N2 基线对照（issue 26）：同一 20 条金标上裸 LLM / 无约束 RAG / SafePass 三列数字与失败样例见 `docs/baseline-vs-safepass.md`（`python -m pytest tests/eval/test_n2_three_column.py -q` 回放；**不进**默认 `tests/` 基线）。
- 生产与 dev 同源（2026-09-08 起全线统一 DashScope `qwen-flash`，选型原则 = 总 token 成本最低）：L2 套件指标即生产模型指标，无跨供应商兼容性验证尾巴。

## 审阅者路径（本地 3 命令，Windows 可跑）

装依赖 → 跑 5 条固定 query（安全 + 越界 + 紧急）→ 开本地页。无 key 走确定性路径（one_liner 数据钩子 + 模板建议；grounds 空态打印「通用建议」）；有 key（`LLM_API_KEY` 三件套或 `DASHSCOPE_API_KEY`）走 Suggestion Skill。5 条 query 文本与金标子集对齐，不读真实 API key、不用非 fixture 数据。

直跑 demo / 前端走运行时数据集 `fixtures/nypd_real`（`config data_source.runtime_dataset_path`）；pytest 钉 mock。两边评级可以不同，**不要把 demo 改钉 mock**（两套数据世界是票 07 定案）。

```bash
pip install -r requirements.txt
python scripts/demo_queries.py
python frontend/app.py
```

须在仓库根目录执行。`frontend/app.py` 会把根目录加入 `sys.path`（直接跑脚本时默认 path 是 `frontend/`，否则 `safepass` 找不到）。

`python scripts/demo_queries.py --open` 可在摘要打完后于本进程打开本地页（阻塞；Ctrl+C 停止）。与 E7 共用同一入口，无第二套 demo。

## 常用命令

```bash
python -m pytest tests/ -q       # 全部测试（唯一判定命令；裸跑 pytest 会 ModuleNotFoundError——safepass 不在 sys.path）
python -m pytest tests/ -q -m perf   # 性能断言：查询 P95 < 8s、紧急 P95 < 2s
python -m pytest tests/eval -q   # L2 eval 套件（judge 走 cassette 离线回放，独立于基线）
python scripts/generate_fixtures.py   # 重新生成 fixture 三件套（T0 实现后可用；要求同脚本同参数同输出）
python scripts/demo_queries.py        # N3/E7 审阅者路径：5 条固定 query 打印契约摘要（无 key 确定性）
```

## Ralph loop

- 人工在环：`./ralph-once.sh "<任务>"`
- 自治循环：`./afk-ralph.sh "<任务>" [上限]`（默认 10 次迭代上限）
- 完成信号：agent 在输出最后一行单独给出 promise 完成标记。注意：该标记必须独占一行才算数，写在别的内容里无效。

## 环境变量

复制 `.env.example` 为 `.env`。测试用 fake/cassette 固定 LLM 行为，**离线跑测试不需要真实 key**；只有"录制 cassette"和"LLM 层真实准确率在线验证"（人工验收项）才需要。

## 目录结构

```
.
├── config/
│   └── app.yaml            # 集中配置：全库唯一允许出现阈值/档位/警区号字面量的文件（spec D4）
├── safepass/               # 后端包：唯一接缝 = execute_query(查询文本, 会话画像, 会话状态) → 结构化响应契约
│   ├── pipeline.py         #   管线编排与唯一接缝（spec D1）
│   ├── contracts.py        #   结构化响应契约：四种形态的判别联合（spec D3）
│   ├── config_loader.py    #   配置加载（唯一读 config/app.yaml 的入口）
│   ├── session_state.py    #   会话状态：会话级画像 + 上轮结构化结果，零持久化（spec D2/D6）
│   ├── emergency.py        #   紧急检测第一层（关键词静态表，无 LLM）+ 静态紧急组装（spec D7）
│   ├── routing.py          #   FC 路由层：area_safety_query / area_comparison / follow_up / degraded_response / emergency_help
│   ├── data_agent.py       #   数据 Agent：按警区聚合模拟 NYPD 数据集（per-100k、sample_size、Top5、昼夜分布）
│   ├── rating_engine.py    #   评级引擎：纯函数，零 LLM、零画像（ADR-0001/0002）
│   ├── intel_agent.py      #   情报 Agent：FAISS + BM25 混合检索，RRF 融合 top-3（不引入重排）
│   ├── output_pipeline.py  #   输出控制管线：生成→解析/修复→结构+业务校验→有限重试（spec D2）
│   └── skills/             #   建议 Skill（LLM 措辞+数据定调，ADR-0003）：提示词模板 + Pydantic 契约 + grounds 业务校验；画像零接触
├── tests/                  # pytest 测试集（每个 Ralph 任务先写红再转绿；数量以实际文件为准）
│   ├── cassettes/          #   录制回放：固定 LLM 行为，离线可重复
│   └── eval/               #   L2 eval 套件（LLM-as-judge，cassette 回放；独立运行，不进默认基线）
├── scripts/                # 确定性脚本（以实际文件为准）：generate_fixtures（fixture 生成，禁 LLM）、
│                           #   build_index（检索索引）、fetch_nypd（真实数据 adapter）、
│                           #   record_l2_cassette（L2 录制）、record_n2_cassette（N2 三列录制）、serve（容器入口）、demo_queries（N3/E7 审阅者路径）、recompute_city_mean 等
├── fixtures/               # 数据资产，随仓库版本化（spec D11）
│   ├── nypd/               #   ①模拟 NYPD 数据集（测试世界钉 mock）
│   ├── nypd_real/          #   ②真实 NYPD 数据入库（scripts/fetch_nypd.py 产出，生产运行时数据集）
│   ├── safe_places/        #   ③警区安全场所静态表（5 警区 24h 清单 + 通用清单）
│   ├── knowledge/          #   ④RAG 知识库文档（15 篇预计算安全报告）
│   ├── index/              #   FAISS 本地索引 + BM25 pickle（可由 fixture 离线重建）
│   └── eval/               #   金标 golden_set_v1.json + L2 工件 l2_results_v1.json + N2 工件 n2_results_v1.json
├── frontend/               # 前端薄渲染层（循环外，标准 Implement；消费契约、不承载业务逻辑）
├── docs/                   # spec / ADR / 资源清单（产品文档，唯一事实源）
├── .scratch/safepass-nyc-mvp/issues/  # ticket 文件（01–12，MVP 过程档案）
└── docs/archive/                      # 归档：MVP Ralph 任务池等历史文档

> **存档说明**: 原 `参考代码/`、`指导文档/` 为课程材料（spec D10 改写来源），因版权不可再分发，未进入本仓库。D10 映射表与 `docs/resource-manifest.md` §E 保留原路径作 provenance 记录。
```

## 红线速览（详见 RALPH.md"禁止事项"）

- 阈值系数（0.7/1.3）、样本量档位、覆盖警区清单**只存在于 `config/app.yaml`**，代码一律读配置。
- 不让 LLM 参与评级计算、不让画像进入评级输入（ADR-0001/0002）。
- 越界判定走 D12 确定性后置：解析警区 ∉ 覆盖 → 无条件 DegradedResult。
- 数据生成脚本不得使用 LLM；fixture 必须确定性可复现。
- 唯一测试接缝是 `execute_query`，不为管线内部子模块另设接缝、不 mock 管线内部。
