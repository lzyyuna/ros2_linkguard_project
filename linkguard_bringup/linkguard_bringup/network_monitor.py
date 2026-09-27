import rclpy
from rclpy.node import Node

from linkguard_interfaces.msg import NetworkMetrics


class NetworkMonitor(Node):
    def __init__(self) -> None:
        super().__init__('network_monitor')
        self.create_subscription(NetworkMetrics, '/network/metrics', self._on_metrics, 10)

    def _on_metrics(self, message: NetworkMetrics) -> None:
        self.get_logger().info(
            f'profile={message.profile:<12} latency={message.latency_ms:6.1f}ms '
            f'jitter={message.jitter_ms:5.1f}ms configured_drop={message.drop_rate:.2f} '
            f'delivery={message.measured_delivery_rate:.2f} '
            f'packets={message.delivered_packets}/{message.sent_packets}'
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = NetworkMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
