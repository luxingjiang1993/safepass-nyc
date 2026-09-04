# SafePass NYC — 工程骨架与环境说明

> 产品文档以 `docs/specs/safepass-nyc-mvp-spec.md`（v1.2）为准；MVP 任务池（已归档）见 `docs/archive/ralph-mvp-pool.md`；领域词汇见 CONTEXT.md。
> 本文档只回答：**目录里有什么、环境怎么搭、命令怎么跑**。

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

## 常用命令

```bash
pytest -q                # 全部测试（Ralph 循环的判定依据）
pytest -q -m perf        # 性能断言：查询 P95 < 8s、紧急 P95 < 2s
python scripts/generate_fixtures.py   # 重新生成 fixture 三件套（T0 实现后可用；要求同脚本同参数同输出）
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
│   └── skills/             #   建议生成等 Skill：提示词模板 + Pydantic 契约 + 业务校验规则
├── tests/                  # 10 个 pytest 测试集（每个 Ralph 任务先写红再转绿）
│   └── cassettes/          # 录制回放：固定 LLM 行为，离线可重复
├── scripts/
│   └── generate_fixtures.py  # fixture 确定性生成脚本（禁 LLM，spec D11）
├── fixtures/               # 数据资产三件套，随仓库版本化（spec D11）
│   ├── nypd/               #   ①模拟 NYPD 数据集（CSV/JSON 或 SQLite，T0 二选一）
│   ├── safe_places/        #   ②警区安全场所静态表（5 警区 24h 清单 + 通用清单）
│   ├── knowledge/          #   ③RAG 知识库文档（15 篇预计算安全报告）
│   └── index/              #   FAISS 本地索引 + BM25 pickle（可由 fixture 离线重建）
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
