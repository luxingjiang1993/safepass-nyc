"""city_mean 重算回填工具（票 07 / M2，spec v2）。

单一公式：city_mean_per_100k = Σcount / Σpop × 1e5（Σpop 取 config
coverage.precinct_populations 口径；与 scripts/generate_fixtures.py 的
manifest 公式、safepass/data_agent.py 的就地复算同一事实源）。

运行时评级由 data_agent.rating_config 就加载数据集自动复算，本工具服务的是
config/app.yaml 里的落盘锚点（生产数据集复算值）：月更真实数据
（scripts/fetch_nypd.py）后重跑本脚本同步回填。

用法：
    python scripts/recompute_city_mean.py                 # 打印复算值与 config 现值
    python scripts/recompute_city_mean.py --check         # 不一致退出码 1（CI/ralph 承诺验证）
    python scripts/recompute_city_mean.py --update-config # 就地回填 config/app.yaml（保留 4 位小数）
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from safepass import config_loader  # noqa: E402

# 与 data_agent._TIMESTAMP_FORMAT 同构的复算只需要计数，不解析时间戳；
# 窗口校验属 data_agent.load_dataset 职责，这里只复算均值。


def recompute(cfg: config_loader.AppConfig) -> float:
    """从 config 运行时数据集复算全市均值（真实 CSV 无人口列，按警区 join config 表）。"""
    csv_path = REPO_ROOT / cfg.data_source.runtime_dataset_path
    if not csv_path.exists():
        raise SystemExit(f"运行时数据集不存在：{csv_path}（先运行 scripts/fetch_nypd.py）")
    counts: dict[int, int] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = int(r["precinct"])
            counts[p] = counts.get(p, 0) + 1
    missing = set(counts) - set(cfg.precinct_populations)
    if missing:
        raise SystemExit(f"警区 {sorted(missing)} 不在 coverage.precinct_populations 人口表内")
    total_count = sum(counts.values())
    total_pop = sum(cfg.precinct_populations[p] for p in counts)
    return total_count / total_pop * 100_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SafePass city_mean 重算回填（票 07）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="复算值与 config 不一致时退出码 1")
    mode.add_argument("--update-config", action="store_true", help="就地回填 config/app.yaml")
    args = parser.parse_args(argv)

    cfg = config_loader.get_config()
    mean = recompute(cfg)
    rounded = round(mean, 4)
    current = cfg.city_mean_per_100k
    print(f"复算 city_mean_per_100k = {rounded}（数据集 {cfg.data_source.runtime_dataset_path}）")
    print(f"config 现值              = {current}")

    if args.check:
        if current is None or abs(current - mean) > 1e-3:
            print("不一致：运行 python scripts/recompute_city_mean.py --update-config", file=sys.stderr)
            return 1
        print("一致 ✓")
        return 0
    if args.update_config:
        config_path = REPO_ROOT / "config" / "app.yaml"
        text = config_path.read_text(encoding="utf-8")
        updated, n = re.subn(
            r"^(city_mean_per_100k:\s*)[0-9.]+",
            rf"\g<1>{rounded}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise SystemExit("config/app.yaml 中未找到唯一的 city_mean_per_100k 行，拒绝改写")
        config_path.write_text(updated, encoding="utf-8")
        print(f"已回填 {config_path}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
