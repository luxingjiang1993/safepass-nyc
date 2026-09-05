# 04 — 三项指标基线进 README

**What to build:** 从 eval 套件产出三项指标——路由准确率（L1）/ groundedness（L2）/ 幻觉率（L2）——写入 README 作为质量基线，M1 出口标准达成。

**Blocked by:** 02 — L1 断言进 pytest 基线；03 — L2 judge 套件

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M1 eval 套件（spec v2）

- [x] 三项指标有数字、可复算（跑套件即得），写入 README
- [x] 指标口径一句话说清（分子分母）
- [ ] 尾巴（人工验收，不阻塞本票）：DeepSeek 生产模型兼容性验证需真实 DeepSeek key + 网络，结果登记 README
