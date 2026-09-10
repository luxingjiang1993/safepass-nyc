# 07 — A5 画像本机可感知

**What to build:** 同一地点、不同画像，安全评级相同、建议不全相同。已填画像的覆盖内页有默认折叠的「对比：无画像时的建议」，只并排建议、没有第二盏灯。画像仍不进模型。

**Blocked by:** 01 — C2 四时段桶（灯不变）

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/35

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/42 （原生 blocked by #36）

- [ ] 同区两画像：rating 相等、suggestions 不全等；自动化锁住
- [ ] Skill 输入仍无六维画像；隐私页零上传口径不改为「画像上传」
- [ ] 有画像时折叠默认关闭、无第二盏灯；无画像 / 紧急 / 越界 / 防线无该块
- [ ] 对比用空画像再跑一次唯一接缝，仍零上传
- [ ] `python -m pytest tests/ -q` 全绿（本票不跑、不等 L2 重录）
