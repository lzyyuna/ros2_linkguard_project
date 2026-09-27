# 阶段性交付计划

## 项目目标

构建一个可复现实验平台，量化网络时延、抖动、丢包和 ROS 2 QoS 对机器人闭环任务的影响，并实现网络恶化时的安全降级。

最终要让面试官看到三件事：

1. 你理解 ROS 2 通信语义，不只是会调用 API；
2. 你能把通信指标映射到机器人任务指标；
3. 你具备从需求、架构、实现、测试到演示的工程闭环能力。

## D0-D1：通信闭环 MVP（当前版本）

周期建议：7 天。

交付物：

- 自定义 `NetworkMetrics.msg`、`SetNetworkProfile.srv`、`ExecuteMission.action`；
- `robot_sim`、`link_emulator`、`mission_server`、`network_monitor` 四个节点；
- launch 文件、YAML 参数、纯 Python 链路模型单测；
- 可演示的良好/拥塞/断连三种场景。

验收：

- good 网络下 30 秒内到达 `(5, 2)`；
- Action 持续返回当前位置、剩余距离、链路质量；
- 运行中可通过 Service 切换网络；
- 运行中可通过 Parameter 修改安全阈值；
- 客户端取消后 500 ms 内输出零速度；
- disconnected 状态持续超过保护时限后 Action 中止。

学习重点：Topic、Service、Parameter、Action 的职责边界和协作关系。

## D2：QoS 与可观测性实验

周期建议：10 天。

新增内容：

- 比较 `BEST_EFFORT` 与 `RELIABLE`；
- 比较不同 depth、deadline、lifespan；
- 使用 rosbag2 记录位姿、命令和网络指标；
- 输出 CSV 与 matplotlib 图：完成时间、稳态误差、控制命令新鲜度、投递率；
- 添加 launch testing 或 pytest 集成测试。

验收：至少完成 3 × 3 组参数实验，每组重复 10 次，报告均值、标准差与结论。不能只截图，要有原始数据和可复现脚本。

面试亮点：能解释 DDS QoS 如何影响业务，而不是背 QoS 名称。

## D3：多机器人与工程可靠性

周期建议：14 天。

新增内容：

- 使用 namespace 启动 3 台机器人；
- 一个调度器并发管理多个 Action goal；
- 按链路质量和任务优先级分配任务；
- 使用 lifecycle node 管理启动、降级和恢复；
- 加入 heartbeat、超时、重试、幂等和异常注入；
- 记录结构化日志与诊断信息。

验收：随机网络故障下运行 20 分钟，任务不死锁；单机器人故障不拖垮其他机器人；恢复后可继续接单。

面试亮点：从“会写节点”提升到“会设计分布式机器人系统”。

## D4：企业级包装

周期建议：7 天。

新增内容：

- GitHub Actions：lint、单测、构建；
- Docker/Dev Container；
- 架构决策记录（ADR）；
- 2 分钟演示视频与 6 页技术汇报；
- 性能报告、已知限制、后续路线；
- Issue、里程碑、规范化 commit 和 release tag。

验收：陌生人在一台干净的 Ubuntu 主机上，按 README 能在 15 分钟内复现 Demo。

## 每周复盘模板

- 本周目标：一句话，可验收。
- 已完成：链接到代码、测试、图表或视频。
- 遇到的问题：现象、定位过程、根因。
- 技术决策：选择、备选、权衡。
- 指标变化：用数字说话。
- 下周风险：最多三项，每项有应对措施。
