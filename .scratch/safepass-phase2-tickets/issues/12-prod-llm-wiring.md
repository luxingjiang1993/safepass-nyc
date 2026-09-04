# 12 — 生产模型接线（DeepSeek）

**What to build:** 生产环境经 env（`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`）注入 DeepSeek `deepseek-chat` 客户端（OpenAI 兼容端点），客户端被 06 的成本熔断器包装；前端 app 的 `llm_client=None` 默认值不变（确定性路径离线可跑），生产容器内经 env 接线。

**Blocked by:** 06 — 成本三件套

**Status:** ready-for-agent　**执行方式:** /implement　**里程碑:** M4 部署（spec v2）

- [ ] env 注入路径有测试（fake key 注入验证接线，不烧真钱）
- [ ] 注入客户端必经熔断器（单注入点，不可绕过）
- [ ] dev/test 行为不变：fake/cassette 离线全绿
