# 01 — C2 四时段桶（灯不变）

**What to build:** 查询带可解析钟点时，案件计数切到清晨 / 日间 / 晚间 / 深夜四档。该桶样本不够就诚实说未知。不问钟点时仍用昼夜合计。安全评级不随钟点改档。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/36

- [ ] 四桶边界只在配置里；无钟点 = 昼夜合计；有钟点 = 对应该桶
- [ ] 该桶低于配置样本门槛 → unknowns，不编造
- [ ] 同一地点改钟点不改变安全评级
- [ ] 时段可进建议的数据定调，不进用户画像、不进模型请求的画像字段
- [ ] `python -m pytest tests/ -q` 全绿（本票不跑、不等 L2 重录）
