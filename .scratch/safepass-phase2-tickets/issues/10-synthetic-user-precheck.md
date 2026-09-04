# 10 — 合成用户预检脚本

**What to build:** LLM 扮演用户 persona 的预检脚本（dev-only）：用于真人访谈前低成本戳访谈脚本、扩充金标输入。走输出控制管线模式（生成→解析→校验→有限重试）。产出必须标注"开发参考"，永不冒充真人证据。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M3 信任 + 用户（spec v2）

- [ ] 合成用户脚本可运行，persona 提示词 + 输出 schema 齐备
- [ ] 产出带"开发参考"标注
- [ ] 测试走 fake/cassette，离线可跑
- [ ] 人工前置：运行需 DashScope key（dev）
