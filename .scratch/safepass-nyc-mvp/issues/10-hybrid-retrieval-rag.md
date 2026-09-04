# 10 — 情报 Agent 混合检索 + RAG 知识库

**What to build:** 情报 Agent 在 15 篇预计算安全报告（含华人特定注意事项）上做混合检索：FAISS 向量检索（语义，本地 embedding 模型）+ BM25 关键词检索（专名/犯罪术语兜底），RRF 融合取 top-3（不引入重排层）。检索结果产出 `community_info`：反亚裔仇恨犯罪记录（如有）、华人常见诈骗提醒、中文警员与中文服务记载、社区组织/法律援助/移民服务资源（只列有官方来源的）；知识库未记载的事实（如某警区中文警员）输出"未核实到"，绝不编造。

**Track:** Ralph（对应 RALPH.md T8）

**Blocked by:** 02（需要 15 篇知识文档与 FAISS/BM25 索引 fixture）

**Status:** done（2026-09-04，T8；260 tests green 全绿含 perf）

- [x] `检索集` 全绿：专名查询（精确地名/犯罪术语）+ 语义查询共 ≥10 条，对应报告全部出现在 top-3
- [x] `community_info` 字段断言：未记载的中文警员项输出"未核实到"
- [x] 无官方来源的机构不出现在社区资源列表
- [x] 向量侧用本地 embedding 模型，测试离线可跑、零 API 依赖
- [x] 混合检索遵循 CONTEXT.md 词汇（混合检索，不用"双路检索"）

**完成证据（2026-09-04）**：`tests/test_intel.py`（39 用例）——检索集 14 条
（5 专名 + 9 语义，全部断言 RRF top-3 命中，socket 封锁下离线跑）；community_info
五警区参数化字段断言（未记载中文警员/仇恨犯罪 → `intel.unverified_label`，F7-3）；
资源解析级防线（无 URL 机构条目一律跳过）+ 落盘数据全 http 来源断言；
接缝集成用例复用 `fc_routing_seam.json`（2 交互）断言
`SafetyQueryResult.community_info`；词汇扫描（safepass/+scripts/ 禁"双路检索/混合搜索"）。
实现：`safepass/intel_agent.py` = 混合检索接口 `search()`（FAISS+BM25 经共享纯函数
`scripts.build_index.rrf_fuse`，K_VEC=60/K_BM25=10 单一事实源；索引与本地 embedding
模型 lru_cache，稳态查询 ~30ms）+ 警区锚定 `build_community_info()`（三主题知识文档
确定性解析，零 LLM：overview→仇恨犯罪、scam→诈骗提醒标题、emergency→中文警员/
法律援助资源，格式漂移抛 IntelFormatError）。管线 `_build_safety_result` 填
`community_info`（perf 路径只读索引三件套，不加载模型，P95 无回归）。
统一标注措辞单一事实源 = config `intel.unverified_label`。

**顺手修复（issue 02 遗留，未被认领）**：`scripts/build_index.py` pickle 固定
protocol=5——本机默认协议 4 导致 `test_committed_index_matches_fresh_rebuild`
逐字节比对必挂的环境性失败根治（重建与落盘字节一致，无需重落盘索引）。
