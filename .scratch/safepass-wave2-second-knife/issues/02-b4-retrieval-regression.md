# 02 — B4 混合检索 top-3 回归

**What to build:** 约 20 条「查询 → 应命中文档标识」钉死在 mock 世界上，混合检索 top-3 必须命中；仓库里有一张 BM25-only 与混合检索的对照表。改标注或改坏索引能让测试变红。不经建议 Skill、不测 HTML。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Parent

https://github.com/luxingjiang1993/safepass-nyc/issues/29

## GitHub

https://github.com/luxingjiang1993/safepass-nyc/issues/31

- [ ] 约 20 条标注，优先复用已有金标与知识锚点；覆盖五核心警区及诈骗 / 夜间等主题差
- [ ] 应命中文档标识均存在于当前知识 / 索引元数据；改名单即红
- [ ] 混合检索 top-3 含应命中文档；community_info 不参与排序
- [ ] BM25-only vs 混合检索对照表进仓库；测试断言表存在且含可核对结论（不必每次重算 embedding）
- [ ] 进默认行为基线；`python -m pytest tests/ -q` 全绿；零 LLM
