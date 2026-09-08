# RALPH.md — Ralph Loop 运行配置

> **实现**: Matt Pocock 版 bash 循环（非 ralph-loop 插件）。入口 `./ralph-once.sh`，自治 `./afk-ralph.sh`。
>
> **归档**: MVP 任务池（T0–T8）见 `docs/archive/ralph-mvp-pool.md`（335 测试全绿，2026-09-04 关闭）。

## 当前任务

（空——票 #18 A3 已归档至下方迭代历史 ✅。Phase 3 波 1 余票见 `docs/specs/safepass-v3-spec.md`；下一张机械票候选 = N3 #25 一键复现，登记时须写完成承诺。）

## 完成承诺（Definition of Done）

每个 Ralph 任务登记时必须写明机器可验证布尔条件，例如：

- [ ] `python -m pytest tests/ -q` 全绿且无新 skip（禁裸跑 `pytest`——safepass 不在 sys.path，必 ModuleNotFoundError）
- [ ] 新能力经唯一接缝 `execute_query` 暴露，且有测试覆盖
- [ ] 无 `config/app.yaml` 之外的新阈值/警区号字面量（grep 自查）
- [ ] 测试离线可跑（新增 LLM 调用已录 cassette）

未写完成承诺的任务禁止进入 afk 循环。

## 迭代限制

- `afk-ralph.sh` 默认上限 10 次（`token-budget.json` 的 `max_iterations` 可压更低）
- 超限未达标 = **优雅失败**：停止迭代，状态留 `progress.txt`，人工排障后再续

## Token 预算

- 配置：`token-budget.json`
- 已落地（Phase 2 票 06）：$5/日成本熔断 + 请求级限流 + 成本 JSONL 上报 = `safepass/cost_control.py` 的 BudgetFusedClient 包装器，挂 LLMClient 注入接缝，生产客户端必经（唯一注入点 `safepass/llm_wiring.py` 的 `build_llm_client_from_env`）；2026-09-08 起全线统一 qwen-flash，无分供应商预算

## 模型路由

| 环境 | 模型 | 用途 |
|------|------|------|
| dev / test | DashScope `qwen-flash` | 开发、cassette 录制、金标基准（2026-09-08 全线统一） |
| prod | DashScope `qwen-flash` | 线上全部生成型 Agent（与 dev 同源；原 deepseek-chat 已下架） |

Ralph 循环本身跑在 dev 模型上；dev/prod 同源（qwen-flash）后，eval 套件不再承担跨供应商兼容性验证尾巴，只产出质量指标（README「质量基线」表，单一事实源 = `fixtures/eval/l2_results_v1.json`）。

## Back-Pressure（多维止损）

| 维度 | 触发 | 动作 |
|------|------|------|
| 迭代上限 | afk 达 max_iterations | 优雅失败，交回人工 |
| 测试红灯 | `pytest` 非全绿 | 当轮 promise 不得写 COMPLETE |
| 预算 | token-budget.json 超限 | 停止循环 |
| 范围蔓延 | 输出出现任务外文件改动 | 人工终止；任务需重登完成承诺 |
| 红线 | 触发 CLAUDE.md 红线任一 | 立即打回，不计迭代 |

## 迭代历史

| 日期 | 任务 | 迭代数 | 结果 |
|------|------|--------|------|
| 2026-09-04 | MVP T0–T8（ralph-loop 插件时代） | — | ✅ 335 green，归档 |
| 2026-09-05 | 票 07 真实数据入库 + 路径切换 | 1（人工会话接管秒挂循环） | ✅ 467 green 零 skip；真实数据入 fixtures/nypd_real（11770 条）；city_mean 回填 2769.4118；生产路径切 config runtime_dataset_path，测试世界钉 mock |
| 2026-09-08 | 票 #18 A3 one_liner 确定性数据钩子化 | 3（headless 秒挂）→ 人工会话接管 1 | ✅ `python -m pytest tests/ -q` 587 green；金标钩子断言入 tests/test_a3_one_liner_hooks.py（允许钩子集合成员 + 与 rating_explainable_basis 逐字一致 + ⚪ 零钩子）；LLM 零参与 one_liner（装配纯函数，suggestion 契约明示不写）；**遗留：L2 cassette 须重录**（judge 请求内嵌 one_liner 随本次变更漂移、指纹失效——棘轮表；重录前 `pytest tests/eval -q` 不可回放） |
| 2026-09-08 | 全线路由统一 qwen-flash（总 token 成本最低） | — | ✅ 587 绿 + eval 15 绿；A3 遗留的 L2 cassette 在 qwen-flash 上重录（150 交互，judge=flash：groundedness 0.980 / relevance 1.000 / 幻觉率 0.000）；合成预检重跑（24 回答）；README 兼容性尾巴消除（生产=dev 同源） |

## 优雅失败记录

| 日期 | 任务 | 轮数 | 卡住的布尔条件 | 人工介入结论 |
|------|------|------|----------------|--------------|
| 2026-09-05 | 票 07 真实数据入库 | 10（全部秒挂） | 未进入任务——headless `claude -p` 继承会话 `ANTHROPIC_MODEL=kimi-for-coding`，报 `unrecognized_model` | 环境配置事故非任务失败，不计票；以 `env -u ANTHROPIC_MODEL` 重启循环 |
| 2026-09-08 | 票 #18 A3 one_liner 确定性数据钩子化 | 3（全部秒挂，ralph-run-20260908-015839/020340/0220…22.log） | 未进入任务——headless `claude -p` 在 `generate_session_title` 报 `unrecognized_model`（settings.json 兜底 deepseek-v4-flash，headless 不认；即使 .launch-a3.sh 显式 ANTHROPIC_MODEL=deepseek-v4-pro 也复现），零主调用产物 | 环境配置事故非任务失败，不计票；人工会话接管完成实现与验证（587 green）；提交待人工 push；L2 cassette 重录留待有网络/预算环境（棘轮表） |
