# 通信契约

## Topic

| 名称 | 类型 | 发布者 | 订阅者 | 频率 | 语义 |
|---|---|---|---|---|---|
| `/cmd_vel_raw` | `geometry_msgs/Twist` | mission_server | link_emulator | 10 Hz | 未经过网络的控制指令 |
| `/cmd_vel` | `geometry_msgs/Twist` | link_emulator | robot_sim | 不固定 | 经过丢包和延迟后的控制指令 |
| `/robot/pose` | `geometry_msgs/Pose2D` | robot_sim | mission_server | 20 Hz | 机器人二维位姿 |
| `/network/metrics` | `NetworkMetrics` | link_emulator | mission_server/monitor | 2 Hz | 链路配置和累计投递指标 |

第一阶段全部使用默认 QoS，避免一次引入过多概念。D2 再系统比较 QoS。

## Service

`/set_network_profile` 使用 `SetNetworkProfile.srv`。

- `good`：20 ms 时延、5 ms 抖动、0% 丢包；
- `congested`：180 ms 时延、60 ms 抖动、25% 丢包；
- `disconnected`：0 ms 时延、0 ms 抖动、100% 丢包；
- `custom`：使用请求中的三个数值。

无效 profile 或越界值必须返回 `success=false`，不能悄悄接受错误配置。

## Parameter

关键参数：

- link_emulator：`latency_ms`、`jitter_ms`、`drop_rate`、`random_seed`；
- robot_sim：`update_rate_hz`、`command_timeout_sec`、`max_linear_speed`；
- mission_server：`control_rate_hz`、`linear_gain`、`max_linear_speed`、`stop_quality_threshold`、`bad_link_abort_sec`。

Parameter 表示节点配置，Service 表示明确的业务操作。“切换网络场景”用 Service；“微调阈值”用 Parameter。

## Action

`/execute_mission` 使用 `ExecuteMission.action`。

- Goal：目标点、容差、最长执行时间；
- Feedback：当前位姿、剩余距离、网络质量；
- Result：成功与否、原因、耗时；
- Cancel：立即发零速度并返回 canceled。

服务器一次只执行一个目标，新的并发目标会被拒绝。D3 再扩展多机器人并发。

## 安全规则

1. 命令超过 `command_timeout_sec` 未更新，robot_sim 自动停车；
2. 链路质量低于阈值持续 `bad_link_abort_sec`，mission_server 中止；
3. Action 成功、取消、超时或异常时都必须发布零速度；
4. 所有运行期参数更新先校验再提交。

## 外部 TCP 网关

`linkguard_tcp_bridge` 是 Windows 上位机与 ROS 2 图之间的边界适配器。它沿用
`tcp_stream_lab` 的 4 字节大端长度前缀协议，但不复制机器人业务状态机：任务状态的
唯一事实来源仍是 `/execute_mission` Action。

- `START|task|x|y|tolerance|max_duration`：发送 Action goal；
- `STATUS[|task]`：读取桥接节点保存的最新 Action 状态；
- `STOP|task`：调用 Action cancel；
- `PING|sequence`：网络线程直接回复 `PONG|sequence`，不经过 ROS 2；
- 所有外发帧经过同一个 TCP 写线程；
- TCP 断线只停止遥测转发，不自动取消正在执行的任务。
- Action Feedback 中的 `communication_state` 和 `speed_scale` 会原样转发到上位机，
  用于区分正常、降速和安全停车状态。

详细字段和联调步骤见 [TCP_ROS2_BRIDGE.md](TCP_ROS2_BRIDGE.md)。
