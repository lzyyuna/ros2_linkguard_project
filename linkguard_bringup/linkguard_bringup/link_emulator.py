from collections import deque
from dataclasses import dataclass

import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node

from linkguard_interfaces.msg import CommandPacket, CommandReceipt, NetworkMetrics
from linkguard_interfaces.srv import SetNetworkProfile

from .delivery_metrics import SlidingWindowDeliveryMetrics
from .link_model import LinkConfig, LinkModel, PROFILES
from .qos_profiles import command_qos, reliable_qos


@dataclass
class PendingCommand:
    due_ns: int
    message: CommandPacket


class LinkEmulator(Node):
    def __init__(self) -> None:
        super().__init__('link_emulator')
        self.declare_parameter('latency_ms', 20.0)
        self.declare_parameter('jitter_ms', 5.0)
        self.declare_parameter('drop_rate', 0.0)
        self.declare_parameter('random_seed', 7)
        self.declare_parameter('metrics_window_size', 50)
        self.declare_parameter('command_qos_reliability', 'reliable')
        self.declare_parameter('command_qos_depth', 10)

        config = self._config_from_parameters()
        self._model = LinkModel(config, int(self.get_parameter('random_seed').value))
        self._profile = 'custom'
        self._pending = deque()
        self._sent = 0
        self._delivered = 0
        self._dropped = 0
        self._delivery_metrics = SlidingWindowDeliveryMetrics(
            int(self.get_parameter('metrics_window_size').value)
        )
        receipt_history_size = max(100, self._delivery_metrics.window_size * 4)
        self._recent_receipts = deque()
        self._recent_receipt_set = set()
        self._receipt_history_size = receipt_history_size

        command_profile = command_qos(
            str(self.get_parameter('command_qos_reliability').value),
            int(self.get_parameter('command_qos_depth').value),
        )
        self._command_pub = self.create_publisher(
            CommandPacket,
            '/cmd_vel',
            command_profile,
        )
        self._metrics_pub = self.create_publisher(
            NetworkMetrics,
            '/network/metrics',
            reliable_qos(),
        )
        self.create_subscription(
            CommandPacket,
            '/cmd_vel_raw',
            self._on_command,
            command_profile,
        )
        self.create_subscription(
            CommandReceipt,
            '/cmd_vel_receipt',
            self._on_receipt,
            reliable_qos(),
        )
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
            if parameter.name in (
                'metrics_window_size',
                'command_qos_reliability',
                'command_qos_depth',
            ):
                return SetParametersResult(
                    successful=False,
                    reason=f'{parameter.name} requires a node restart',
                )
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

    def _on_command(self, message: CommandPacket) -> None:
        self._sent += 1
        if self._model.should_drop():
            self._dropped += 1
            self._delivery_metrics.record_drop(int(message.sequence))
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
            packet = self._pending.popleft().message
            self._command_pub.publish(packet)

    def _on_receipt(self, receipt: CommandReceipt) -> None:
        sequence = int(receipt.sequence)
        if sequence in self._recent_receipt_set:
            return
        if len(self._recent_receipts) >= self._receipt_history_size:
            expired_sequence = self._recent_receipts.popleft()
            self._recent_receipt_set.remove(expired_sequence)
        self._recent_receipts.append(sequence)
        self._recent_receipt_set.add(sequence)

        self._delivered += 1
        source_stamp_ns = (
            int(receipt.source_stamp.sec) * 1_000_000_000
            + int(receipt.source_stamp.nanosec)
        )
        received_stamp_ns = (
            int(receipt.received_stamp.sec) * 1_000_000_000
            + int(receipt.received_stamp.nanosec)
        )
        self._delivery_metrics.record_delivery(
            sequence,
            source_stamp_ns,
            received_stamp_ns,
        )

    def _publish_metrics(self) -> None:
        now = self.get_clock().now()
        config = self._model.config
        measured = self._delivery_metrics.snapshot(now.nanoseconds)
        message = NetworkMetrics()
        message.stamp = now.to_msg()
        message.latency_ms = config.latency_ms
        message.jitter_ms = config.jitter_ms
        message.drop_rate = config.drop_rate
        message.measured_delivery_rate = measured.delivery_rate
        message.measured_latency_ms = measured.mean_latency_ms
        message.measured_jitter_ms = measured.jitter_ms
        message.age_of_information_ms = measured.age_of_information_ms
        message.sent_packets = self._sent
        message.delivered_packets = self._delivered
        message.dropped_packets = self._dropped
        message.out_of_order_packets = measured.out_of_order_packets
        message.window_sample_count = measured.window_sample_count
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
