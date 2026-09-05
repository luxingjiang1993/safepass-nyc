# RALPH.md — Ralph Loop 运行配置

> **实现**: Matt Pocock 版 bash 循环（非 ralph-loop 插件）。入口 `./ralph-once.sh`，自治 `./afk-ralph.sh`。
>
> **归档**: MVP 任务池（T0–T8）见 `docs/archive/ralph-mvp-pool.md`（335 测试全绿，2026-09-04 关闭）。

## 当前任务

（无 — 等待 Phase 2 PRD.md 落到 `docs/specs/` 后在此登记）

## 完成承诺（Definition of Done）

每个 Ralph 任务登记时必须写明机器可验证布尔条件，例如：

- [ ] `pytest tests/ -q` 全绿且无新 skip
- [ ] 新能力经唯一接缝 `execute_query` 暴露，且有测试覆盖
- [ ] 无 `config/app.yaml` 之外的新阈值/警区号字面量（grep 自查）
- [ ] 测试离线可跑（新增 LLM 调用已录 cassette）

未写完成承诺的任务禁止进入 afk 循环。

## 迭代限制

- `afk-ralph.sh` 默认上限 10 次（`token-budget.json` 的 `max_iterations` 可压更低）
- 超限未达标 = **优雅失败**：停止迭代，状态留 `progress.txt`，人工排障后再续

## Token 预算

- 配置：`token-budget.json`
- Phase 2 落生产 $5/日成本熔断（DeepSeek）+ dev DashScope 预算，熔断器挂 `safepass/llm_client.py` 接缝

## 模型路由

| 环境 | 模型 | 用途 |
|------|------|------|
| dev / test | DashScope（Qwen） | 开发、cassette 录制、金标基准 |
| prod | DeepSeek `deepseek-chat` | 线上全部生成型 Agent |

Ralph 循环本身跑在 dev 模型上；eval 套件负责验证生产模型兼容性（Phase 2）。

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

## 优雅失败记录

| 日期 | 任务 | 轮数 | 卡住的布尔条件 | 人工介入结论 |
|------|------|------|----------------|--------------|
| 2026-09-05 | 票 07 真实数据入库 | 10（全部秒挂） | 未进入任务——headless `claude -p` 继承会话 `ANTHROPIC_MODEL=kimi-for-coding`，报 `unrecognized_model` | 环境配置事故非任务失败，不计票；以 `env -u ANTHROPIC_MODEL` 重启循环 |
