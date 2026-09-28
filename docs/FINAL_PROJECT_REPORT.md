# LinkGuard最终项目报告

## 1. 项目定位

LinkGuard是一个单机器人网络感知任务控制原型。项目重点不是构建完整导航栈，
而是展示ROS 2通信机制、端到端通信测量、通信故障决策和安全控制之间的闭环。

系统使用Topic传输控制与遥测，Service切换网络场景，Parameter配置控制和安全策略，
Action管理有反馈、可取消、可超时的移动任务。

## 2. 完成范围

- 四节点通信闭环：mission_server、link_emulator、robot_sim、network_monitor；
- 控制报文序号、源时间戳和机器人接收回执；
- 滑动窗口交付率、实测延迟、抖动、AoI和乱序；
- GOOD、DEGRADED、STOPPED、ABORTED通信状态机；
- 控制端停车与机器人端命令看门狗双层安全保护；
- 10Hz控制线程、2Hz反馈线程与ROS执行器解耦；
- 显式Topic QoS与RELIABLE/BEST_EFFORT切换；
- 可复现重复实验、CSV汇总、SVG图表和Markdown报告；
- GitHub Actions构建测试、许可证、贡献指南和变更日志。

双容器配置已经提供，但学校Nomad实例不开放Docker，因此不作为本次最终验收条件。

## 3. 功能验收

| 场景 | 实测表现 | 状态 | 控制行为 | Action结果 |
|---|---|---|---|---|
| good | 低延迟、低抖动、交付率接近1 | GOOD | 全速 | SUCCEEDED |
| congested | 约180ms延迟、约25%应用层丢包 | DEGRADED | 默认50%线速度 | SUCCEEDED |
| disconnected | 无新报文、AoI持续增长 | STOPPED→ABORTED | 停车 | ABORTED |

取消、超时、参数校验、Service场景切换、20Hz位姿和10Hz控制命令也均已完成验收。

## 4. QoS重复实验

实验设计为：

```text
2种reliability × 3种network profile × 每组10次 = 60次
```

两种QoS使用相同profile、目标、depth和配对随机种子。每次试验重启节点，避免机器人
位置和滑动窗口污染下一组结果。

### 4.1 数据质量

- 原始记录：60；
- 有效记录：60；
- 基础设施错误：0；
- 六个组合预期结果率：全部100%。

### 4.2 关键结果

| QoS | 场景 | 任务耗时(s) | 平均交付率 | 延迟(ms) | 抖动(ms) | 结果 |
|---|---|---:|---:|---:|---:|---|
| BEST_EFFORT | good | 4.541 ± 0.038 | 1.000 ± 0.000 | 23.3 | 4.3 | 10/10成功 |
| RELIABLE | good | 4.642 ± 0.260 | 0.993 ± 0.023 | 24.7 | 8.0 | 10/10成功 |
| BEST_EFFORT | congested | 7.582 ± 0.159 | 0.751 ± 0.069 | 183.9 | 53.4 | 10/10成功 |
| RELIABLE | congested | 7.545 ± 0.136 | 0.754 ± 0.066 | 187.5 | 55.7 | 10/10成功 |
| BEST_EFFORT | disconnected | 3.364 ± 0.044 | 0.000 | 0.0 | 0.0 | 10/10按预期中止 |
| RELIABLE | disconnected | 3.346 ± 0.066 | 0.000 | 0.0 | 0.0 | 10/10按预期中止 |

![任务耗时](../experiments/results/report/qos_elapsed.svg)

![交付率](../experiments/results/report/qos_delivery.svg)

### 4.3 结论

在本次单机、低发布频率、低DDS负载环境中，没有观察到RELIABLE相对BEST_EFFORT
具有实质性的任务成功率或完成时间优势。congested场景的平均耗时差仅0.037秒，平均
交付率差仅0.003；disconnected场景的安全中止时间差约0.018秒。

这一结果与系统结构一致：主要故障由link_emulator在DDS已经交付消息后进行应用层
注入，RELIABLE不能恢复模拟器主动删除的报文。结果证明状态机对网络profile的响应
稳定，但不能用来宣称两种QoS在真实受限网络中等价。

good/reliable组出现平均0.1个DDS入口序号缺口，相当于10次实验共观察到约1个缺口。
该数量过小，且缺少更高负载和跨主机证据，不应据此判断RELIABLE更差。

完整自动报告见
[QOS_EXPERIMENT_REPORT.md](../experiments/results/report/QOS_EXPERIMENT_REPORT.md)。

## 5. 关键工程问题与修复

项目早期出现控制命令频率降至约0.4～2Hz、Action频繁超时的问题。根因是长时间运行
的Action执行路径占用了ROS回调调度。修复后将任务控制与反馈分别放入10Hz和2Hz
工作线程，Action协程只等待Future，ROS执行器继续处理订阅和服务回调。最终
`/cmd_vel_raw`稳定在约10Hz，good场景任务稳定完成。

这一故障分析比继续堆叠QoS参数更能展示执行器、线程、回调和实时控制之间的理解。

## 6. 已知限制

- 二维运动学模型，不包含真实动力学、传感器和执行器；
- 网络故障主要在应用层模拟，不等同于真实无线信道或DDS传输故障；
- 实验在单机环境完成，不能外推到跨主机和带宽受限环境；
- DDS缺口通过单发布者单调序号推断；
- 双容器配置未在学校环境验收；
- 当前系统只管理一台机器人。

## 7. 最终结论

项目已经实现并验证从任务下发、控制命令、故障网络、机器人反馈、指标计算到安全
决策的完整闭环。它证明的不只是ROS 2 API使用能力，还包括通信接口设计、可观测性、
线程问题定位、安全降级、自动测试和实验结论边界意识。

本阶段到此收尾，不再扩展QoS参数矩阵。后续如果继续开发，应把它作为新的里程碑，
优先选择真实多主机通信、机器人硬件接入或多机器人调度，而不是继续增加低价值的
单机QoS排列组合。
