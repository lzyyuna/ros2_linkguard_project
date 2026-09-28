import rclpy
from rclpy.node import Node

from linkguard_interfaces.msg import CommunicationState, NetworkMetrics

from .qos_profiles import reliable_qos, state_qos


class NetworkMonitor(Node):
    def __init__(self) -> None:
        super().__init__('network_monitor')
        self.create_subscription(
            NetworkMetrics,
            '/network/metrics',
            self._on_metrics,
            reliable_qos(),
        )
        self.create_subscription(
            CommunicationState,
            '/communication/state',
            self._on_communication_state,
            state_qos(),
        )

    def _on_metrics(self, message: NetworkMetrics) -> None:
        self.get_logger().info(
            f'profile={message.profile:<12} '
            f'configured=({message.latency_ms:.1f}ms, {message.jitter_ms:.1f}ms, '
            f'drop={message.drop_rate:.2f}) '
            f'measured=(latency={message.measured_latency_ms:.1f}ms, '
            f'jitter={message.measured_jitter_ms:.1f}ms, '
            f'delivery={message.measured_delivery_rate:.2f}, '
            f'aoi={message.age_of_information_ms:.1f}ms, '
            f'reordered={message.out_of_order_packets}, '
            f'window={message.window_sample_count}) '
            f'packets={message.delivered_packets}/{message.sent_packets} '
            f'dropped={message.dropped_packets}'
        )

    def _on_communication_state(self, message: CommunicationState) -> None:
        self.get_logger().info(
            f'communication_state={message.state:<8} '
            f'speed_scale={message.speed_scale:.2f} '
            f'delivery={message.measured_delivery_rate:.2f} '
            f'latency={message.measured_latency_ms:.1f}ms '
            f'aoi={message.age_of_information_ms:.1f}ms '
            f'reason="{message.reason}"'
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
