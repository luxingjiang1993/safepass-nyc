# 03 — N2b 三列对照收口

## 执行方式 / 并行组
- **方式：/implement**（需录制 cassette：网络 + DASHSCOPE_API_KEY + 预算）
- **依赖**：N2a（#28）合并（夹具与打分口径冻结）
- **并行组**：无（等 N2a）；A4 已可并行于 N2a，不阻塞本票
- **文件独占**：对照生成入口、N2 生成 cassette、对照文档；勿改 N2a 已钉 ID/打分口径；勿改 L2 judge cassette；勿改 frontend
- **阻塞**：无
- **GitHub**：#26（原生 blocked by #28）

## 来源
docs/specs/safepass-v3-wave2-n2-a4-spec.md（权威）+ docs/portfolio-100-execution-plan.md §7.1 N2 + 文首 P8

## 目标 / 缺口 / 做法 / DoD / 加分

- **目标**：同一 20 条金标上三列对照，证明约束下的 SafePass 优于裸 LLM 与无约束 RAG。
- **缺口**：验收看板 #17 空。
- **做法**：裸 LLM 无检索；无约束 RAG = 同一混合检索 top-3 知识 chunk 整段入提示（无依据校验、不禁写灯、不塞 charts/倍数、不劣化检索）；SafePass 走唯一接缝；复用 N2a 打分；cassette 与 L2 分文件；世界钉 mock 数据集。
- **DoD**：对照页存在；SafePass 无证据事实声明率严格低于另两列；越界编造率 SafePass=0 且另两列在越界子集各 ≥1 例；评级一致性 SafePass=100%；3 个失败样例；默认 `python -m pytest tests/ -q` 不跑本套件。
- **加分**：直接回答「和会调 API 的人差在哪」。
- **Craft**：T2。

## 波 2 第一刀定案（P8，效力优先）

1. 不改 N2a 已钉死的 ID 名单与打分口径。
2. 对照列不得进入主应用依赖。
3. 禁止 Plan/ReAct/对话助手；禁止重做 N1/N3。

## Craft
- Craft IDs: T2
- **必须打开**：spec 三列定义；禁止为对照引入 LangChain 进主路径
- **观察清单**：同一索引比约束，不是绑起对手再赛
- **借鉴什么 / 别抄什么**：借三列对照叙事；禁止对照列塞统计表、禁止故意劣化检索

## 允许改动
- 对照生成脚本 / eval 回放测试 / N2 生成 cassette / 对照文档
- README 仅可增加对照页链接或一行指标，禁止借机改产品范围

## 禁止
- 将本套件纳入默认 tests/ 基线
- 用 L2 幻觉 judge 给三列打分
- 对照列塞统计表；故意劣化检索
- LangChain / LlamaIndex / 服务型 DB 进主路径
- 重做 N1/N3；实现 Plan/ReAct
- LLM 改评级/越界/可信度

## 验证
- `python -m pytest tests/ -q` 仍全绿（不因本票依赖网络）
- `python -m pytest tests/eval -q`（或本票专用路径）回放全绿
- 对照文档与现场重算数字一致

## 完成承诺
- 对照页含三列数字 + 3 失败样例；SafePass 越界编造率=0、评级一致性=100%、无证据事实声明率严格低于另两列；另两列越界子集各至少 1 例编造；默认基线不跑 N2。
