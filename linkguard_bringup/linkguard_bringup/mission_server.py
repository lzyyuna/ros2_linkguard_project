import math
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
from linkguard_interfaces.msg import NetworkMetrics


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
        self.declare_parameter('stop_quality_threshold', 0.20)
        self.declare_parameter('bad_link_abort_sec', 2.0)
        self.add_on_set_parameters_callback(self._validate_parameters)

        self._state_lock = threading.Lock()
        self._pose = Pose2D()
        self._network_quality = 1.0
        self._goal_reserved = False
        self._active_goal_handle = None
        self._started_at = 0.0
        self._bad_link_since = None
        self._mission_done = None
        self._mission_result = None

        self._command_pub = self.create_publisher(Twist, '/cmd_vel_raw', 10)
        self.create_subscription(Pose2D, '/robot/pose', self._on_pose, 10)
        self.create_subscription(NetworkMetrics, '/network/metrics', self._on_metrics, 10)

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
                return SetParametersResult(successful=False, reason=f'{parameter.name} must be positive')
            if parameter.name == 'stop_quality_threshold' and not 0.0 <= float(parameter.value) <= 1.0:
                return SetParametersResult(successful=False, reason='stop_quality_threshold must be in [0, 1]')
        return SetParametersResult(successful=True)

    def _on_pose(self, message: Pose2D) -> None:
        with self._state_lock:
            self._pose = message

    def _on_metrics(self, message: NetworkMetrics) -> None:
        # D1 uses configured loss for immediate and stable safety decisions.
        # D2 will replace this with a sliding-window delivery/AoI estimator.
        with self._state_lock:
            self._network_quality = max(0.0, min(1.0, 1.0 - float(message.drop_rate)))

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
        self._command_pub.publish(Twist())

    async def _execute(self, goal_handle):
        # Use an executor-owned Future so awaiting the Action result yields the
        # worker thread back to rclpy. A blocking threading.Event here can
        # starve timers and subscriptions on some rclpy executors.
        done = self.executor.create_future()
        with self._state_lock:
            self._active_goal_handle = goal_handle
            self._started_at = time.monotonic()
            self._bad_link_since = None
            self._mission_done = done
            self._mission_result = None

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
            return (
                handle,
                self._started_at,
                self._bad_link_since,
                float(self._pose.x),
                float(self._pose.y),
                float(self._pose.theta),
                self._network_quality,
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
        handle, started_at, bad_link_since, x, y, theta, quality = snapshot
        elapsed = now - started_at
        goal = handle.request
        dx = goal.target_x - x
        dy = goal.target_y - y
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

        threshold = float(self.get_parameter('stop_quality_threshold').value)
        if quality < threshold:
            if bad_link_since is None:
                bad_link_since = now
                with self._state_lock:
                    if self._active_goal_handle is handle:
                        self._bad_link_since = bad_link_since
            self._stop()
            if now - bad_link_since >= float(self.get_parameter('bad_link_abort_sec').value):
                self._finish(
                    handle,
                    'aborted',
                    False,
                    'aborted: network quality remained below safety threshold',
                    elapsed,
                )
            return

        if bad_link_since is not None:
            with self._state_lock:
                if self._active_goal_handle is handle:
                    self._bad_link_since = None

        desired_heading = math.atan2(dy, dx)
        heading_error = math.atan2(
            math.sin(desired_heading - theta),
            math.cos(desired_heading - theta),
        )
        command = Twist()
        max_linear = float(self.get_parameter('max_linear_speed').value)
        max_angular = float(self.get_parameter('max_angular_speed').value)
        command.linear.x = min(max_linear, float(self.get_parameter('linear_gain').value) * distance)
        command.linear.x *= max(0.0, math.cos(heading_error))
        command.angular.z = max(
            -max_angular,
            min(max_angular, float(self.get_parameter('angular_gain').value) * heading_error),
        )
        self._command_pub.publish(command)

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
        handle, _, _, x, y, theta, quality = snapshot
        if not handle.is_active:
            return
        goal = handle.request

        feedback = ExecuteMission.Feedback()
        feedback.current_pose.x = x
        feedback.current_pose.y = y
        feedback.current_pose.theta = theta
        feedback.distance_remaining = math.hypot(goal.target_x - x, goal.target_y - y)
        feedback.network_quality = quality
        handle.publish_feedback(feedback)

    def prepare_shutdown(self) -> None:
        snapshot = self._snapshot()
        if snapshot is not None:
            handle, started_at, _, _, _, _, _ = snapshot
            self._finish(
                handle,
                'aborted',
                False,
                'mission server stopped',
                time.monotonic() - started_at,
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
