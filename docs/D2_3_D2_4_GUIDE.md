# D2.3-D2.4 验收指南

## 更新后重新构建

接口文件和Action feedback都发生了变化，必须在工作空间根目录重新构建，并让
每一个新终端重新source：

```bash
cd /home/u2023213113/linkguard_ws
source /opt/ros/$ROS_DISTRO/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test --packages-select linkguard_bringup --event-handlers console_direct+
colcon test-result --verbose
```

如果仍有旧的launch进程，先在它的终端按`Ctrl+C`，否则旧节点与新节点会同时存在，
造成Topic频率、Action结果和指标相互干扰。

## D2.3 通信感知状态机

`mission_server`只在Action任务活动期间解释通信指标。每个任务开始后的
`metrics_warmup_sec`为采样预热期，防止上一次任务留下的高AoI让新任务立即停车。

默认策略：

| 状态 | 默认条件 | 控制行为 |
|---|---|---|
| GOOD | 指标均处于安全范围 | 100%速度 |
| DEGRADED | 交付率低于0.85，或延迟高于150ms，或抖动高于50ms | 50%线速度 |
| STOPPED | 交付率低于0.40，或延迟高于500ms，或AoI高于750ms | 持续发布零速度 |
| ABORTED | STOPPED持续超过2秒 | Action中止 |

状态发布在`/communication/state`，Action feedback同时携带状态和速度缩放比例。

单容器启动：

```bash
ros2 launch linkguard_bringup demo.launch.py
```

观察状态：

```bash
ros2 topic echo /communication/state
```

另一个终端发送足够远的目标，让状态机有时间收集样本：

```bash
ros2 run linkguard_bringup mission_client --x 4 --y 2 --timeout 40
```

依次切换`good`、`congested`和`disconnected`，预期主要转换为：

```text
good         -> GOOD
congested    -> DEGRADED
disconnected -> STOPPED -> ABORTED
```

滑动窗口具有历史记忆，状态不会在Service响应的一瞬间完成转换。恢复良好网络后，
窗口指标会逐渐恢复，状态通常先从STOPPED进入DEGRADED，再进入GOOD。

推荐按下表记录一次验收。每组实验前重启launch可清空机器人位置和统计窗口：

| 场景 | `/communication/state` | 客户端反馈 | Action结果 |
|---|---|---|---|
| good | `GOOD`，`speed_scale=1.0` | 正常收敛 | `SUCCEEDED` |
| congested | `DEGRADED`，默认`speed_scale=0.5` | 位姿收敛变慢 | 给足超时应成功 |
| disconnected | `STOPPED`后`ABORTED` | 剩余距离不再下降 | `ABORTED` |

状态不是由场景名称直接决定，而是由`/network/metrics`里的实测值决定，所以短时间
样本不足时可能先显示`DEGRADED`，这是预期行为。

## D2.4 显式QoS

命令报文支持`reliable`和`best_effort`：

```bash
ros2 launch linkguard_bringup demo.launch.py \
  command_qos_reliability:=reliable
```

或：

```bash
ros2 launch linkguard_bringup demo.launch.py \
  command_qos_reliability:=best_effort
```

同一条通信链路上的发布者和订阅者必须使用兼容QoS。QoS在实体创建时确定，因此
运行时修改`command_qos_reliability`和`command_qos_depth`会被拒绝，修改后需要重启节点。

确认实际端点QoS：

```bash
ros2 topic info /cmd_vel_raw --verbose
ros2 topic info /cmd_vel --verbose
```

注意：`link_emulator`的随机丢包发生在应用层。即使命令Topic使用RELIABLE，模拟器
主动丢弃的报文也不会被DDS重传。QoS对照测试研究的是DDS链路本身，不应把
`drop_rate`造成的应用层丢包误认为BEST_EFFORT的效果。

## 双容器部署

容器职责：

```text
control容器：mission_server、network_monitor
robot容器：link_emulator、robot_sim
```

跨容器Topic包括`/cmd_vel_raw`、`/robot/pose`和`/network/metrics`；
`/set_network_profile` Service同样可以从control容器访问robot容器。

构建并启动：

```bash
docker compose build
docker compose up
```

另开终端确认两个进程组通过DDS互相发现：

```bash
docker compose exec control /linkguard_entrypoint.sh ros2 node list
docker compose exec control /linkguard_entrypoint.sh \
  ros2 topic info /cmd_vel_raw --verbose
```

节点列表应至少包含`/mission_server`、`/network_monitor`、`/link_emulator`和
`/robot_sim`；`/cmd_vel_raw`应显示控制容器中的publisher和机器人容器中的subscriber。

另开终端发送任务：

```bash
docker compose exec control /linkguard_entrypoint.sh \
  ros2 run linkguard_bringup mission_client --x 2 --y 1 --timeout 20
```

切换网络：

```bash
docker compose exec control /linkguard_entrypoint.sh \
  ros2 service call /set_network_profile \
  linkguard_interfaces/srv/SetNetworkProfile \
  "{profile: congested, latency_ms: 0.0, jitter_ms: 0.0, drop_rate: 0.0}"
```

使用BEST_EFFORT重新创建容器：

```bash
COMMAND_QOS_RELIABILITY=best_effort docker compose up --force-recreate
```

停止：

```bash
docker compose down
```

学校服务器如果不提供Docker权限，可以先完成单容器QoS与状态机验收，再在个人电脑
完成双容器演示。两个容器仍位于同一台主机，主要验证ROS 2发现、接口兼容和跨网络
命名空间通信；跨物理主机还需要时钟同步和防火墙配置。

## D2.3-D2.4完成判据

- 单元测试通过；
- good、congested、disconnected三种场景出现预期状态和Action结果；
- Action feedback能看到`communication`与`speed_scale`；
- `ros2 topic info --verbose`能证明QoS配置生效；
- 双容器模式下四个节点可发现，Service可跨容器切换场景，Action任务能闭环执行。

这一步完成的是状态机、QoS配置入口和分布式部署能力。大量重复实验、CSV/绘图和
统计结论仍属于后续D2实验报告，不应仅凭一次运行宣称QoS性能优劣。
