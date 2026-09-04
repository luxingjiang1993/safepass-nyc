# 15 — Hetzner 上线 + UptimeRobot + 真实运营五条验收

**What to build:** 部署到 Hetzner 并验收 M4 出口——「真实运营五条」逐条兑现：①公开 HTTPS URL 可访问；②生产路径由真实 NYPD 数据驱动；③$5/日熔断在线、超限降级明示；④UptimeRobot 监控在线 + 运行/成本日志可查证；⑤隐私页/免责页公开可访问。

**Blocked by:** 14 — Caddy HTTPS + 域名；07 — 真实数据入库 + 路径切换；08 — 隐私页 + 免责页

**Status:** ready-for-human　**执行方式:** 人工（agent 可辅助核验脚本）　**里程碑:** M4 部署（spec v2）

- [ ] 公开 URL 外部可访问（HTTPS）
- [ ] UptimeRobot 探活在线
- [ ] 五条逐条核验并登记（结果写入 README 或 milestone 记录）
