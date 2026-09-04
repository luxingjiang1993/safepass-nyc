# 02 — 数据资产 fixture 三件套

**What to build:** 用确定性脚本（禁 LLM）生成并版本化三份测试 fixture，是一切红测试的前提：①模拟 NYPD 数据集——逐条记录含警区、犯罪类型、时间戳（含昼夜可判定字段）、来源标注字段，规模覆盖评级四档与样本量各档（至少一个 <10 条 ⚪ 案例、若干 10–29 / 30–99 / ≥100 档案例、至少一个警区落在 0.7× 与 1.3× 边界附近）；②警区安全场所静态表——5 个核心警区各一份 24 小时安全场所清单（便利店/医院/警局，含地址电话）+ 通用清单（911/311 + 五警局），未核实电话的机构只列机构名；③RAG 知识库文档 15 篇预计算安全报告（含华人特定注意事项、各警区中文服务记载情况），未记载的事实明确写"未记载"。存储形态：版本化 CSV/JSON 或 SQLite 单文件（二选一）；向量库 = FAISS 本地索引文件 + BM25 pickle；embedding 用本地 sentence-transformers 级模型，不依赖 API。安全场所表与知识文档是人工搜集/撰写后录入的内容工作，录入时执行两条护栏：未核实不编、未记载写明"未记载"。动手前先查素材清单与状态登记。

**Track:** Ralph（对应 RALPH.md T0；fixture 自检集机器可验证）

**Blocked by:** 01（pytest 布局与配置加载是三件套自检集的前提）

**Status:** done (2026-09-04, Ralph iteration 1)

- [x] fixture 自检集通过：生成脚本跑两遍输出逐字节一致（确定性）
- [x] 独立复算脚本断言数据集覆盖评级四档 + 各样本量档（含 <10 ⚪ 案例与 0.7×/1.3× 边界案例）
- [x] 静态表与知识文档满足两条护栏（未核实不编、未记载写明"未记载"），已核实来源可追溯
- [x] FAISS 索引与 BM25 索引可从 fixture 离线重建（本地 embedding，无 API 依赖）
- [x] 未安装 MySQL/PostgreSQL/向量数据库等任何需单独部署的组件

**完成证据（iteration 1）**：`pytest tests/ -q` 32 passed（test_skeleton 11 + test_fixtures 21）。新增：`scripts/generate_fixtures.py`（确定性模拟 NYPD 数据集，禁 LLM，阈值/覆盖警区全部读 config；1,280 条记录覆盖 11 个警区：评级四档齐全，P90 比率 0.6983 贴 0.7× 边界、P109 比率 1.2998 贴 1.3× 边界，P84 仅 6 条 ⚪，样本量四档各有案例）；`fixtures/safe_places/precinct_safe_places.json`（5 警区×模板条目+通用清单，警局/医院电话地址经 NYPD 官网与机构官网核实，未核实便利店按护栏只列类别名）；`fixtures/knowledge/*.md` 15 篇（5 警区×3 主题，含仇恨犯罪与中文警员"未记载"标注、来源清单、经验性建议标注）；`scripts/build_index.py`（本地 sentence-transformers paraphrase-multilingual-MiniLM-L12-v2 + FAISS IndexFlatIP + BM25Okapi，CJK 二元组分词，非对称 RRF k_vec=60/k_bm25=10）→ `fixtures/index/`；`config/app.yaml` 回填 city_mean_per_100k=144.6328（与数据集复算一致，有测试锁定）。遗留：D1 字段规范参考文件未下载（仅字段结构参考用途，不阻塞 T1）。
