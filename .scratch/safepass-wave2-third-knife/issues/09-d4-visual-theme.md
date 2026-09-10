# 09 — D4 视觉网格、浅深主题与十槽插画

**What to build:** 结果页换成冷静简报网格，浅/深色跟系统也可页内切换并写入主题 cookie。紧急页独立高对比。十个状态各有自制单色 SVG。首屏五槽顺序不变。

**Blocked by:** 07 — A5 画像本机可感知；08 — E4 熔断演示态

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/44 （原生 blocked by #42、#43）

- [ ] 新网格与字号阶梯；无新前端栈、无位图包、无 emoji
- [ ] 系统偏好 + 页内开关 + 主题 cookie；紧急页不跟深色走
- [ ] 十槽 SVG：首页、覆盖内页眉、越界、紧急、空态、熔断、防线、对比、隐私/法律、无法解析；不按灯配犯罪图
- [ ] 隐私页写明主题 cookie（不是画像）
- [ ] D1 槽序结构锁仍绿；`python -m pytest tests/ -q` 全绿
