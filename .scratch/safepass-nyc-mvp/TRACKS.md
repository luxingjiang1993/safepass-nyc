# SafePass NYC MVP — Ticket 轨道标注

> 判定依据：`docs/specs/safepass-nyc-mvp-spec.md` v1.2 "Ralph 适用性评估"表。
> 规则：验收标准全部机器可验证 → **Ralph**；含主观判断项（UI、UX、文案品味、在线 LLM 准确率）→ **标准 Implement**（循环外）。
> 每条 ticket 文件的 `**Track:**` 行与本表一致。

| # | Ticket | Track | 备注 |
|---|--------|-------|------|
| 01 | 工程骨架与接缝空壳 | **Ralph** | prefactor；机器可验证（pytest 可跑、grep 审查、接缝空壳存在） |
| 02 | 数据资产 fixture 三件套 | **Ralph** | = RALPH.md T0 |
| 03 | 数据 Agent 聚合 | **Ralph** | = T1 |
| 04 | 评级引擎 + 可信度映射 | **Ralph** | = T2；纯函数零 LLM，信任基石 |
| 05 | 降级分支 + D12 确定性后置 | **Ralph** | = T3；诚实原则基石 |
| 06 | FC 路由 + 输出控制管线 | **Ralph**（结构） | = T4；建议文案具体性/温暖度 ⚠️ 转标准 Implement + 人工抽查 |
| 07 | 紧急检测两层 + 静态紧急组装 | **Ralph** | = T5；改写句层 cassette 回放，真实兜底召回率转人工在线验证 |
| 08 | 追问上下文承接 | **Ralph** | = T6 |
| 09 | 中文地址识别 + NEG 负例防线 | **Ralph** | = T7；画像措辞 ⚠️ 转人工抽验 |
| 10 | 情报 Agent 混合检索 + RAG | **Ralph** | = T8 |
| 11 | 前端：首页 + 查询结果渲染 | **标准 Implement** | ❌ 禁止 Ralph（UI/UX 主观项） |
| 12 | 前端：紧急模式页 + 画像侧边栏 | **标准 Implement** | ❌ 禁止 Ralph（UI） |

**执行顺序建议**：
1. Ralph 循环推进 01–10（协议见 RALPH.md；停止条件 = 任务全勾选 + 10 个 pytest 集全绿 + 零硬编码审查）。
2. 循环外并行/后续用标准 Implement 做 11–12（需 06–08 的契约就绪）。
3. 最后统一走人工验收清单（spec "质量门复查"表：UX 访谈、窄屏、无障碍、话术品味、关键词库扩充、LLM 层在线验证、KPI 指标）。
