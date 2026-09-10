# SafePass NYC — Agent 入口

本仓库宪法 = [`CLAUDE.md`](CLAUDE.md)，全文为最高优先级规则。另读 [`CONTEXT.md`](CONTEXT.md) 与 [`docs/adr/`](docs/adr/)。

Cursor / Codex / 其他编码 agent 开会话先读宪法，再动手。本文件与 `CLAUDE.md` 冲突时以 `CLAUDE.md` 为准。

## 当前阶段（先读，避免把已做的票再做一遍）

Phase 3 **波 1 已收口**；**波 2 第一刀已收口**；**波 2 第二刀已收口**（2026-09-10）：GitHub `#16`–`#34` 已关（第二刀 `#30` C1a、`#31` B4、`#32` N4、`#33` C1b、`#34` D5+C6）。不要再实现 N1 骨架、N3 一键复现、N2 三列对照、A4 依据槽、C1 评级依据、B4 检索回归、N4 脏输入或 D5/C6 覆盖诚实。不要把 demo 钉到 mock 数据集。波 2 其余票只在用户明确点名后动手。权威现状：`docs/specs/safepass-v3-spec.md` 文首 + `docs/specs/safepass-v3-wave2-second-knife-spec.md` + git log + `python -m pytest tests/ -q`。

## 唯一接缝与唯一判定

- 唯一接缝：`execute_query(查询文本, 会话画像, 会话状态)`（`safepass/pipeline.py`）。
- 唯一判定：`python -m pytest tests/ -q` 全绿。禁止裸跑 `pytest`（`safepass` 不在 sys.path）。
- L2 eval 套件：`python -m pytest tests/eval -q`（`tests/conftest.py` 的 `collect_ignore` 刻意排除出默认基线）。
- **B7 壳**：改建议提示词或 Skill 必须 `python -m pytest tests/eval -m l2 -q`。默认 `python -m pytest tests/ -q` 仍不收集 L2。不做故意改坏 prompt 满门闩。

## 高危雷区（操作层）

- **L2 cassette 棘轮**：改影响 judge 请求内容的值（数据世界 / 提示词 / 口径 / 新字段进 `model_dump`）必须重录 `tests/cassettes/l2_judge*.json`，再跑 eval 套件。重录：`set -a && source .env && set +a && python scripts/record_l2_cassette.py`（需网络 + `DASHSCOPE_API_KEY` + 预算）。
- **B7 建议变更挂钩**：改 `safepass/skills/suggestion.py` 提示词或 Skill 逻辑后，默认行为基线不够；必须 `python -m pytest tests/eval -m l2 -q`。指纹若因提示词漂移失效，先走上面的 cassette 棘轮，再跑该子集。
- **测试世界钉不要拆**：`tests/conftest.py`、`tests/eval/l2_runner.py`、`tests/injection_report.py` 三处模块级钉 `SAFEPASS_DATASET_PATH` 到 mock 数据集。金标 / 复算 / cassette 指纹建在 mock 世界上；生产数据在 `fixtures/nypd_real`。
- **`.env` 永不入库、永不读进上下文**。
- **Git**：push 由用户自己执行（需 VPN）；agent 只 commit。`git add` 用显式路径，禁止 `git add -A`。commit 末尾带 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- **不要跑 headless ralph 循环**（`afk-ralph.sh` 已有优雅失败记录）；机械票人工接管。
- **Windows**：控制台 GBK 下 Python 中文乱码是显示问题；`git show | python` 管道会损坏 UTF-8，必须重定向文件。
- **`progress.txt` 正文从 A3 段起是历史**，文首「现状」节才有效。不要把旧「cassette 失效」当待办。
