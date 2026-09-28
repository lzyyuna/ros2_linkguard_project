# 贡献指南

## 开发流程

1. 从最新稳定分支创建短生命周期分支；
2. 一个提交只解决一个清晰问题；
3. 修改通信接口时同步更新`docs/COMMUNICATION_CONTRACT.md`；
4. 修改运行行为时添加或更新测试；
5. Pull Request中写明复现步骤、验证结果和已知风险。

## 本地检查

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test --packages-select linkguard_bringup --event-handlers console_direct+
colcon test-result --verbose
```

## 提交信息

推荐使用动词开头并描述结果，例如：

```text
Add paired QoS experiment runner
Fix stale communication-state recovery
Document D2 acceptance procedure
```

不要提交`build/`、`install/`、`log/`或实验过程日志。用于作品集的原始CSV、
汇总CSV、SVG图表和最终报告可以提交。
