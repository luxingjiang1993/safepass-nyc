# SafePass 全程里程碑（当前视角）

> 粗略参考用，不追细节。视角日期：2026-09-05。
> 已完成：MVP（335 tests green）+ Phase 0 harness（CLAUDE.md / ralph 循环 / GitHub tracker）。

## Phase 2（当前，预算 2–3 周）

| 里程碑 | 内容 | 出口标准 |
|--------|------|---------|
| **M1 eval 套件** | L1 断言扩展 + L2 LLM-judge（openevals 改写）+ 50 金标 + judge 版本锁定 | 套件全绿，README 有三项指标基线 |
| **M2 数据 + 成本** | NYC 真实数据 adapter + 熔断/限流/成本上报三件套 | 真实 fixture 入库；熔断可测；老测试不破 |
| **M3 信任 + 用户** | 隐私页/免责页 + 前端作品集级打磨 + 合成用户预检 + 真人 5 人访谈 | 页面可访问；访谈发现 issue 化 |
| **M4 部署** | Hetzner + Docker + Caddy HTTPS + 域名 + UptimeRobot | 公开 URL 可访问；"真实运营五条"全部兑现 |

**此刻坐标**：M0 done，M1 未开工（spec v2 写作中）。

## Phase 3（上线后，按需触发）

- **地理编码扩覆盖**：直连 Google Geocoding API（禁 MCP 绕道），addressing 从别名表升级；走 ADR（隐私披露 + 运行时外部依赖）
- **可观测性升级**：Langfuse 自托管评估（需修订"禁服务型数据库"红线例外 + 服务器升配），ADR 先行
- **金标扩量**：50 → 150 条，覆盖更多警区（需先扩数据覆盖）

## Phase N — 最终成品（面试/作品集叙述）

一个**真实在线运营**的 AI 安全情报产品：

- 公开 HTTPS URL，真实 NYPD 数据驱动，$5/日熔断保护下稳定运行
- 335+ 单元测试 + 50 条金标 eval + README 指标（路由准确率 / groundedness / 幻觉率）
- "零服务架构"完整故事：stdlib 前端、文件级监控、成本熔断、诚实降级——每个取舍都有 ADR 或 CLAUDE.md 棘轮表背书
- 用户证据：5 人真人访谈发现清单 + 合成用户预检报告
- 仓库即简历：干净 commit 历史、spec/ADR/票据三件套齐全、ralph 循环自治记录

> 注：Phase 3+ 均为候选，不构成承诺；每步进场前重新 grill。
