import math

import rclpy
from geometry_msgs.msg import Pose2D, Twist
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult

from linkguard_interfaces.msg import CommandPacket, CommandReceipt

from .qos_profiles import command_qos, reliable_qos, telemetry_qos


class RobotSim(Node):
    """Minimal planar kinematic robot with a command watchdog."""

    def __init__(self) -> None:
        super().__init__('robot_sim')
        self.declare_parameter('update_rate_hz', 20.0)
        self.declare_parameter('command_timeout_sec', 0.5)
        self.declare_parameter('max_linear_speed', 1.0)
        self.declare_parameter('command_qos_reliability', 'reliable')
        self.declare_parameter('command_qos_depth', 10)

        self._pose = Pose2D()
        self._command = Twist()
        self._last_command_ns = self.get_clock().now().nanoseconds
        command_profile = command_qos(
            str(self.get_parameter('command_qos_reliability').value),
            int(self.get_parameter('command_qos_depth').value),
        )
        self._pose_pub = self.create_publisher(
            Pose2D,
            '/robot/pose',
            telemetry_qos(),
        )
        self._receipt_pub = self.create_publisher(
            CommandReceipt,
            '/cmd_vel_receipt',
            reliable_qos(),
        )
        self.create_subscription(
            CommandPacket,
            '/cmd_vel',
            self._on_command,
            command_profile,
        )
        self.add_on_set_parameters_callback(self._validate_parameters)

        rate = float(self.get_parameter('update_rate_hz').value)
        self._timer = self.create_timer(1.0 / rate, self._update)
        self._last_update_ns = self.get_clock().now().nanoseconds

    def _validate_parameters(self, parameters):
        for parameter in parameters:
            if parameter.name in ('command_qos_reliability', 'command_qos_depth'):
                return SetParametersResult(
                    successful=False,
                    reason=f'{parameter.name} requires a node restart',
                )
            if parameter.name in ('update_rate_hz', 'command_timeout_sec', 'max_linear_speed'):
                if float(parameter.value) <= 0.0:
                    return SetParametersResult(successful=False, reason=f'{parameter.name} must be positive')
        return SetParametersResult(successful=True)

    def _on_command(self, message: CommandPacket) -> None:
        now = self.get_clock().now()
        self._command = message.command
        self._last_command_ns = now.nanoseconds

        receipt = CommandReceipt()
        receipt.source_stamp = message.stamp
        receipt.received_stamp = now.to_msg()
        receipt.sequence = message.sequence
        self._receipt_pub.publish(receipt)

    def _update(self) -> None:
        now_ns = self.get_clock().now().nanoseconds
        dt = max(0.0, (now_ns - self._last_update_ns) / 1e9)
        self._last_update_ns = now_ns

        timeout = float(self.get_parameter('command_timeout_sec').value)
        command_age = (now_ns - self._last_command_ns) / 1e9
        command_expired = command_age > timeout
        speed = 0.0 if command_expired else self._command.linear.x
        angular_speed = 0.0 if command_expired else self._command.angular.z
        speed_limit = float(self.get_parameter('max_linear_speed').value)
        speed = max(-speed_limit, min(speed, speed_limit))

        self._pose.theta += angular_speed * dt
        self._pose.theta = math.atan2(math.sin(self._pose.theta), math.cos(self._pose.theta))
        self._pose.x += speed * math.cos(self._pose.theta) * dt
        self._pose.y += speed * math.sin(self._pose.theta) * dt
        self._pose_pub.publish(self._pose)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RobotSim()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
