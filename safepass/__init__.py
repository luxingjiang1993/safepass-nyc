"""SafePass NYC 后端包。

唯一对外接缝：`pipeline.execute_query(查询文本, 会话画像, 会话状态) → 结构化响应契约`（spec D1）。
前端是纯渲染层，消费 contracts 中声明的响应契约，不承载业务逻辑。

模块边界（spec D2）：
    contracts         结构化响应契约（判别联合，四种响应形态）
    config_loader     集中配置加载（唯一读 config/app.yaml 的入口）
    session_state     会话级画像 + 上轮结构化结果；零持久化、零上传
    emergency         紧急检测第一层（关键词静态表，无 LLM）+ 静态紧急组装
    routing           FC 路由层（五个声明工具）
    data_agent        按警区聚合模拟 NYPD 数据集
    rating_engine     纯函数评级 + 可信度映射（零 LLM、零画像）
    intel_agent       混合检索（FAISS + BM25，RRF top-3）
    skills            建议生成等 Skill（提示词模板 + Pydantic 契约 + 业务校验）
    synthetic_user    合成用户预检（票 10，dev-only，产出带"开发参考"标注）
    output_pipeline   输出控制管线（生成→解析/修复→校验→有限重试）
    pipeline          管线编排与唯一接缝
"""
