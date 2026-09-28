import math
from dataclasses import dataclass
import threading
import time

import rclpy
from geometry_msgs.msg import Pose2D, Twist
from rcl_interfaces.msg import SetParametersResult
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from linkguard_interfaces.action import ExecuteMission
from linkguard_interfaces.msg import (
    CommandPacket,
    CommunicationState as CommunicationStateMsg,
    NetworkMetrics,
)

from .communication_policy import (
    LinkHealth,
    LinkState,
    PolicyConfig,
    PolicyDecision,
    evaluate_link_health,
)
from .qos_profiles import command_qos, reliable_qos, state_qos, telemetry_qos


@dataclass(frozen=True)
class MissionSnapshot:
    handle: object
    started_at: float
    stopped_since: object
    x: float
    y: float
    theta: float
    health: LinkHealth
    last_metrics_at: object
    communication_state: LinkState
    speed_scale: float


class MissionServer(Node):
    """Timer-driven mission controller with an Action lifecycle."""

    def __init__(self) -> None:
        super().__init__('mission_server')
        self.declare_parameter('control_rate_hz', 10.0)
        self.declare_parameter('feedback_rate_hz', 2.0)
        self.declare_parameter('linear_gain', 0.8)
        self.declare_parameter('angular_gain', 1.8)
        self.declare_parameter('max_linear_speed', 0.8)
        self.declare_parameter('max_angular_speed', 1.5)
        self.declare_parameter('bad_link_abort_sec', 2.0)
        self.declare_parameter('degraded_delivery_rate', 0.85)
        self.declare_parameter('stopped_delivery_rate', 0.40)
        self.declare_parameter('degraded_latency_ms', 150.0)
        self.declare_parameter('stopped_latency_ms', 500.0)
        self.declare_parameter('degraded_jitter_ms', 50.0)
        self.declare_parameter('stopped_aoi_ms', 750.0)
        self.declare_parameter('degraded_speed_scale', 0.50)
        self.declare_parameter('metrics_min_samples', 10)
        self.declare_parameter('metrics_warmup_sec', 1.0)
        self.declare_parameter('metrics_timeout_sec', 1.5)
        self.declare_parameter('command_qos_reliability', 'reliable')
        self.declare_parameter('command_qos_depth', 10)
        self.add_on_set_parameters_callback(self._validate_parameters)

        self._state_lock = threading.Lock()
        self._pose = Pose2D()
        self._link_health = LinkHealth()
        self._last_metrics_at = None
        self._communication_state = LinkState.GOOD
        self._communication_reason = 'waiting for mission'
        self._communication_speed_scale = 1.0
        self._goal_reserved = False
        self._active_goal_handle = None
        self._started_at = 0.0
        self._stopped_since = None
        self._mission_done = None
        self._mission_result = None

        self._sequence_lock = threading.Lock()
        self._next_command_sequence = 0
        command_profile = command_qos(
            str(self.get_parameter('command_qos_reliability').value),
            int(self.get_parameter('command_qos_depth').value),
        )
        self._command_pub = self.create_publisher(
            CommandPacket,
            '/cmd_vel_raw',
            command_profile,
        )
        self._communication_state_pub = self.create_publisher(
            CommunicationStateMsg,
            '/communication/state',
            state_qos(),
        )
        self.create_subscription(
            Pose2D,
            '/robot/pose',
            self._on_pose,
            telemetry_qos(),
        )
        self.create_subscription(
            NetworkMetrics,
            '/network/metrics',
            self._on_metrics,
            reliable_qos(),
        )

        # Keep the custom group alive for the entire node lifetime.
        self._action_group = ReentrantCallbackGroup()
        self._action_server = ActionServer(
            self,
            ExecuteMission,
            '/execute_mission',
            execute_callback=self._execute,
            goal_callback=self._on_goal,
            cancel_callback=self._on_cancel,
            callback_group=self._action_group,
        )

        # Run the real-time-ish control loop independently of rclpy Action
        # scheduling. Feedback has its own worker so a slow client cannot stall
        # command publication.
        self._workers_stop = threading.Event()
        self._control_thread = threading.Thread(
            target=self._control_loop,
            name='linkguard-control',
            daemon=True,
        )
        self._feedback_thread = threading.Thread(
            target=self._feedback_loop,
            name='linkguard-feedback',
            daemon=True,
        )
        self._control_thread.start()
        self._feedback_thread.start()

    def _validate_parameters(self, parameters):
        positive = {
            'control_rate_hz', 'feedback_rate_hz', 'linear_gain', 'angular_gain',
            'max_linear_speed', 'max_angular_speed', 'bad_link_abort_sec',
        }
        for parameter in parameters:
            if parameter.name in positive and float(parameter.value) <= 0.0:
                return SetParametersResult(
                    successful=False,
                    reason=f'{parameter.name} must be positive',
                )
            if parameter.name in ('command_qos_reliability', 'command_qos_depth'):
                return SetParametersResult(
                    successful=False,
                    reason=f'{parameter.name} requires a node restart',
                )

        policy_values = {
            'degraded_delivery_rate': float(
                self.get_parameter('degraded_delivery_rate').value
            ),
            'stopped_delivery_rate': float(
                self.get_parameter('stopped_delivery_rate').value
            ),
            'degraded_latency_ms': float(
                self.get_parameter('degraded_latency_ms').value
            ),
            'stopped_latency_ms': float(
                self.get_parameter('stopped_latency_ms').value
            ),
            'degraded_jitter_ms': float(
                self.get_parameter('degraded_jitter_ms').value
            ),
            'stopped_aoi_ms': float(self.get_parameter('stopped_aoi_ms').value),
            'degraded_speed_scale': float(
                self.get_parameter('degraded_speed_scale').value
            ),
            'metrics_min_samples': int(
                self.get_parameter('metrics_min_samples').value
            ),
            'metrics_warmup_sec': float(
                self.get_parameter('metrics_warmup_sec').value
            ),
            'metrics_timeout_sec': float(
                self.get_parameter('metrics_timeout_sec').value
            ),
        }
        for parameter in parameters:
            if parameter.name not in policy_values:
                continue
            if parameter.name == 'metrics_min_samples':
                policy_values[parameter.name] = int(parameter.value)
            else:
                policy_values[parameter.name] = float(parameter.value)
        try:
            PolicyConfig(**policy_values).validate()
        except (TypeError, ValueError) as error:
            return SetParametersResult(successful=False, reason=str(error))
        return SetParametersResult(successful=True)

    def _policy_config(self) -> PolicyConfig:
        return PolicyConfig(
            degraded_delivery_rate=float(
                self.get_parameter('degraded_delivery_rate').value
            ),
            stopped_delivery_rate=float(
                self.get_parameter('stopped_delivery_rate').value
            ),
            degraded_latency_ms=float(
                self.get_parameter('degraded_latency_ms').value
            ),
            stopped_latency_ms=float(
                self.get_parameter('stopped_latency_ms').value
            ),
            degraded_jitter_ms=float(
                self.get_parameter('degraded_jitter_ms').value
            ),
            stopped_aoi_ms=float(self.get_parameter('stopped_aoi_ms').value),
            degraded_speed_scale=float(
                self.get_parameter('degraded_speed_scale').value
            ),
            metrics_min_samples=int(
                self.get_parameter('metrics_min_samples').value
            ),
            metrics_warmup_sec=float(
                self.get_parameter('metrics_warmup_sec').value
            ),
            metrics_timeout_sec=float(
                self.get_parameter('metrics_timeout_sec').value
            ),
        )

    def _on_pose(self, message: Pose2D) -> None:
        with self._state_lock:
            self._pose = message

    def _on_metrics(self, message: NetworkMetrics) -> None:
        health = LinkHealth(
            delivery_rate=max(0.0, min(1.0, float(message.measured_delivery_rate))),
            latency_ms=max(0.0, float(message.measured_latency_ms)),
            jitter_ms=max(0.0, float(message.measured_jitter_ms)),
            age_of_information_ms=max(0.0, float(message.age_of_information_ms)),
            window_sample_count=int(message.window_sample_count),
        )
        with self._state_lock:
            self._link_health = health
            self._last_metrics_at = time.monotonic()

    def _on_goal(self, goal_request):
        if goal_request.tolerance <= 0.0 or goal_request.max_duration_sec <= 0.0:
            self.get_logger().warning('Rejecting goal: tolerance and timeout must be positive')
            return GoalResponse.REJECT
        with self._state_lock:
            if self._goal_reserved:
                self.get_logger().warning('Rejecting goal: another mission is active')
                return GoalResponse.REJECT
            self._goal_reserved = True
        return GoalResponse.ACCEPT

    def _on_cancel(self, _goal_handle):
        self.get_logger().info('Cancel request accepted')
        return CancelResponse.ACCEPT

    def _stop(self) -> None:
        self._publish_command(Twist())

    def _publish_command(self, command: Twist) -> None:
        packet = CommandPacket()
        packet.stamp = self.get_clock().now().to_msg()
        with self._sequence_lock:
            packet.sequence = self._next_command_sequence
            self._next_command_sequence += 1
        packet.command = command
        self._command_pub.publish(packet)

    async def _execute(self, goal_handle):
        # Use an executor-owned Future so awaiting the Action result yields the
        # worker thread back to rclpy. A blocking threading.Event here can
        # starve timers and subscriptions on some rclpy executors.
        done = self.executor.create_future()
        with self._state_lock:
            self._active_goal_handle = goal_handle
            self._started_at = time.monotonic()
            self._stopped_since = None
            self._mission_done = done
            self._mission_result = None
            health = self._link_health

        self._apply_policy_decision(
            PolicyDecision(LinkState.GOOD, 1.0, 'collecting fresh mission samples'),
            health,
            force=True,
        )

        result = await done

        with self._state_lock:
            self._goal_reserved = False
            self._active_goal_handle = None
            self._mission_done = None
            self._mission_result = None

        return result

    def _snapshot(self):
        with self._state_lock:
            handle = self._active_goal_handle
            if handle is None:
                return None
            return MissionSnapshot(
                handle=handle,
                started_at=self._started_at,
                stopped_since=self._stopped_since,
                x=float(self._pose.x),
                y=float(self._pose.y),
                theta=float(self._pose.theta),
                health=self._link_health,
                last_metrics_at=self._last_metrics_at,
                communication_state=self._communication_state,
                speed_scale=self._communication_speed_scale,
            )

    def _apply_policy_decision(
        self,
        decision: PolicyDecision,
        health: LinkHealth,
        force: bool = False,
    ) -> None:
        with self._state_lock:
            changed = decision.state != self._communication_state
            self._communication_state = decision.state
            self._communication_reason = decision.reason
            self._communication_speed_scale = decision.speed_scale
        if not changed and not force:
            return

        message = CommunicationStateMsg()
        message.stamp = self.get_clock().now().to_msg()
        message.state = decision.state.value
        message.reason = decision.reason
        message.speed_scale = decision.speed_scale
        message.measured_delivery_rate = health.delivery_rate
        message.measured_latency_ms = health.latency_ms
        message.measured_jitter_ms = health.jitter_ms
        message.age_of_information_ms = health.age_of_information_ms
        message.window_sample_count = health.window_sample_count
        self._communication_state_pub.publish(message)
        self.get_logger().info(
            f'communication state={decision.state.value} '
            f'speed_scale={decision.speed_scale:.2f} reason="{decision.reason}"'
        )

    def _finish(self, handle, state: str, success: bool, message: str, elapsed: float) -> None:
        result = ExecuteMission.Result()
        result.success = success
        result.message = message
        result.elapsed_sec = elapsed

        self._stop()
        if state == 'succeeded':
            handle.succeed()
        elif state == 'canceled':
            handle.canceled()
        else:
            handle.abort()

        with self._state_lock:
            if self._active_goal_handle is not handle:
                return
            self._active_goal_handle = None
            self._mission_result = result
            done = self._mission_done
        if done is not None and not done.done():
            done.set_result(result)

    def _control_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._workers_stop.is_set():
            snapshot = self._snapshot()
            if snapshot is not None:
                self._control_step(snapshot, time.monotonic())

            period = 1.0 / float(self.get_parameter('control_rate_hz').value)
            next_tick += period
            delay = next_tick - time.monotonic()
            if delay <= 0.0:
                # Do not burst old ticks after the process was descheduled.
                next_tick = time.monotonic()
                continue
            self._workers_stop.wait(delay)

    def _control_step(self, snapshot, now: float) -> None:
        handle = snapshot.handle
        elapsed = now - snapshot.started_at
        goal = handle.request
        dx = goal.target_x - snapshot.x
        dy = goal.target_y - snapshot.y
        distance = math.hypot(dx, dy)

        if handle.is_cancel_requested:
            self._finish(handle, 'canceled', False, 'mission canceled by client', elapsed)
            return
        if elapsed >= goal.max_duration_sec:
            self._finish(handle, 'aborted', False, 'mission timed out', elapsed)
            return
        if distance <= goal.tolerance:
            self._finish(handle, 'succeeded', True, 'target reached', elapsed)
            return

        metrics_age_sec = (
            None
            if snapshot.last_metrics_at is None
            else max(0.0, now - snapshot.last_metrics_at)
        )
        decision = evaluate_link_health(
            snapshot.health,
            self._policy_config(),
            elapsed,
            metrics_age_sec,
        )
        self._apply_policy_decision(decision, snapshot.health)

        if decision.state == LinkState.STOPPED:
            stopped_since = snapshot.stopped_since
            if stopped_since is None:
                stopped_since = now
                with self._state_lock:
                    if self._active_goal_handle is handle:
                        self._stopped_since = stopped_since
            self._stop()
            if now - stopped_since >= float(
                self.get_parameter('bad_link_abort_sec').value
            ):
                aborted = PolicyDecision(
                    LinkState.ABORTED,
                    0.0,
                    f'communication remained stopped: {decision.reason}',
                )
                self._apply_policy_decision(aborted, snapshot.health, force=True)
                self._finish(
                    handle,
                    'aborted',
                    False,
                    f'aborted: {aborted.reason}',
                    elapsed,
                )
            return

        if snapshot.stopped_since is not None:
            with self._state_lock:
                if self._active_goal_handle is handle:
                    self._stopped_since = None

        desired_heading = math.atan2(dy, dx)
        heading_error = math.atan2(
            math.sin(desired_heading - snapshot.theta),
            math.cos(desired_heading - snapshot.theta),
        )
        command = Twist()
        max_linear = float(self.get_parameter('max_linear_speed').value)
        max_angular = float(self.get_parameter('max_angular_speed').value)
        command.linear.x = min(max_linear, float(self.get_parameter('linear_gain').value) * distance)
        command.linear.x *= max(0.0, math.cos(heading_error))
        command.linear.x *= decision.speed_scale
        command.angular.z = max(
            -max_angular,
            min(max_angular, float(self.get_parameter('angular_gain').value) * heading_error),
        )
        self._publish_command(command)

    def _feedback_loop(self) -> None:
        next_tick = time.monotonic()
        while not self._workers_stop.is_set():
            snapshot = self._snapshot()
            if snapshot is not None:
                self._feedback_step(snapshot)

            period = 1.0 / float(self.get_parameter('feedback_rate_hz').value)
            next_tick += period
            delay = next_tick - time.monotonic()
            if delay <= 0.0:
                next_tick = time.monotonic()
                continue
            self._workers_stop.wait(delay)

    @staticmethod
    def _feedback_step(snapshot) -> None:
        handle = snapshot.handle
        if not handle.is_active:
            return
        goal = handle.request

        feedback = ExecuteMission.Feedback()
        feedback.current_pose.x = snapshot.x
        feedback.current_pose.y = snapshot.y
        feedback.current_pose.theta = snapshot.theta
        feedback.distance_remaining = math.hypot(
            goal.target_x - snapshot.x,
            goal.target_y - snapshot.y,
        )
        feedback.network_quality = snapshot.health.delivery_rate
        feedback.communication_state = snapshot.communication_state.value
        feedback.speed_scale = snapshot.speed_scale
        handle.publish_feedback(feedback)

    def prepare_shutdown(self) -> None:
        snapshot = self._snapshot()
        if snapshot is not None:
            self._finish(
                snapshot.handle,
                'aborted',
                False,
                'mission server stopped',
                time.monotonic() - snapshot.started_at,
            )
        self._workers_stop.set()
        self._control_thread.join(timeout=1.0)
        self._feedback_thread.join(timeout=1.0)

    def destroy_node(self):
        self.prepare_shutdown()
        self._stop()
        self._action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MissionServer()
    # The Action callback awaits an rclpy Future and does not block. A single
    # executor thread is sufficient and avoids GIL contention with the 10 Hz
    # control worker in CPU-limited containers.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.prepare_shutdown()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
