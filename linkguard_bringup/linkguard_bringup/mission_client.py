import argparse
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from linkguard_interfaces.action import ExecuteMission


class MissionClient(Node):
    def __init__(self) -> None:
        super().__init__('mission_client')
        self._client = ActionClient(self, ExecuteMission, '/execute_mission')

    @staticmethod
    def _feedback(message) -> None:
        feedback = message.feedback
        pose = feedback.current_pose
        print(
            f'pose=({pose.x:.2f}, {pose.y:.2f}, {pose.theta:.2f}) '
            f'remaining={feedback.distance_remaining:.2f} m '
            f'network_quality={feedback.network_quality:.2f} '
            f'communication={feedback.communication_state} '
            f'speed_scale={feedback.speed_scale:.2f}'
        )

    def run(self, x: float, y: float, tolerance: float, timeout: float,
            cancel_after: float) -> None:
        if not self._client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError('action server /execute_mission was not found')

        goal = ExecuteMission.Goal()
        goal.target_x = x
        goal.target_y = y
        goal.tolerance = tolerance
        goal.max_duration_sec = timeout
        send_future = self._client.send_goal_async(goal, feedback_callback=self._feedback)
        rclpy.spin_until_future_complete(self, send_future)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            print('Goal rejected')
            return

        print(f'Goal accepted: target=({x:.2f}, {y:.2f})')
        result_future = goal_handle.get_result_async()

        if cancel_after > 0.0:
            deadline = time.monotonic() + cancel_after
            while rclpy.ok() and not result_future.done() and time.monotonic() < deadline:
                rclpy.spin_once(self, timeout_sec=0.1)
            if not result_future.done():
                print(f'Requesting cancellation after {cancel_after:.1f} s')
                cancel_future = goal_handle.cancel_goal_async()
                rclpy.spin_until_future_complete(self, cancel_future)
                if not cancel_future.result().goals_canceling:
                    print('Cancellation request was rejected')

        rclpy.spin_until_future_complete(self, result_future)
        wrapped = result_future.result()
        result = wrapped.result
        print(
            f'Finished: status={wrapped.status}, success={result.success}, '
            f'elapsed={result.elapsed_sec:.2f} s, message="{result.message}"'
        )


def main(args=None) -> None:
    parser = argparse.ArgumentParser(description='Send and optionally cancel a LinkGuard mission.')
    parser.add_argument('--x', type=float, default=5.0)
    parser.add_argument('--y', type=float, default=2.0)
    parser.add_argument('--tolerance', type=float, default=0.1)
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--cancel-after', type=float, default=0.0)
    cli_args, ros_args = parser.parse_known_args(args=args)

    rclpy.init(args=ros_args)
    node = MissionClient()
    try:
        node.run(
            cli_args.x,
            cli_args.y,
            cli_args.tolerance,
            cli_args.timeout,
            cli_args.cancel_after,
        )
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
