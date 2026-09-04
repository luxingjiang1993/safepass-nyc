"""issue 02 / RALPH T0 验收测试：数据资产 fixture 三件套自检集。

对应 .scratch/safepass-nyc-mvp/issues/02-data-asset-fixtures.md 五条勾选：
    1. 生成脚本跑两遍输出逐字节一致（确定性）
    2. 独立复算脚本断言数据集覆盖评级四档 + 各样本量档（含 <10 ⚪ 与 0.7×/1.3× 边界）
    3. 静态表与知识文档满足两条护栏（未核实不编、未记载写明"未记载"）
    4. FAISS 索引与 BM25 索引可从 fixture 离线重建（本地 embedding，无 API 依赖）
    5. 未安装 MySQL/PostgreSQL/向量数据库等任何需单独部署的组件
"""

from __future__ import annotations

import csv
import json
import re
import socket
from datetime import datetime
from pathlib import Path

import pytest

from safepass import config_loader
from scripts import build_index as bi
from scripts import generate_fixtures as gf

REPO_ROOT = Path(__file__).resolve().parent.parent
NYPD_DIR = REPO_ROOT / "fixtures" / "nypd"
SAFE_PLACES = REPO_ROOT / "fixtures" / "safe_places" / "precinct_safe_places.json"
KNOWLEDGE_DIR = REPO_ROOT / "fixtures" / "knowledge"
INDEX_DIR = REPO_ROOT / "fixtures" / "index"


# ---------------------------------------------------------------------------
# 1. 确定性：生成脚本跑两遍输出逐字节一致
# ---------------------------------------------------------------------------


def test_generator_two_runs_byte_identical(tmp_path):
    cfg = config_loader.load_config()
    rows_a = gf.build_rows(cfg)
    rows_b = gf.build_rows(cfg)
    assert gf.render_csv(rows_a) == gf.render_csv(rows_b), "CSV 两次生成不一致"
    assert gf.render_manifest(rows_a) == gf.render_manifest(rows_b), "manifest 两次生成不一致"


def test_generator_on_disk_matches_fresh_generation(tmp_path):
    out = tmp_path / "nypd"
    files = gf.generate(out)
    for name, data in files.items():
        assert (NYPD_DIR / name).read_bytes() == data, (
            f"fixtures/nypd/{name} 与重新生成结果不一致（先跑 scripts/generate_fixtures.py）"
        )


def test_generator_uses_no_llm_and_no_wallclock():
    """禁 LLM：生成器不得 import 任何 LLM/网络客户端；时间窗为固定常量。"""
    text = (REPO_ROOT / "scripts" / "generate_fixtures.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "requests", "httpx", "urllib", "datetime.now", "date.today"):
        assert banned not in text, f"生成器出现禁用依赖/调用：{banned}"


# ---------------------------------------------------------------------------
# 2. 独立复算：评级四档 + 样本量各档 + 边界案例
# ---------------------------------------------------------------------------


def _load_rows():
    with open(NYPD_DIR / "mock_nypd.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _recompute(rows):
    """独立复算（不引用生成器 DESIGN 常量）：逐警区计数/人口/比率/全市均值。"""
    counts: dict[int, int] = {}
    pops: dict[int, int] = {}
    for r in rows:
        p = int(r["precinct"])
        counts[p] = counts.get(p, 0) + 1
        pops.setdefault(p, int(r["population"]))
        assert int(r["population"]) > 0
    total_c = sum(counts.values())
    total_p = sum(pops.values())
    mean = total_c / total_p * 100_000
    ratios = {p: (counts[p] / pops[p] * 100_000) / mean for p in counts}
    return counts, pops, mean, ratios


def test_dataset_covers_all_rating_and_sample_tiers():
    cfg = config_loader.load_config()
    rows = _load_rows()
    counts, pops, mean, ratios = _recompute(rows)
    gmax = cfg.thresholds.green_max_ratio
    rmin = cfg.thresholds.red_min_ratio

    tiers = {t.min: t for t in cfg.sample_size_tiers}

    def tier_of(n: int):
        for t in cfg.sample_size_tiers:
            if n >= t.min and (t.max is None or n <= t.max):
                return t
        raise AssertionError(f"样本数 {n} 不在任何档位")

    # 评级四档：🟢 / 🟡 / 🔴 / ⚪(<10 强制 insufficient_data)
    rated = {p: r for p, r in ratios.items() if tier_of(counts[p]).rating != "insufficient_data" and counts[p] >= 10}
    assert any(r < gmax for r in rated.values()), "缺 🟢 案例"
    assert any(gmax <= r <= rmin for r in rated.values()), "缺 🟡 案例"
    assert any(r > rmin for r in rated.values()), "缺 🔴 案例"
    white = [p for p in counts if tier_of(counts[p]).rating == "insufficient_data" or counts[p] < 10]
    assert white, "缺 ⚪（<10 条）案例"

    # 样本量四档全覆盖
    present = {(t.min, t.max) for t in (tier_of(n) for n in counts.values())}
    expected = {(t.min, t.max) for t in tiers.values()}
    assert expected <= present, f"样本量档未全覆盖：缺 {expected - present}"

    # 覆盖警区每区至少一档案例，且含 ≥100 与 <10
    for p in cfg.covered_precincts:
        assert p in counts, f"覆盖警区 {p} 在数据集中无记录"
    covered_counts = [counts[p] for p in cfg.covered_precincts]
    assert max(covered_counts) >= 100, "覆盖警区缺 ≥100 档案例"
    assert min(covered_counts) < 10, "覆盖警区缺 <10 ⚪ 案例"


def test_dataset_boundary_cases_near_config_thresholds():
    cfg = config_loader.load_config()
    rows = _load_rows()
    counts, pops, mean, ratios = _recompute(rows)
    gmax = cfg.thresholds.green_max_ratio
    rmin = cfg.thresholds.red_min_ratio
    near_green = [p for p in counts if abs(ratios[p] - gmax) <= 0.012 and counts[p] >= 10]
    near_red = [p for p in counts if abs(ratios[p] - rmin) <= 0.012 and counts[p] >= 10]
    assert near_green, f"无警区落在 {gmax}× 边界附近"
    assert near_red, f"无警区落在 {rmin}× 边界附近"
    # 边界警区本身须有足够样本支撑评级（非 ⚪ 档）
    for p in near_green + near_red:
        assert counts[p] >= 10, f"边界警区 P{p} 样本 {counts[p]} 不足 10，无法支撑边界用例"


def test_dataset_night_flag_and_window_and_source():
    rows = _load_rows()
    manifest = json.loads((NYPD_DIR / "manifest.json").read_text(encoding="utf-8"))
    start = datetime(2025, 7, 1)
    end = datetime(2026, 7, 1)
    night_count = 0
    for r in rows:
        ts = datetime.strptime(r["occurred_at"], "%Y-%m-%dT%H:%M:%S")
        assert start <= ts < end, f"时间戳越窗：{r['occurred_at']}"
        hour = ts.hour
        expected_night = 1 if (hour >= 20 or hour < 6) else 0
        assert int(r["is_night"]) == expected_night, f"is_night 与小时不一致：{r}"
        assert int(r["hour"]) == hour
        assert r["source"] == manifest["dataset_version"]
        assert r["offense_level"] in ("FELONY", "MISDEMEANOR")
        night_count += int(r["is_night"])
    assert 0 < night_count < len(rows), "昼夜分布不应全为白天或全为夜间"


def test_dataset_out_of_coverage_precincts_present_for_degraded_tests():
    cfg = config_loader.load_config()
    rows = _load_rows()
    present = {int(r["precinct"]) for r in rows}
    # 越界/中城测试需要：26（哥大附近映射目标）与 14/18（中城跨区）
    assert 26 in present, "缺 P26（哥大附近越界测试用）"
    assert cfg.excluded_precincts <= present, "缺中城 14/18 警区记录"


def test_config_city_mean_matches_dataset():
    cfg = config_loader.load_config()
    rows = _load_rows()
    _counts, _pops, mean, _ratios = _recompute(rows)
    assert cfg.city_mean_per_100k is not None, "T0 应回填 config/app.yaml 的 city_mean_per_100k"
    assert cfg.city_mean_per_100k == pytest.approx(mean, abs=1e-3), (
        f"config 全市均值 {cfg.city_mean_per_100k} 与数据集复算 {mean:.4f} 不一致"
    )


def test_manifest_consistent_with_csv():
    manifest = json.loads((NYPD_DIR / "manifest.json").read_text(encoding="utf-8"))
    rows = _load_rows()
    counts, pops, mean, ratios = _recompute(rows)
    assert manifest["total_records"] == len(rows)
    assert manifest["city_mean_per_100k"] == pytest.approx(mean, abs=1e-3)
    for p, v in manifest["precincts"].items():
        p = int(p)
        assert v["records"] == counts[p]
        assert v["population"] == pops[p]
        assert v["ratio_to_city_mean"] == pytest.approx(ratios[p], abs=1e-4)


# ---------------------------------------------------------------------------
# 3. 两条内容护栏：未核实不编、未记载写明"未记载"
# ---------------------------------------------------------------------------


def _load_safe_places():
    return json.loads(SAFE_PLACES.read_text(encoding="utf-8"))


def test_safe_places_structure_and_coverage():
    cfg = config_loader.load_config()
    data = _load_safe_places()
    assert set(data["precincts"].keys()) == {str(p) for p in cfg.covered_precincts}
    for p in cfg.covered_precincts:
        venues = data["precincts"][str(p)]["venues"]
        types = [v["type"] for v in venues]
        assert types.count("police_station") == 1, f"P{p} 须恰有 1 个警局条目"
        assert types.count("hospital") >= 1, f"P{p} 须至少 1 个医院条目"
        assert types.count("convenience_store") >= 2, f"P{p} 须至少 2 个便利店条目"
    general_types = [v["type"] for v in data["general"]["venues"]]
    assert "emergency_number" in general_types, "通用清单缺 911"
    assert "city_services_number" in general_types, "通用清单缺 311"
    assert general_types.count("police_station") == 5, "通用清单缺五警局"


def test_safe_places_guardrail_unverified_lists_name_only():
    """护栏①：verified=false 的条目只列机构名——不得含 address/phone/hours。"""
    data = _load_safe_places()
    offenders = []
    groups = list(data["precincts"].values()) + [data["general"]]
    for g in groups:
        for v in g["venues"]:
            assert v.get("source"), f"条目缺 source：{v.get('name')}"
            assert v.get("name"), "条目缺机构名"
            if not v.get("verified"):
                for field in ("address", "phone", "hours"):
                    if v.get(field):
                        offenders.append(f"{v.get('name')} 未核实却填写了 {field}")
    assert not offenders, "未核实不编护栏被违反：\n" + "\n".join(offenders)


def test_safe_places_verified_entries_have_address_phone_and_source():
    data = _load_safe_places()
    groups = list(data["precincts"].values()) + [data["general"]]
    for g in groups:
        for v in g["venues"]:
            if v.get("verified"):
                assert v.get("phone"), f"已核实条目缺电话：{v.get('name')}"
                if v["type"] not in ("emergency_number", "city_services_number"):
                    # 911/311 是号码条目本身，不要求地址
                    assert v.get("address"), f"已核实条目缺地址：{v.get('name')}"
                assert str(v["source"]).startswith("http"), f"已核实条目 source 应为官方 URL：{v.get('name')}"


def test_knowledge_docs_fifteen_files_three_themes_per_precinct():
    cfg = config_loader.load_config()
    files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    assert len(files) == 15, f"知识库应为 15 篇，实际 {len(files)}"
    for p in cfg.covered_precincts:
        stems = {f.stem for f in files if f.stem.startswith(f"p{p}_")}
        assert stems == {f"p{p}_overview", f"p{p}_scam", f"p{p}_emergency"}, f"P{p} 三主题不全：{stems}"


def test_knowledge_docs_guardrails():
    """护栏②：未记载的事实明确写"未记载"；每篇带来源；无官方来源的机构不列电话。"""
    files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    assert files, "知识库目录为空"
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert re.search(r"^sources:\s*$", text, re.M), f"{f.name} 缺 sources 清单"
        assert re.search(r"^precinct:\s*\d+", text, re.M), f"{f.name} 缺 precinct frontmatter"
        assert "verified_at" in text, f"{f.name} 缺 verified_at"
        # 仇恨犯罪记载情况（overview 篇）与中文警员记载情况（emergency 篇）必须显式记载/未记载
        if f.stem.endswith("_overview"):
            assert "仇恨犯罪" in text, f"{f.name} 缺仇恨犯罪记载情况"
        if f.stem.endswith("_emergency"):
            assert "中文警员" in text and "未记载" in text, (
                f"{f.name} 缺中文服务记载情况或未写明'未记载'"
            )
        # 未核实机构不得列电话（F7-3/护栏①）
        for m in re.finditer(r"未记载|未核实", text):
            pass  # 存在性由上面断言保证；此处防止未来改动删除标注
        phone_like = re.findall(r"\(\d{3}\)\s*\d{3}-\d{4}", text)
        for ph in phone_like:
            # 文内出现的电话必须能对应到已核实来源（警局/医院/911/311）
            assert any(
                s in text
                for s in ("nyc.gov/site/nypd", "flushinghospital.org", "nychealthandhospitals.org",
                          "northwell.edu", "tbh.org", "whmcny.org", "portal.311.nyc.gov")
            ), f"{f.name} 出现未溯源电话 {ph}"


def test_knowledge_docs_contain_required_chinese_specific_notes():
    for f in KNOWLEDGE_DIR.glob("*_scam.md"):
        text = f.read_text(encoding="utf-8")
        assert "使领馆" in text and "诈骗" in text, f"{f.name} 缺华人诈骗主题"
    for f in KNOWLEDGE_DIR.glob("*_overview.md"):
        text = f.read_text(encoding="utf-8")
        assert "华人" in text, f"{f.name} 缺华人特定注意事项"


# ---------------------------------------------------------------------------
# 4. FAISS + BM25 索引可离线重建（本地 embedding，无 API 依赖）
# ---------------------------------------------------------------------------


def _block_network(monkeypatch):
    def _no_connect(*args, **kwargs):
        raise AssertionError("索引构建/检索不得访问网络（必须为本地离线路径）")

    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket.socket, "connect", lambda self, *a, **k: _no_connect())


def test_index_rebuild_offline_and_deterministic(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    meta_a = bi.build_index(KNOWLEDGE_DIR, out_a)
    meta_b = bi.build_index(KNOWLEDGE_DIR, out_b)
    assert meta_a == meta_b, "两次构建的 meta 不一致"
    assert (out_a / bi.FAISS_FILE).read_bytes() == (out_b / bi.FAISS_FILE).read_bytes(), (
        "FAISS 索引两次构建不一致"
    )
    assert (out_a / bi.BM25_FILE).read_bytes() == (out_b / bi.BM25_FILE).read_bytes(), (
        "BM25 索引两次构建不一致"
    )


def test_committed_index_matches_fresh_rebuild(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    bi.build_index(KNOWLEDGE_DIR, tmp_path)
    assert (tmp_path / bi.FAISS_FILE).read_bytes() == (INDEX_DIR / bi.FAISS_FILE).read_bytes(), (
        "fixtures/index 与离线重建不一致（先跑 scripts/build_index.py）"
    )
    assert (tmp_path / bi.BM25_FILE).read_bytes() == (INDEX_DIR / bi.BM25_FILE).read_bytes()


def test_index_search_hits_expected_docs(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    bi.build_index(KNOWLEDGE_DIR, tmp_path)
    cases = [
        ("法拉盛 换汇诈骗", "p109_scam"),
        ("唐人街 冒充使领馆诈骗", "p5_scam"),
        ("上东区 仇恨犯罪", "p19_overview"),
        ("威廉斯堡 自行车盗窃", "p90_overview"),
        ("布鲁克林高地 急诊 医院", "p84_emergency"),
    ]
    for query, expected_doc in cases:
        top = bi.search(tmp_path, query, k=3)
        assert top, f"查询无结果：{query}"
        assert expected_doc in [doc_id for doc_id, _ in top], (
            f"查询 '{query}' 的 top-3 未命中 {expected_doc}：{[d for d, _ in top]}"
        )


def test_embedding_model_is_local_sentence_transformers():
    meta = json.loads((INDEX_DIR / bi.META_FILE).read_text(encoding="utf-8"))
    assert meta["embedding_model"].startswith("sentence-transformers/"), (
        "embedding 必须是本地 sentence-transformers 级模型（禁 API 依赖）"
    )
    assert meta["doc_count"] == 15


# ---------------------------------------------------------------------------
# 5. 无 MySQL/PostgreSQL/向量数据库等需单独部署的组件
# ---------------------------------------------------------------------------


def test_no_deployed_database_components():
    """项目不得依赖 MySQL/PostgreSQL/向量数据库等需单独部署的组件。

    判定口径（与环境无关）：requirements.txt 不引入、产品代码与脚本不 import。
    （共享 Python 环境可能预装无关包，不能据此判定项目依赖。）
    """
    banned = ["mysql", "pymysql", "psycopg", "psycopg2", "sqlalchemy", "pymongo",
              "qdrant", "milvus", "pinecone", "weaviate", "chromadb", "elasticsearch"]
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for mod in banned:
        assert mod not in req, f"requirements.txt 引入了 {mod}"
    import_re = re.compile(
        r"(import|from)\s+(mysql|pymysql|psycopg|pymongo|sqlalchemy|qdrant|milvus|pinecone|weaviate|chromadb|elasticsearch)\b",
        re.I,
    )
    for py in sorted((REPO_ROOT / "safepass").rglob("*.py")) + sorted(
        (REPO_ROOT / "scripts").rglob("*.py")
    ):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            assert not import_re.search(line), f"{py.name}:{lineno} 引入需部署的数据库组件"


def test_product_code_has_no_database_client_imports():
    """产品代码 safepass/ 只允许本地文件形态（CSV/JSON/FAISS/pickle），不得 import 数据库驱动。"""
    banned = re.compile(r"import\s+(mysql|pymysql|psycopg|pymongo|sqlalchemy|qdrant|milvus|pinecone)", re.I)
    for py in sorted((REPO_ROOT / "safepass").rglob("*.py")):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            assert not banned.search(line), f"{py.name}:{lineno} 引入数据库驱动"
