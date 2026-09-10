# SafePass NYC — CLAUDE.md

面向编码 agent 的宪法与运行配置。Cursor 等工具经根目录 `AGENTS.md` 指向本文。领域词汇见 `CONTEXT.md`，架构决策见 `docs/adr/`，issue 流程见 `docs/agents/`。

## 项目一句话

面向纽约中文用户（留学生、新移民、访客）的 AI 安全情报产品：查询地点 → NYPD 数据 + 混合检索 → 四级安全评级 + 场景化建议。MVP 与 Phase 2 已关闭；Phase 3 **波 1 已收口**；**波 2 第一刀已收口**；**波 2 第二刀已收口**（GitHub `#16`–`#34` 已关，见 `docs/specs/safepass-v3-wave2-second-knife-spec.md`）。波 2 其余未经用户点名不得开票。测试基线以「唯一判定」为准。

## 唯一接缝与唯一判定

- **唯一接缝**：`execute_query(查询文本, 会话画像, 会话状态)`（`safepass/pipeline.py`）。后端全部能力经此进入。
- **唯一判定**：`python -m pytest tests/ -q` 全绿（基线 735，随票递增）。没有"看起来对了"——测试不过就是没过。**禁止裸跑 `pytest`**：`safepass` 不在 sys.path（pytest.ini 未配 pythonpath），裸跑必 ModuleNotFoundError。
- **B7 建议变更回归门（壳）**：改建议提示词或 Skill（`safepass/skills/suggestion.py`）时，必须跑 L2 子集 `python -m pytest tests/eval -m l2 -q`。默认行为基线因 `tests/conftest.py` 的 `collect_ignore = ["eval"]` **仍然不收集 L2**；`python -m pytest tests/ -m l2` 会收集到 0 条，不得当回归。本刀不做「故意改坏 prompt → 红」满门闩。整目录（含 N2）仍是 `python -m pytest tests/eval -q`。

## Karpathy 宪法

1. **简单优先**：能用 Python 标准库 + 确定性计算解决的，绝不引入框架、服务或 LLM。评级、越界判定、可信度档全部是纯函数。
2. **能复现才算完成**：同一输入任何机器上输出一致。测试离线可跑（cassette/fixture），不依赖网络。
3. **显式 > 隐式**：阈值、警区号、档位字面量只活在 `config/app.yaml`，代码经 `safepass/config_loader.py` 读取。
4. **删除 > 抽象**：遇到重复先想删，再想合并。不为假想需求建抽象层。
5. **LLM 只做它不可替代的事**：结构化抽取、检索改写、建议生成。凡能用规则、算术、查表判定的（评级、越界、警区映射），LLM 一律不掺和。

## 红线（违反 = 立即打回）

1. 阈值系数 / 样本量档位 / 警区号字面量禁止出现在 `config/app.yaml` 之外（含测试里的魔法数字，fixture 例外）。
2. LLM 不参与安全评级、可信度、越界判定——这三样是确定性后置（D12）。
3. 禁服务型数据库（Postgres/MySQL/Redis/Mongo）；持久化 = 文件 + fixture。
4. 越界查询必须走诚实降级分支：告知无数据、不编造、给通用建议 + 紧急资源。
5. 测试必须离线可跑：LLM 调用走 VCR cassette，数据走 fixture。

## 模型路由

| 环境 | 模型 | 说明 |
|------|------|------|
| dev / test | DashScope `qwen-flash` | cassette 与金标以此为准（2026-09-08 起全线统一；原 qwen-turbo 官方已弃用） |
| prod | DashScope `qwen-flash` | 与 dev 同源（原 DeepSeek `deepseek-chat` 已下架）；$5/日预算熔断 + 限流 |

## Ralph 特化（Matt Pocock 版 bash 循环）

- 迭代入口：`./ralph-once.sh "<任务>"`（人工在环，单次迭代）
- 自治循环：`./afk-ralph.sh "<任务>" [max_iterations]`（默认 10 次上限，`<promise>COMPLETE</promise>` 退出）
- 任务源：当前 Phase 的 `PRD.md`；跨迭代记忆 = `progress.txt`
- 完成承诺：机器可验证布尔条件，写进 `RALPH.md`（如 "`python -m pytest tests/ -q` 全绿"）
- **不再使用 ralph-loop 插件**；`.claude/ralph-loop.local.md` 已废弃待删

## Loop 硬限制

- afk-ralph 迭代上限默认 10，超限未达标 = 优雅失败：把失败状态写进 `progress.txt` 和 `RALPH.md` 迭代历史，停止烧 token，交回人工。
- Ralph 自治仅限机械性任务且前置条件齐全（fixture 就位、完成承诺明确、测试接缝存在）。探索性/架构性任务禁止进 afk 循环。
- 单日 token 预算见 `token-budget.json`，熔断逻辑 Phase 2 与 $5/日成本熔断一起落。

## 错误 → 约束棘轮表

每出一次事故，在此加一行约束，只增不改。新 agent 读表即知雷区。

| 事故 | 根因 | 新增约束 |
|------|------|----------|
| BM25 索引跨环境加载失败 | pickle 协议版本漂移 | 索引固定 pickle protocol=5（`scripts/build_index.py`） |
| FAISS 在中文路径下初始化失败 | FAISS 对非 ASCII 路径不兼容 | 索引必须建在纯 ASCII 路径，路径配置进 `config/app.yaml` |
| 检索排序被 community_info 干扰 | 把社区信息当检索信号排序 | community_info 只走 meta 警区锚定，不参与检索排序 |
| 检索结果随依赖版本漂移 | 无锁定查询集 | 14 条查询实测锁定为回归基线（见 `docs/archive/ralph-mvp-pool.md`） |
| 票 07 改 city_mean 后 L2 套件静默回归 | judge 请求内嵌证据文本随数据世界漂移，cassette 指纹全失效（conftest collect_ignore 藏出默认基线） | L2 世界钉 mock 快照（`tests/eval/l2_runner.py` 模块级钉子）；改影响 judge 请求内容的值（数据世界/提示词/口径）必须重录 L2 cassette 并跑 `python -m pytest tests/eval -q` 验证 |

## Git 纪律

- push 由用户自己执行（需 VPN）。agent 只 commit。
- commit message 末尾：`Co-Authored-By: Claude Code <noreply@anthropic.com>`
- `docs/specs/` 下 MVP spec（v1.2）是历史档案，正文不动；Phase 2 新 spec 另起文件。

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`gh` CLI); repo inferred from `git remote -v`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles, label string = role name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` (glossary) + `docs/adr/`. See `docs/agents/domain.md`.
