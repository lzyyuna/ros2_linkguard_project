from collections import deque
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node

from linkguard_interfaces.msg import NetworkMetrics
from linkguard_interfaces.srv import SetNetworkProfile

from .link_model import LinkConfig, LinkModel, PROFILES


@dataclass
class PendingCommand:
    due_ns: int
    message: Twist


class LinkEmulator(Node):
    def __init__(self) -> None:
        super().__init__('link_emulator')
        self.declare_parameter('latency_ms', 20.0)
        self.declare_parameter('jitter_ms', 5.0)
        self.declare_parameter('drop_rate', 0.0)
        self.declare_parameter('random_seed', 7)

        config = self._config_from_parameters()
        self._model = LinkModel(config, int(self.get_parameter('random_seed').value))
        self._profile = 'custom'
        self._pending = deque()
        self._sent = 0
        self._delivered = 0
        self._dropped = 0

        self._command_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self._metrics_pub = self.create_publisher(NetworkMetrics, '/network/metrics', 10)
        self.create_subscription(Twist, '/cmd_vel_raw', self._on_command, 10)
        self.create_service(SetNetworkProfile, '/set_network_profile', self._set_profile)
        self.add_on_set_parameters_callback(self._on_parameters)
        self.create_timer(0.005, self._flush_due_commands)
        self.create_timer(0.5, self._publish_metrics)

    def _config_from_parameters(self) -> LinkConfig:
        return LinkConfig(
            float(self.get_parameter('latency_ms').value),
            float(self.get_parameter('jitter_ms').value),
            float(self.get_parameter('drop_rate').value),
        )

    def _on_parameters(self, parameters):
        current = self._model.config
        values = {
            'latency_ms': current.latency_ms,
            'jitter_ms': current.jitter_ms,
            'drop_rate': current.drop_rate,
        }
        for parameter in parameters:
            if parameter.name in values:
                values[parameter.name] = float(parameter.value)
        try:
            config = LinkConfig(**values)
            config.validate()
        except (TypeError, ValueError) as error:
            return SetParametersResult(successful=False, reason=str(error))
        self._model.reconfigure(config)
        self._profile = 'custom'
        return SetParametersResult(successful=True)

    def _set_profile(self, request, response):
        try:
            if request.profile == 'custom':
                config = LinkConfig(request.latency_ms, request.jitter_ms, request.drop_rate)
            elif request.profile in PROFILES:
                config = PROFILES[request.profile]
            else:
                raise ValueError(f'unknown profile: {request.profile}')
            config.validate()
        except ValueError as error:
            response.success = False
            response.message = str(error)
            return response

        self._model.reconfigure(config)
        self._profile = request.profile
        response.success = True
        response.message = (
            f'{request.profile}: latency={config.latency_ms:.1f} ms, '
            f'jitter={config.jitter_ms:.1f} ms, drop={config.drop_rate:.2f}'
        )
        self.get_logger().info(response.message)
        return response

    def _on_command(self, message: Twist) -> None:
        self._sent += 1
        if self._model.should_drop():
            self._dropped += 1
            return
        due_ns = self.get_clock().now().nanoseconds + int(self._model.sample_delay_sec() * 1e9)
        pending = PendingCommand(due_ns, message)
        if not self._pending or self._pending[-1].due_ns <= due_ns:
            self._pending.append(pending)
        else:
            items = list(self._pending)
            items.append(pending)
            items.sort(key=lambda item: item.due_ns)
            self._pending = deque(items)

    def _flush_due_commands(self) -> None:
        now_ns = self.get_clock().now().nanoseconds
        while self._pending and self._pending[0].due_ns <= now_ns:
            self._command_pub.publish(self._pending.popleft().message)
            self._delivered += 1

    def _publish_metrics(self) -> None:
        config = self._model.config
        message = NetworkMetrics()
        message.stamp = self.get_clock().now().to_msg()
        message.latency_ms = config.latency_ms
        message.jitter_ms = config.jitter_ms
        message.drop_rate = config.drop_rate
        message.measured_delivery_rate = self._delivered / self._sent if self._sent else 1.0
        message.sent_packets = self._sent
        message.delivered_packets = self._delivered
        message.dropped_packets = self._dropped
        message.profile = self._profile
        self._metrics_pub.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LinkEmulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
