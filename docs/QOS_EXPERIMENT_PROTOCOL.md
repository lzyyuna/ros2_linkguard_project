# QoS重复对照实验协议

## 实验问题

在相同机器人任务、相同应用层网络场景和相同随机序列下，命令Topic使用
`RELIABLE`或`BEST_EFFORT`是否会改变任务结果与通信指标？

## 因素设计

| 因素 | 水平 |
|---|---|
| command reliability | reliable、best_effort |
| network profile | good、congested、disconnected |
| 重复次数 | 每个组合10次 |
| QoS depth | 固定10 |
| 任务目标 | 固定(2, 1) |

总实验次数：`2 × 3 × 10 = 60`。

同一个profile和重复编号在两种reliability下使用相同随机种子，减少随机链路序列
差异对QoS比较的干扰。每次试验都会重新启动四个节点，从原点开始并清空统计窗口。

## 运行前检查

不要手动运行`demo.launch.py`，实验工具会自行启动和停止它。先确认当前没有旧节点：

```bash
ros2 node list
```

然后构建并加载最新代码：

```bash
cd /home/u2023213113/linkguard_ws
source /opt/ros/$ROS_DISTRO/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test --packages-select linkguard_bringup --event-handlers console_direct+
colcon test-result --verbose
```

## 先做6次冒烟实验

先用每个组合1次确认流程正确：

```bash
cd /home/u2023213113/linkguard_ws/src/ros2_linkguard_project

ros2 run linkguard_bringup qos_experiment \
  --repetitions 1 \
  --output experiments/results/qos_smoke.csv
```

CSV应有6行。`disconnected`的`success=False`和`ABORTED`是预期结果，不是实验失败；
真正的基础设施失败记录在`error`列。

## 正式重复实验

```bash
ros2 run linkguard_bringup qos_experiment \
  --repetitions 10 \
  --qos-depth 10 \
  --target-x 2 \
  --target-y 1 \
  --timeout 40 \
  --base-seed 1000 \
  --output experiments/results/qos_trials.csv
```

运行器每完成一次试验就刷新CSV，因此中途断开不会丢失已完成记录。继续中断的实验使用同一条命令并加上`--resume`，它会跳过已完成组合。不加`--resume`时，已存在的非空CSV会被拒绝，防止误追加重复数据。

```bash
ros2 run linkguard_bringup qos_experiment \
  --repetitions 10 \
  --resume \
  --output experiments/results/qos_trials.csv
```

## 生成CSV汇总、图表和报告

```bash
ros2 run linkguard_bringup qos_analyze \
  --input experiments/results/qos_trials.csv \
  --output-dir experiments/results/report
```

生成内容：

- `qos_summary.csv`：按QoS与场景聚合的均值和标准差；
- `qos_elapsed.svg`：平均任务耗时；
- `qos_delivery.svg`：平均实测交付率；
- `qos_transport_drops.svg`：从序号缺口推断的DDS入口丢失；
- `qos_expected_outcome.svg`：是否得到该场景的预期Action结果；
- `QOS_EXPERIMENT_REPORT.md`：带表格、图表和结论边界的自动报告。

## 数据口径

- `application_dropped_packets`：link_emulator按`drop_rate`主动丢弃的报文；
- `transport_dropped_packets`：通过`/cmd_vel_raw`序号缺口推断的DDS入口丢失；
- `delivery_rate_mean`：试验期间2Hz网络指标样本的交付率平均值；
- `elapsed_sec`：Action服务器测得的任务时间；
- `expected_outcome_rate`：good/congested应成功，disconnected应中止。

## 解释限制

应用层随机丢包发生在DDS已经把消息送到link_emulator之后，因此RELIABLE不会恢复
模拟器主动删除的报文。在单机环境中DDS通常很稳定，两种QoS可能几乎没有差异。
“没有观察到明显差异”仍然是有效结论，但不能推导为所有网络环境下两者完全等价。
