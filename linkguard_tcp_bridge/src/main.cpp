#include "linkguard_tcp_bridge/tcp_ros_bridge.hpp"

#include <rclcpp/executors/multi_threaded_executor.hpp>
#include <rclcpp/rclcpp.hpp>

#include <memory>

int main(int argc, char *argv[]) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<linkguard_tcp_bridge::TcpRosBridge>();

  rclcpp::executors::MultiThreadedExecutor executor(rclcpp::ExecutorOptions(), 2);
  executor.add_node(node);
  executor.spin();
  executor.remove_node(node);
  node.reset();

  if (rclcpp::ok()) {
    rclcpp::shutdown();
  }
  return 0;
}
