# Phase 2 Skill 清单与流程

> 本文档列出 Phase 2（spec v2 → 上线）全程要用的 skill、各自的角色和调用流程。
> 规矩：主任务会话一条线走到底；侧边问题去新会话；跨会话交接用 `/handoff`。

## 主流程链（按调用顺序）

```
/grill-with-docs  →  /to-spec  →  /to-tickets  →  /implement(+ /tdd, /code-review)  →  /ralph(机械票)
```

### 1. `/grill-with-docs` — 拷问定需求【已完成】

- **什么时候**：任何"要做什么还不完全清楚"的阶段开头
- **干什么**：一次一问把决策全部拍板，resolve 的术语落 `CONTEXT.md`，架构级决策落 `docs/adr/`
- **产出**：本系列决策（eval 两层判定、覆盖矩阵、四里程碑等），即 spec 的输入

### 2. `/to-spec` — 会话变规格

- **什么时候**：grilling 收官后（现在）
- **干什么**：把拍板决策写成 `docs/specs/safepass-v2-spec.md`；**每个改写自参考代码的组件必须标注来源路径**（`可用来参考的代码案例/...`）
- **注意**：MVP spec v1.2 是历史档案，正文不动

### 3. `/to-tickets` — 规格变票据

- **干什么**：spec 拆成 tracer-bullet 票据，每张声明 blocking edges；写到 GitHub Issues（`gh` CLI，见 `docs/agents/issue-tracker.md`）
- **产出**：M1–M4 全部票据，**每张标注执行方式：`/implement`（默认）或 `/ralph`（仅限机械性、有布尔验证命令的票）**

### 4. `/implement` + `/tdd` — 逐票实现【主力】

- **什么时候**：每张票据开工时；**每票清一次上下文**（新会话或 `/clear`），只吃票据文本
- **流程**：`/tdd` 红绿切片构建 → 唯一判定 `pytest tests/ -q` → `/code-review` 双轴审查（Standards + Spec）→ commit（push 用户自己来）

### 5. `/ralph` — 机械票批量【辅助】

- **什么时候**：票据池里**有明确机器可验证完成条件**的机械票（如"补 cassette""批量改名""跑 adapter 入库"）
- **前置**：任务登记 `RALPH.md` + 布尔完成承诺；`./ralph-once.sh` 先试一轮，满意再 `./afk-ralph.sh`
- **红线**：探索性/架构性任务禁止进 Ralph；见 `CLAUDE.md`「Ralph 特化」

## 支撑 skill（穿插使用）

| Skill | 用途 |
|-------|------|
| `/domain-modeling` | 拷问/实现中新术语 resolve 时更新 `CONTEXT.md`；三条件触发时落 ADR |
| `/handoff` | 会话逼近上下文上限或换会话时生成交接文档（存系统 Temp） |
| `/triage` | 真人访谈发现清单 issue 化后，走五标签分诊（`needs-triage` → `ready-for-agent` 等） |
| `/code-review` | 每票收尾 + 每个里程碑结束时的双轴审查 |

## 明确不用的

- **ralph-loop 插件**（`/ralph-loop`）：已弃用，用 Pocock 版 bash 循环（上面的 `/ralph` skill）
- **LangChain/LangSmith/Langfuse SDK 进运行时**：监控走文件级方案；开发期 Langfuse 可选且默认关（见 spec）
- **MCP**：Phase 2 无 agent 自由调工具的需求，地理编码将来直连 REST 不走 MCP
