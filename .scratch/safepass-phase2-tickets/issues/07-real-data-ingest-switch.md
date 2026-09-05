# 07 — 真实数据入库 + 数据路径切换（Ralph 票）

**What to build:** 跑 adapter 拉真实 NYPD 数据入库；`city_mean_per_100k` 按真实数据重算并回填 config（评级可复现性约束）；生产数据路径从 mock 切到真实数据目录，mock fixture 保留为测试资产。M2 出口：真实 fixture 入库、老测试不破。

**Blocked by:** 05 — 真实数据 adapter

**Status:** ready-for-agent　**执行方式:** /ralph（机械票：入库运行 + 重算 + 切换 + 布尔承诺）　**里程碑:** M2 数据 + 成本（spec v2）

**Ralph 完成承诺:** `pytest tests/ -q` 全绿且无新 skip；真实数据已入 `fixtures/nypd_real/`；`city_mean_per_100k` 已按真实数据重算回填。

**前置条件:** Socrata 网络可达（需 VPN）。

- [x] 真实数据入库完成，manifest 来源标注齐
- [x] city_mean 重算回填，评级可复算集跨机器复跑仍绿
- [x] prod 数据路径切换（config 数据目录）
- [x] 唯一判定：`pytest tests/ -q` 全绿
