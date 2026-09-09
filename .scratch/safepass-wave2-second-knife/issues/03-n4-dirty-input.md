# 03 — N4 脏输入参数化

**What to build:** 对唯一接缝打一批畸形查询（空、超长、中英混、复读、控制字符；夹具可含表情符号）。每次输出只能是紧急、防线拒绝或诚实降级之一，或者仍是结构完整的覆盖内安全结果；禁止半残契约。若仍走安全路径，安全评级只由确定性引擎写出。不加 hypothesis。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/29

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/32

- [ ] pytest 参数化覆盖约定输入类；产品文案不因此改成表情符号
- [ ] 非法输入 ∈ 紧急 / 防线拒绝 / 诚实降级；无缺字段的覆盖内安全契约
- [ ] 安全路径上 rating 仍只来自引擎
- [ ] 不替代 N1 语义攻击表；不加新模糊测试框架依赖
- [ ] `python -m pytest tests/ -q` 全绿
