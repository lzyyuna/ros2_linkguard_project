# D1 学习任务卡（7 天）

不要把现成代码当答案；把它当实验台。每天都必须留下命令记录、现象和一句自己的解释。

## Day 1：读懂图和接口

- 手画一次节点图，标出发布者、订阅者、客户端、服务端；
- 用自己的话解释 4 种通信机制为什么这样分工；
- 阅读三个自定义接口，预测 CLI 命令的输入和输出。

验收：不看 README，也能完整讲出一条任务指令如何经过系统。

## Day 2：只运行 Topic 链路

- 单独运行 `robot_sim`；
- 用 CLI 向 `/cmd_vel` 发布带`Twist`的`CommandPacket`；
- echo `/robot/pose`；
- 改发布频率，观察看门狗停车。

思考：为什么控制 Topic 停止后机器人必须自行停车，不能只依赖上游发零速度？

## Day 3：Parameter

- 列出每个节点参数；
- 在线修改 `command_timeout_sec` 和 `max_linear_speed`；
- 故意设置负值，确认节点拒绝；
- 阅读参数校验回调。

验收：解释“声明参数”和“动态参数校验”的区别。

## Day 4：Service 与链路故障注入

- 分别切换 good、congested、disconnected；
- echo `/network/metrics`；
- 发一个非法 profile 和一个 `drop_rate=1.2` 的 custom 请求；
- 记录响应和日志。

验收：解释为什么 Service 失败要显式返回，而不是在日志里悄悄报错。

## Day 5：Action

- 发目标并观察 feedback；
- 中途取消；
- 发送不合法 goal；
- 用极短的 `max_duration_sec` 触发超时。

验收：能区分 rejected、aborted、canceled、succeeded 四种状态。

## Day 6：联调与故障实验

分别录制以下四次实验：

1. good 网络成功到达；
2. congested 网络成功但更慢；
3. disconnected 导致安全停车和 abort；
4. 客户端 cancel 导致停车和 canceled。

每次记录目标、网络配置、耗时、最终状态。

## Day 7：做一次属于你的修改

从以下任选一个：

- 新增 `poor` profile；
- 在 feedback 中加入任务已用时间；
- 加入目标边界检查（例如坐标必须在 `[-10, 10]`）；
- 把累计投递率改成 2 秒滑动窗口投递率；
- 给 robot_sim 增加轨迹 Topic。

验收：提交一个小而完整的 commit，包含代码、测试和 README 变更。

## 阶段答辩问题

1. 哪些数据需要连续传播，哪些操作需要明确响应？
2. Service 为什么不能替代 Action？
3. Parameter 变更失败时，旧值是否仍然有效？
4. 如果 Action server 崩溃，机器人为什么仍能停下？
5. 为什么等待队列中的报文不能立刻算作丢失？滑动窗口如何改进累计投递率？
6. DDS QoS 尚未显式配置时使用什么默认行为？这会带来什么风险？
