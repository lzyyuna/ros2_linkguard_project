# 通信契约

## Topic

| 名称 | 类型 | 发布者 | 订阅者 | 频率 | 语义 |
|---|---|---|---|---|---|
| `/cmd_vel_raw` | `CommandPacket` | mission_server | link_emulator | 10 Hz | 带发送时间和序号的原始控制指令 |
| `/cmd_vel` | `CommandPacket` | link_emulator | robot_sim | 不固定 | 经过丢包和延迟后的控制报文 |
| `/cmd_vel_receipt` | `CommandReceipt` | robot_sim | link_emulator | 每个已接收命令一次 | 机器人接收确认和接收时间 |
| `/robot/pose` | `geometry_msgs/Pose2D` | robot_sim | mission_server | 20 Hz | 机器人二维位姿 |
| `/network/metrics` | `NetworkMetrics` | link_emulator | mission_server/monitor | 2 Hz | 链路配置、累计计数和滑动窗口实测指标 |
| `/communication/state` | `CommunicationState` | mission_server | network_monitor/运维端 | 状态变化时 | 通信安全状态、限速比例和判定原因 |

`CommandPacket.sequence`单调递增，用于发现丢失与乱序；`stamp`记录控制命令的
源端发送时间。robot_sim实际收到报文后发布`CommandReceipt`，链路模拟器使用
回执中的源时间和接收时间计算端到端延迟，避免把“已经publish”误认为“机器人
已经收到”。

实测指标使用最近`metrics_window_size`个已经完成的结果，默认窗口为50。
已丢弃和已投递报文进入窗口，仍在延迟队列中的报文暂不进入窗口，避免把延迟
误判为丢包。`age_of_information_ms`表示最新已投递源数据距当前时刻的年龄。

显式QoS约定：

- `/cmd_vel_raw`和`/cmd_vel`：KEEP_LAST，depth默认10，reliability可在启动时选择`reliable`或`best_effort`；
- `/robot/pose`：BEST_EFFORT、VOLATILE，允许新位姿替代旧位姿；
- `/cmd_vel_receipt`和`/network/metrics`：RELIABLE、VOLATILE；
- `/communication/state`：RELIABLE、TRANSIENT_LOCAL、depth 1，新订阅者可立即得到最近状态。

QoS在publisher/subscription创建时确定，`command_qos_reliability`与
`command_qos_depth`运行时不可修改，变更后需要重启相关节点。

## Service

`/set_network_profile` 使用 `SetNetworkProfile.srv`。

- `good`：20 ms 时延、5 ms 抖动、0% 丢包；
- `congested`：180 ms 时延、60 ms 抖动、25% 丢包；
- `disconnected`：0 ms 时延、0 ms 抖动、100% 丢包；
- `custom`：使用请求中的三个数值。

无效 profile 或越界值必须返回 `success=false`，不能悄悄接受错误配置。

## Parameter

关键参数：

- link_emulator：`latency_ms`、`jitter_ms`、`drop_rate`、`random_seed`、`metrics_window_size`；
- robot_sim：`update_rate_hz`、`command_timeout_sec`、`max_linear_speed`；
- mission_server：`control_rate_hz`、`linear_gain`、`max_linear_speed`、状态机阈值、`bad_link_abort_sec`；
- 三个命令链路节点：`command_qos_reliability`、`command_qos_depth`（仅启动时生效）。

Parameter 表示节点配置，Service 表示明确的业务操作。“切换网络场景”用 Service；“微调阈值”用 Parameter。

## Action

`/execute_mission` 使用 `ExecuteMission.action`。

- Goal：目标点、容差、最长执行时间；
- Feedback：当前位姿、剩余距离、实测交付率、通信状态、速度缩放比例；
- Result：成功与否、原因、耗时；
- Cancel：立即发零速度并返回 canceled。

服务器一次只执行一个目标，新的并发目标会被拒绝。D3 再扩展多机器人并发。

## 安全规则

1. 命令超过 `command_timeout_sec` 未更新，robot_sim 自动停车；
2. 实测通信指标触发STOPPED时立即输出零速度，持续 `bad_link_abort_sec` 后Action中止；
3. Action 成功、取消、超时或异常时都必须发布零速度；
4. 所有运行期参数更新先校验再提交。

## D2测量口径

- `latency_ms`、`jitter_ms`、`drop_rate`：Service或Parameter设置的仿真配置；
- `measured_latency_ms`：窗口内已投递报文的实际平均延迟；
- `measured_jitter_ms`：窗口内已投递报文延迟的总体标准差；
- `measured_delivery_rate`：窗口内已投递数量除以已完成结果数量；
- `age_of_information_ms`：当前时间减去最新已投递报文的源时间戳；
- `out_of_order_packets`：序号不大于历史最高已投递序号的累计次数；
- `window_sample_count`：当前窗口内已完成结果的数量。

## D2.3状态策略

- `GOOD`：指标健康，线速度比例1.0；
- `DEGRADED`：交付率、延迟或抖动达到预警阈值，按`degraded_speed_scale`限速；
- `STOPPED`：交付率、延迟、AoI或指标超时达到危险条件，发布零速度；
- `ABORTED`：STOPPED连续超过`bad_link_abort_sec`，中止当前Action。

每个任务开始时有`metrics_warmup_sec`预热期，用新任务产生的控制回执刷新指标，
防止空闲阶段累积的高AoI导致任务刚开始就停车。
