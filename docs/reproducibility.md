# SafePass NYC — 换机器不漂（N6 版本钉）

审阅者 30 秒看懂：**同一提交在另一台机器上，检索索引、离线评测回放、依赖图不该漂。**  
「能跑」走 README「审阅者路径」（`pip install` → `python scripts/demo_queries.py` → `python frontend/app.py`）。本页不重做那套命令，只钉死会让数字和索引对不齐的版本指针。

密钥只存在本机 `.env`（模板 `.env.example`，仓库不入库）。本页不列任何 API key。

## Python 依赖怎么锁

- 运行时与检索栈：`requirements.txt` **三段式 `==` 钉死**（`pydantic` / `faiss-cpu==1.9.0.post1` / `sentence-transformers==6.0.1` 等）。不要改成 `>=`。
- Python：**3.11–3.13**。不要用 3.14（`faiss-cpu` 无预编译 wheel）。
- 容器里的 `torch==2.14.x` 与 `sentence-transformers==6.0.x` 成对锁定，由 `tests/test_dockerfile.py::test_build_dependencies_pinned` 守住。单侧升级必须先实测再两侧一起改。
- 测试收集器：`pytest>=8.0`（唯一未钉补丁号；跑测试用 `python -m pytest tests/ -q`，禁止裸跑 `pytest`）。

换依赖版本 = 刻意事件：先跑唯一判定，涉及索引则重建 `fixtures/index/` 并跑检索回归。

## 索引：pickle protocol=5

BM25 落盘在 `scripts/build_index.py`，**固定 `protocol=5`**（有环境默认 protocol=4，不固定则跨 Python 小版本加载失败）。文件：

- `fixtures/index/bm25.pkl`

重建：`python scripts/build_index.py`；自检：`python scripts/build_index.py --check`。

## embedding 模型标识

单一事实源 = 构建脚本常量 + 落盘 `fixtures/index/meta.json` 的 `embedding_model`：

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

本地 `sentence-transformers` 加载，禁 embedding API。首次在能联网的环境下载进 Hugging Face 缓存后，测试与重建走离线（`HF_HUB_OFFLINE`）。换模型名必须改脚本、重建索引、更新本页与 meta，并当作 N6 事件。

## FAISS ASCII 路径

FAISS 在含非 ASCII 的绝对路径上会初始化/写盘失败（Windows 中文目录尤其常见）。约束：

- 索引目录相对仓库根必须是纯 ASCII：`fixtures/index/`
- 文件名纯 ASCII：`docs.faiss`、`bm25.pkl`、`meta.json`
- 构建时先 `chdir` 到该目录再写相对文件名（`scripts/build_index.py`），避免把中文盘符路径传给 FAISS

克隆仓库的路径可以含中文（本项目作者环境即是）；**不要把索引建到另一处中文路径，也不要把 `fixtures/index` 改成非 ASCII 目录名。**

## cassette / judge 版本指针

L2 考官与回放路径锁在 `config/app.yaml` 的 `eval` 节（改提示词、数据世界或进 `model_dump` 的字段须重录 cassette）：

| 指针 | 值 |
|------|-----|
| judge 模型 | `qwen-flash` |
| Skill 路径 judge cassette | `tests/cassettes/l2_judge.json` |
| 模板路径 judge cassette | `tests/cassettes/l2_judge_template.json` |
| Skill 管线 cassette | `tests/cassettes/l2_skill.json` |
| groundedness 提示词 | `sp-groundedness-v5` |
| hallucination 提示词 | `sp-hallucination-v5` |
| relevance 提示词 | `sp-relevance-v1` |
| L2 录制工件 | `fixtures/eval/l2_results_v1.json` |

离线回放：`python -m pytest tests/eval -q`（**不进**默认 `tests/` 基线）。重录：`python scripts/record_l2_cassette.py`（需本机 `DASHSCOPE_API_KEY` 与预算；命令与变量名见 README / `.env.example`，**不要把 key 贴进本页**）。

N2 三列对照 cassette（`tests/cassettes/n2_*.json`）与 L2 分开；本刀禁止误伤 N2。

## 两套数据世界（不要钉错）

- **pytest**：模块级钉 `SAFEPASS_DATASET_PATH` → mock（`fixtures/nypd/`）。金标、检索回归、cassette 指纹建在 mock 世界上。
- **demo / 前端运行时**：`fixtures/nypd_real/`。两边评级可以不同，不要把 demo 改钉 mock。

确定性评级 / 可信度 / 越界不依赖 LLM，换机器只要求同一 fixture + 同一配置。Skill 路径措辞随模型采样会变。

## 波 1 指标量级（投影）

权威数字 = `fixtures/eval/l2_results_v1.json` + `python -m pytest tests/test_golden_set.py -q`；README「质量基线」是同一投影。按上列指针、同一 mock 世界回放，应落在这一量级（精确到录制工件）：

| 指标 | Skill 路径量级 |
|------|----------------|
| L1 金标通过率 | 100%（金标全条） |
| groundedness（L2） | 1.000 |
| 幻觉率（L2） | 0.000 |

数字与 README 漂移由 `tests/test_readme_baselines.py` 守住；本页只钉量级与指针，不另起第二套基线表。
