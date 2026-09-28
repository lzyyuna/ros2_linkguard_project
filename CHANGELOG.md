# Changelog

## 0.4.0

- 增加RELIABLE/BEST_EFFORT重复对照实验运行器；
- 使用配对随机种子并在每次试验前重启节点；
- 增加原始CSV、汇总CSV、SVG图表和Markdown报告生成器；
- 增加DDS入口序号缺口统计，区分传输丢失与应用层模拟丢包；
- 增加GitHub Actions构建与测试流程；
- 增加贡献规范、PR模板、许可证和实验协议。

## 0.3.0

- 增加GOOD/DEGRADED/STOPPED/ABORTED通信状态机；
- 根据实测交付率、延迟、抖动和AoI限速或停车；
- 显式配置Topic QoS；
- 提供控制端与机器人端拆分launch和双容器配置。

## 0.2.0

- 控制报文增加序号和源时间戳；
- 机器人增加接收回执；
- 增加滑动窗口交付率、延迟、抖动、AoI和乱序统计。

## 0.1.0

- 完成Topic、Service、Parameter和Action单机器人通信闭环。
