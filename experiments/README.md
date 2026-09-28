# 实验产物

运行器默认把原始数据写到：

```text
experiments/results/qos_trials.csv
```

分析器默认示例输出目录：

```text
experiments/results/report/
├── qos_summary.csv
├── qos_elapsed.svg
├── qos_delivery.svg
├── qos_transport_drops.svg
├── qos_expected_outcome.svg
└── QOS_EXPERIMENT_REPORT.md
```

`logs/`只用于排查单次launch失败，已被Git忽略。原始CSV、汇总CSV、图表和最终
报告属于作品集证据，可以提交到仓库。
