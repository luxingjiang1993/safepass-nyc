"""T0 fixture 生成器：模拟 NYPD 数据集（spec D11 / RALPH T0）。

红线约束：
- 禁 LLM：全部记录由固定种子 PRNG 生成，同脚本同参数 → 逐字节一致输出。
- 阈值系数 / 样本量档位 / 覆盖警区一律从 config/app.yaml 读取（config_loader），
  本脚本不散落 0.7/1.3 等字面量。

覆盖义务（自检集独立复算验证）：
- 评级四档：🟢 / 🟡 / 🔴 / ⚪(<10 强制 insufficient_data)
- 样本量四档：<10、10–29、30–99、≥100 各有案例
- 边界：至少一个警区落在 green_max_ratio 附近、一个落在 red_min_ratio 附近

用法：
    python scripts/generate_fixtures.py            # 写入 fixtures/nypd/
    python scripts/generate_fixtures.py --check    # 重跑并比对已落盘文件（确定性自检）
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from safepass import config_loader  # noqa: E402

DATASET_VERSION = "MOCK_NYPD_V1"
SEED = 20260904
WINDOW_START = datetime(2025, 7, 1, 0, 0, 0)
WINDOW_END = datetime(2026, 7, 1, 0, 0, 0)  # 不含
WINDOW_DAYS = (WINDOW_END - WINDOW_START).days

# 设计常量：每警区人口（mock 元数据，逐条记录带人口字段供 T1 聚合 per-100k）与
# 目标相对全市均值比率。警区号本身来自 config（覆盖警区），这里仅设计比率/人口/样本档。
# 数学约束：Σ(ratio·pop) == Σpop（否则全市均值会把所有比率整体缩放，设计失真）。
# intent：green/yellow/red = 须安全落在该评级带内（留margin）；boundary_* = 贴 config 阈值。
DESIGN = {
    # precinct: dict(population, ratio 或 None, tier, fixed_count, intent)
    19: dict(pop=120_000, ratio=0.60, tier="100+", fixed=None, intent="green"),      # 上东区
    90: dict(pop=100_000, ratio=None, tier="100+", fixed=None, intent="boundary_g"),  # 威廉斯堡：green_max 边界
    109: dict(pop=50_000, ratio=None, tier="30-99", fixed=None, intent="boundary_r"), # 法拉盛：red_min 边界
    5: dict(pop=60_000, ratio=1.60, tier="100+", fixed=None, intent="red"),          # 唐人街
    84: dict(pop=95_000, ratio=None, tier="lt10", fixed=6, intent="none"),            # 布鲁克林高地：⚪
    26: dict(pop=60_000, ratio=1.00, tier="30-99", fixed=None, intent="yellow"),      # 越界测试用（哥大附近）
    14: dict(pop=60_000, ratio=1.00, tier="30-99", fixed=None, intent="yellow"),      # 中城跨区测试用
    18: dict(pop=60_000, ratio=1.00, tier="30-99", fixed=None, intent="yellow"),      # 中城跨区测试用
    20: dict(pop=20_000, ratio=0.85, tier="10-29", fixed=None, intent="yellow"),      # 10–29 档非边界案例
    61: dict(pop=200_000, ratio=1.625, tier="100+", fixed=None, intent="red"),        # 远离边界的红
    75: dict(pop=60_000, ratio=1.00, tier="30-99", fixed=None, intent="yellow"),      # 远离边界的黄
}

TIER_BOUNDS = {
    "lt10": (0, 9),
    "10-29": (10, 29),
    "30-99": (30, 99),
    "100+": (100, None),
}

FELONIES = ["GRAND LARCENY", "ROBBERY", "BURGLARY", "FELONY ASSAULT"]
MISDEMEANORS = ["PETIT LARCENY", "CRIMINAL MISCHIEF", "MISDEMEANOR ASSAULT", "HARRASSMENT 2"]

BOROUGH = {
    19: "MANHATTAN",
    90: "BROOKLYN",
    109: "QUEENS",
    5: "MANHATTAN",
    84: "BROOKLYN",
    26: "MANHATTAN",
    14: "MANHATTAN",
    18: "MANHATTAN",
    20: "MANHATTAN",
    61: "BROOKLYN",
    75: "BROOKLYN",
}

COLUMNS = [
    "complaint_id",
    "precinct",
    "borough",
    "offense_level",
    "offense_type",
    "occurred_at",
    "hour",
    "is_night",
    "population",
    "source",
]


def design_counts(cfg: config_loader.AppConfig) -> dict[int, int]:
    """求解每警区记录数：边界警区贴 config 阈值，其余安全落在设计评级带内。

    比率 = (count/pop*1e5) / city_mean，city_mean = Σcount/Σpop*1e5。
    DESIGN 已保证 Σ(ratio·pop) == Σpop；对缩放系数做网格搜索 + 坐标下降精修。
    """
    gmax = cfg.thresholds.green_max_ratio
    rmin = cfg.thresholds.red_min_ratio
    if not cfg.covered_precincts <= set(DESIGN):
        raise SystemExit("DESIGN 必须覆盖 config 的全部覆盖警区")

    # 边界警区：目标比率 = 配置阈值（每个档位取一个）
    boundary_green = next(p for p, d in DESIGN.items() if d["intent"] == "boundary_g")
    boundary_red = next(p for p, d in DESIGN.items() if d["intent"] == "boundary_r")
    targets: dict[int, float] = {
        p: d["ratio"] for p, d in DESIGN.items() if d["ratio"] is not None
    }
    targets[boundary_green] = gmax
    targets[boundary_red] = rmin
    for p, d in DESIGN.items():
        if d["fixed"] is None and p not in targets:
            raise SystemExit(f"P{p} 比率与 fixed_count 不能同时为空")

    # 一致性自检：Σ(ratio·pop) 必须 == Σpop，否则全市均值会整体缩放比率
    total_pop = sum(d["pop"] for d in DESIGN.values())
    weighted = sum(targets[p] * DESIGN[p]["pop"] for p in targets)
    assert abs(weighted - total_pop) / total_pop < 1e-9, (
        f"DESIGN 加权比率均值 {weighted / total_pop:.6f} != 1"
    )

    def counts_for(scale: float) -> dict[int, int]:
        return {
            p: (
                d["fixed"]
                if d["fixed"] is not None
                else max(1, round(targets[p] * scale * d["pop"] / 100_000))
            )
            for p, d in DESIGN.items()
        }

    def ratio_of(p: int, c: int, counts: dict[int, int]) -> float:
        mean = (sum(counts.values()) - counts[p] + c) / total_pop * 100_000
        return (c / DESIGN[p]["pop"] * 100_000) / mean

    def in_tier(p: int, c: int) -> bool:
        lo, hi = TIER_BOUNDS[DESIGN[p]["tier"]]
        return c >= lo and (hi is None or c <= hi)

    def total_error(counts: dict[int, int]) -> float:
        """档位违例重罚 + 边界比率偏差总和（非边界警区只要求落在评级带内，不进误差）。"""
        if not all(in_tier(p, counts[p]) for p in DESIGN):
            return float("inf")
        return sum(
            abs(ratio_of(p, counts[p], counts) - targets[p])
            for p in (boundary_green, boundary_red)
        )

    # 标量网格搜索 scale（解析可行域约 [142.9, 152.3]，取宽网格 + 四分之一细分）
    best_counts, best_err = None, None
    for coarse in range(120, 181):
        for fine in (0.0, 0.25, 0.5, 0.75):
            cand = counts_for(coarse + fine)
            err = total_error(cand)
            if best_err is None or err < best_err:
                best_counts, best_err = cand, err
    assert best_err is not None and best_err != float("inf"), "网格内无可行样本数解"
    counts = best_counts

    # 边界警区：档位内整数搜索，最小化 |ratio - 阈值|
    for p in (boundary_green, boundary_red):
        best_c, best_err = counts[p], None
        for c in range(max(1, counts[p] - 40), counts[p] + 40):
            if not in_tier(p, c):
                continue
            err = abs(ratio_of(p, c, counts) - targets[p])
            if best_err is None or err < best_err:
                best_c, best_err = c, err
        counts[p] = best_c

    # 坐标下降精修：非常数且非边界警区在档位内 ±3 搜索，最小化全局边界偏差。
    # 边界警区保持专用搜索的结果（边界精度优先）。
    polishables = [
        p
        for p, d in DESIGN.items()
        if d["fixed"] is None and p not in (boundary_green, boundary_red)
    ]
    for _ in range(4):
        improved = False
        for p in polishables:
            lo, hi = TIER_BOUNDS[DESIGN[p]["tier"]]
            best_c = counts[p]
            best_err = total_error(counts)
            upper = hi if hi is not None else counts[p] + 3
            for c in range(max(lo, counts[p] - 3), min(upper, counts[p] + 3) + 1):
                if c == counts[p]:
                    continue
                trial = dict(counts)
                trial[p] = c
                err = total_error(trial)
                if err < best_err:
                    best_c, best_err = c, err
                    improved = True
            counts[p] = best_c
        if not improved:
            break

    # 校验：样本档 + 评级带（intent margin）
    BAND_MARGIN = {"green": (None, gmax - 0.05), "yellow": (gmax + 0.02, rmin - 0.02), "red": (rmin + 0.1, None)}
    for p, d in DESIGN.items():
        c = counts[p]
        assert in_tier(p, c), f"P{p} 样本数 {c} 不在档位 {d['tier']} 内"
        if d["fixed"] is not None:
            continue
        actual = ratio_of(p, c, counts)
        if d["intent"].startswith("boundary"):
            assert abs(actual - targets[p]) <= 0.012, (
                f"P{p} 比率 {actual:.4f} 偏离边界 {targets[p]} 超过容差"
            )
        else:
            lo, hi = BAND_MARGIN[d["intent"]]
            assert (lo is None or actual >= lo) and (hi is None or actual <= hi), (
                f"P{p} 比率 {actual:.4f} 不在设计评级带 {d['intent']} 内"
            )
    return counts


def build_rows(cfg: config_loader.AppConfig) -> list[dict[str, object]]:
    rng = random.Random(SEED)
    counts = design_counts(cfg)
    rows: list[dict[str, object]] = []
    for pct in sorted(counts):
        pop = DESIGN[pct]["pop"]
        for _ in range(counts[pct]):
            ts = WINDOW_START + timedelta(
                days=rng.randrange(WINDOW_DAYS),
                hours=rng.randrange(24),
                minutes=rng.randrange(60),
                seconds=rng.randrange(60),
            )
            level = "FELONY" if rng.random() < 0.42 else "MISDEMEANOR"
            pool = FELONIES if level == "FELONY" else MISDEMEANORS
            offense = pool[rng.randrange(len(pool))]
            hour = ts.hour
            rows.append(
                {
                    "complaint_id": "",  # 排序后统一编号
                    "precinct": pct,
                    "borough": BOROUGH[pct],
                    "offense_level": level,
                    "offense_type": offense,
                    "occurred_at": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "hour": hour,
                    "is_night": 1 if (hour >= 20 or hour < 6) else 0,
                    "population": pop,
                    "source": DATASET_VERSION,
                }
            )
    rows.sort(key=lambda r: (r["precinct"], r["occurred_at"], r["offense_type"]))
    for i, row in enumerate(rows, 1):
        row["complaint_id"] = f"MOCK-{i:06d}"
    return rows


def render_csv(rows: list[dict[str, object]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def render_manifest(rows: list[dict[str, object]]) -> bytes:
    pops = {int(r["precinct"]): int(r["population"]) for r in rows}
    counts: dict[int, int] = {}
    for r in rows:
        counts[int(r["precinct"])] = counts.get(int(r["precinct"]), 0) + 1
    total_c = sum(counts.values())
    total_p = sum(pops.values())
    mean = total_c / total_p * 100_000
    precincts = {}
    for p in sorted(counts):
        rate = counts[p] / pops[p] * 100_000
        precincts[str(p)] = {
            "records": counts[p],
            "population": pops[p],
            "rate_per_100k": round(rate, 4),
            "ratio_to_city_mean": round(rate / mean, 6),
        }
    doc = {
        "dataset_version": DATASET_VERSION,
        "seed": SEED,
        "window_start": WINDOW_START.strftime("%Y-%m-%d"),
        "window_end_exclusive": WINDOW_END.strftime("%Y-%m-%d"),
        "city_mean_per_100k": round(mean, 4),
        "total_records": total_c,
        "precincts": precincts,
    }
    return (
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def generate(out_dir: Path) -> dict[str, bytes]:
    cfg = config_loader.load_config()
    rows = build_rows(cfg)
    files = {
        "mock_nypd.csv": render_csv(rows),
        "manifest.json": render_manifest(rows),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out_dir / name).write_bytes(data)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="生成确定性模拟 NYPD 数据集")
    parser.add_argument(
        "--check",
        action="store_true",
        help="重新生成到内存并与已落盘文件逐字节比对（确定性自检）",
    )
    args = parser.parse_args()
    out_dir = REPO_ROOT / "fixtures" / "nypd"
    files = generate(out_dir)
    if args.check:
        for name, data in files.items():
            on_disk = (out_dir / name).read_bytes()
            if on_disk != data:
                raise SystemExit(f"确定性自检失败：{name} 与已落盘文件不一致")
        print("确定性自检通过：两次生成逐字节一致")
    print(f"city_mean_per_100k = {json.loads(files['manifest.json'])['city_mean_per_100k']}")
    print(f"total_records = {json.loads(files['manifest.json'])['total_records']}")


if __name__ == "__main__":
    main()
