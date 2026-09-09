# 05 — D5+C6 首页价值主张与覆盖边界

**What to build:** 首页 Hero 改成「中文安全情报；数据评级，AI 只建议」，保留查询框和五个核心警区入口，并写清只覆盖这五区、越界不编灯。结果页标明本次命中警区与覆盖清单同源。越界页展示「若在覆盖内你会看到什么结构」，不给该地点四级安全评级。紧急页不加这些槽。

**Blocked by:** 01 — C1a 评级依据人话（契约 + 首屏替换）（结果页与 C1a 同槽冲突）

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/29

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/34 （原生 blocked by #30）

- [ ] Hero 主句与有 Skill 的现实一致；五区名称来自配置别名，代码不写死警区号
- [ ] 首页覆盖诚实：只五区；越界诚实降级
- [ ] 覆盖内结果页：覆盖清单 + 本次命中警区，与配置同源
- [ ] 越界页结构示意不含该地点安全评级或犯罪率；越界「通用建议」旧语义不改成 ⚪
- [ ] 紧急页无芯片、无评级依据、无覆盖结构示意；`python -m pytest tests/ -q` 全绿
