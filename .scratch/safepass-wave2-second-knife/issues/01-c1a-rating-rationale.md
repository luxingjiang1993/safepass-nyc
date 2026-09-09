# 01 — C1a 评级依据人话（契约 + 首屏替换）

**What to build:** 覆盖内查询结果带上一句确定性「评级依据」：相对全市倍数、样本档、以及 ⚪ 为何不评级。首屏核心结论行之下只留这一行，换掉旧的硬编码倍数散文。越界页和紧急页不出现这句。灯不是模型写的。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/29

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/30

- [ ] 覆盖内安全查询结果必有非空 `rating_rationale`；绿 / 黄 / 红 / ⚪ 四档人话可区分
- [ ] 模板按灯色放在配置里；⚪ 不含倍数；倍数与核心结论行全市钩子同一位小数
- [ ] 结果页有且仅有一行「评级依据」+ 该字段；旧倍数硬编码句消失
- [ ] 越界页 / 紧急页 / 对比 / 防线契约不加该字段、不渲染该槽
- [ ] LLM 不写该字段；`python -m pytest tests/ -q` 全绿（本票不跑、不等 L2 重录）
