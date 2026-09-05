collect_ignore = ["eval"]
# L2 评估套件（tests/eval/）刻意不进默认基线（spec v2：单独 marker/命令跑，
# judge 依赖 cassette 资产）。默认基线保持零 cassette 依赖；
# 运行 L2 套件：pytest tests/eval -q
