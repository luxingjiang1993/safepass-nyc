# 06 — F1 免责与契约同源

**What to build:** 免责页上的时间范围和数据来源与当次查询结果里的来源、时间范围同一事实源。改配置两边一起变，否则测试红。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/41

- [ ] 时间范围 / 来源单一事实源在配置
- [ ] 覆盖内结果契约字段与免责文案一致
- [ ] 漂移测试：改配置则两边同时变，只改一处即红
- [ ] 不把免责改成 LLM 生成
- [ ] `python -m pytest tests/ -q` 全绿
