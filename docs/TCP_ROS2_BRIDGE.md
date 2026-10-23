# Windows TCP 上位机与 ROS 2 桥接

## 目标

Windows 只负责操作员交互和 TCP 连接；Linux 运行 ROS 2、LinkGuard 仿真与
`linkguard_tcp_bridge`。桥接节点把 TCP 命令转换为 `/execute_mission` Action goal，
并把 Action 的反馈、结果和取消状态转换回 TCP 消息。

```text
Windows tcp_server_win
        │  TCP（4 字节大端长度 + UTF-8 文本）
        ▼
Linux linkguard_tcp_bridge
        │  ExecuteMission Action
        ▼
mission_server → link_emulator → robot_sim
```

原来的 `tcp_stream_lab` 保持为独立的 TCP 学习项目。LinkGuard 只复用了它的帧协议，
没有把原来的 `RobotSimulator` 搬进 ROS 2。

## 命令协议

Windows 发出的命令：

```text
START|<task-id>|<target-x>|<target-y>|<tolerance>|<max-duration-sec>
STATUS
STATUS|<task-id>
STOP|<task-id>
QUIT
```

示例：

```text
START|1001|5.0|2.0|0.10|30.0
STATUS|1001
STOP|1001
QUIT
```

Linux 可能返回：

```text
ACK|1001|ACCEPTED
FEEDBACK|1001|42|3.117|0.950|DEGRADED|0.500|1.420|0.610
STATUS|1001|RUNNING|42|3.117|0.950|DEGRADED|0.500|1.420|0.610
RESULT|1001|SUCCEEDED|12.430|target reached
ACK|1001|CANCEL_REQUESTED
ERROR|1002|BUSY_WITH|1001
```

`STATUS` 和 `FEEDBACK` 的任务状态后依次为：进度估计、剩余距离、网络质量、
通信状态、速度缩放、当前 x、当前 y。进度仅用于上位机显示；任务是否完成以
Action result 为准。通信状态和速度缩放来自 LinkGuard v0.4.0 的安全降级策略。

## 线程边界

- TCP 接收线程：收完整帧、立即处理 `PING`、把业务命令放入队列；
- ROS 2 执行器线程：解析业务命令、发送 Action goal、发起取消；
- TCP 发送线程：唯一允许调用 `send` 的线程，避免心跳、反馈和结果交叉写坏帧；
- Action 回调：更新受互斥锁保护的任务快照，并把消息放入发送队列。

Windows 断开后桥接节点每 2 秒重连。ROS 2 任务不会因为 TCP 短暂断开而自动取消；
重新连接后发送 `STATUS|<task-id>` 可读取当前状态。断线期间产生的实时反馈不缓存，
以免重连后发送已经过期的数据。

## 在学校 Linux 服务器构建

把本仓库三个 ROS 2 包放到同一个工作空间的 `src` 下，然后：

```bash
cd ~/linkguard_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

## 联调顺序

1. Windows 启动上位机：

   ```powershell
   .\build\windows\Debug\tcp_server_win.exe 19001
   ```

2. Linux 启动完整仿真，把 IP 换成 Windows 的实际 IPv4 地址：

   ```bash
   ros2 launch linkguard_tcp_bridge tcp_demo.launch.py \
     server_ip:=10.29.213.237 server_port:=19001
   ```

3. Windows 输入：

   ```text
   START|1001|5.0|2.0|0.10|30.0
   STATUS|1001
   ```

4. 任务运行时在 Linux 另一个终端切换网络配置，观察上位机的 `FEEDBACK`、
   `RESULT` 是否反映链路恶化：

   ```bash
   ros2 service call /set_network_profile linkguard_interfaces/srv/SetNetworkProfile \
     "{profile: congested, latency_ms: 0.0, jitter_ms: 0.0, drop_rate: 0.0}"
   ```

## 第一轮验收

- good 网络下收到 `SUCCEEDED`；
- 运行中发送 `STOP`，最终收到 `CANCELED`；
- mission_server 未启动时收到 `ACTION_SERVER_UNAVAILABLE`；
- Windows 重启后 Linux 自动重连，`STATUS` 仍能查询正在执行的 ROS 2 任务；
- Windows 心跳持续工作，Action 反馈不会破坏帧边界。
