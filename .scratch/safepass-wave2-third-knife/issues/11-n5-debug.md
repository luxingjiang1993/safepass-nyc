# 11 — N5 仅 debug=1 的工程师块

**What to build:** 只有查询参数 debug=1 时，覆盖内页才显示路由意图、检索文档标识、是否熔断、Skill 重试、时段桶名。普通页零泄露。不做用户透明条。

**Blocked by:** 10 — D3 空态 / 加载 / 部分失败

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/46 （原生 blocked by #45）

- [ ] 无 debug：HTML 不含检索文档标识、retry 等工程师字段
- [ ] 有 debug：含约定字段；无 API key、无画像六维
- [ ] 调试信息不进入安全查询结果序列化（L2 吃不到）
- [ ] 紧急页仅形态名或隐藏；本票不做 D6
- [ ] `python -m pytest tests/ -q` 全绿
