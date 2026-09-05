"""pytest 全局接缝（tests/ 根 conftest）。

1. collect_ignore：L2 评估套件（tests/eval/）刻意不进默认基线（spec v2：
   单独 marker/命令跑，judge 依赖 cassette 资产）。默认基线保持零 cassette 依赖；
   运行 L2 套件：pytest tests/eval -q
2. SAFEPASS_DATASET_PATH（票 07 / M2）：生产数据路径已切到 fixtures/nypd_real
   （config data_source.runtime_dataset_path），而整个测试世界（金标期望、
   复算集、cassette 指纹）建立在 mock 数据集之上——mock 保留为测试资产。
   这里强制把默认数据集钉到 mock，保证任何人任何机器上 pytest 跑的都是
   同一测试世界；显式传参的 load_dataset 调用不受影响（解析顺序：传参 > env）。
"""
import os
from pathlib import Path

collect_ignore = ["eval"]

_MOCK_DATASET = Path(__file__).resolve().parent.parent / "fixtures" / "nypd" / "mock_nypd.csv"
os.environ["SAFEPASS_DATASET_PATH"] = str(_MOCK_DATASET)
