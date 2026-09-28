"""Repeatable single-host QoS experiment orchestrator for LinkGuard."""

import argparse
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import signal
import socket
import statistics
import subprocess
import sys
import time

from action_msgs.msg import GoalStatus
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.utilities import remove_ros_args

from linkguard_interfaces.action import ExecuteMission
from linkguard_interfaces.msg import CommunicationState, NetworkMetrics
from linkguard_interfaces.srv import SetNetworkProfile

from .qos_profiles import reliable_qos, state_qos


CSV_FIELDS = [
    'timestamp_utc', 'hostname', 'platform', 'ros_distro',
    'rmw_implementation', 'git_commit', 'reliability', 'qos_depth',
    'profile', 'repetition',
    'random_seed', 'goal_x', 'goal_y', 'tolerance', 'timeout_sec',
    'success', 'action_status', 'message', 'elapsed_sec', 'wall_time_sec',
    'final_distance_m', 'feedback_count', 'metrics_samples',
    'delivery_rate_mean', 'delivery_rate_min', 'latency_ms_mean',
    'jitter_ms_mean', 'aoi_ms_mean', 'aoi_ms_max', 'sent_packets',
    'delivered_packets', 'application_dropped_packets',
    'transport_dropped_packets', 'out_of_order_packets',
    'good_duration_sec', 'degraded_duration_sec', 'stopped_duration_sec',
    'error',
]


STATUS_NAMES = {
    GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
    GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
    GoalStatus.STATUS_EXECUTING: 'EXECUTING',
    GoalStatus.STATUS_CANCELING: 'CANCELING',
    GoalStatus.STATUS_SUCCEEDED: 'SUCCEEDED',
    GoalStatus.STATUS_CANCELED: 'CANCELED',
    GoalStatus.STATUS_ABORTED: 'ABORTED',
}


def _mean(values):
    return statistics.fmean(values) if values else 0.0


class ExperimentProbe(Node):
    def __init__(self) -> None:
        super().__init__('qos_experiment_runner')
        self._action = ActionClient(self, ExecuteMission, '/execute_mission')
        self._profile_client = self.create_client(
            SetNetworkProfile,
            '/set_network_profile',
        )
        self.create_subscription(
            NetworkMetrics,
            '/network/metrics',
            self._on_metrics,
            reliable_qos(),
        )
        self.create_subscription(
            CommunicationState,
            '/communication/state',
            self._on_state,
            state_qos(),
        )
        self._collecting = False
        self._metrics = []
        self._state_durations = {}
        self._current_state = None
        self._state_changed_at = 0.0
        self._feedback_count = 0
        self._final_distance = 0.0

    def wait_until_ready(self, timeout_sec: float, process) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f'launch exited early with code {process.returncode}'
                )
            action_ready = self._action.wait_for_server(timeout_sec=0.25)
            service_ready = self._profile_client.wait_for_service(timeout_sec=0.25)
            if action_ready and service_ready:
                return
            rclpy.spin_once(self, timeout_sec=0.05)
        raise TimeoutError('ROS graph did not become ready before startup timeout')

    def wait_until_stopped(self, timeout_sec: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            action_ready = self._action.server_is_ready()
            service_ready = self._profile_client.service_is_ready()
            if not action_ready and not service_ready:
                return
            rclpy.spin_once(self, timeout_sec=0.1)

    def set_profile(self, profile: str) -> None:
        request = SetNetworkProfile.Request()
        request.profile = profile
        request.latency_ms = 0.0
        request.jitter_ms = 0.0
        request.drop_rate = 0.0
        future = self._profile_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        if not future.done() or future.result() is None:
            raise TimeoutError(f'profile service timed out for {profile}')
        response = future.result()
        if not response.success:
            raise RuntimeError(response.message)

    def _begin_collection(self) -> None:
        self._metrics = []
        self._state_durations = {}
        self._current_state = None
        self._state_changed_at = time.monotonic()
        self._feedback_count = 0
        self._final_distance = 0.0
        self._collecting = True

    def _end_collection(self) -> None:
        self._record_state_duration(time.monotonic())
        self._collecting = False

    def _record_state_duration(self, now: float) -> None:
        if self._current_state is None:
            return
        elapsed = max(0.0, now - self._state_changed_at)
        self._state_durations[self._current_state] = (
            self._state_durations.get(self._current_state, 0.0) + elapsed
        )
        self._state_changed_at = now

    def _observe_state(self, state: str) -> None:
        if not self._collecting or not state or state == self._current_state:
            return
        now = time.monotonic()
        self._record_state_duration(now)
        self._current_state = state
        self._state_changed_at = now

    def _on_state(self, message: CommunicationState) -> None:
        self._observe_state(message.state)

    def _on_metrics(self, message: NetworkMetrics) -> None:
        if not self._collecting:
            return
        self._metrics.append({
            'delivery_rate': float(message.measured_delivery_rate),
            'latency_ms': float(message.measured_latency_ms),
            'jitter_ms': float(message.measured_jitter_ms),
            'aoi_ms': float(message.age_of_information_ms),
            'sent_packets': int(message.sent_packets),
            'delivered_packets': int(message.delivered_packets),
            'application_dropped_packets': int(message.dropped_packets),
            'transport_dropped_packets': int(message.transport_dropped_packets),
            'out_of_order_packets': int(message.out_of_order_packets),
        })

    def _on_feedback(self, message) -> None:
        feedback = message.feedback
        self._feedback_count += 1
        self._final_distance = float(feedback.distance_remaining)
        self._observe_state(feedback.communication_state)

    def run_goal(
        self,
        x: float,
        y: float,
        tolerance: float,
        timeout_sec: float,
    ) -> dict:
        goal = ExecuteMission.Goal()
        goal.target_x = x
        goal.target_y = y
        goal.tolerance = tolerance
        goal.max_duration_sec = timeout_sec

        self._begin_collection()
        wall_started = time.monotonic()
        send_future = self._action.send_goal_async(
            goal,
            feedback_callback=self._on_feedback,
        )
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=5.0)
        handle = send_future.result() if send_future.done() else None
        if handle is None or not handle.accepted:
            self._end_collection()
            raise RuntimeError('experiment goal was rejected')

        result_future = handle.get_result_async()
        deadline = time.monotonic() + timeout_sec + 10.0
        while rclpy.ok() and not result_future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        if not result_future.done():
            cancel_future = handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=3.0)
            self._end_collection()
            raise TimeoutError('Action result exceeded experiment safety timeout')

        wrapped = result_future.result()
        rclpy.spin_once(self, timeout_sec=0.2)
        self._end_collection()
        wall_elapsed = time.monotonic() - wall_started
        result = wrapped.result

        metric = self._metrics[-1] if self._metrics else {}
        delivery_rates = [item['delivery_rate'] for item in self._metrics]
        latencies = [item['latency_ms'] for item in self._metrics]
        jitters = [item['jitter_ms'] for item in self._metrics]
        ages = [item['aoi_ms'] for item in self._metrics]
        return {
            'success': bool(result.success),
            'action_status': STATUS_NAMES.get(wrapped.status, str(wrapped.status)),
            'message': result.message,
            'elapsed_sec': float(result.elapsed_sec),
            'wall_time_sec': wall_elapsed,
            'final_distance_m': self._final_distance,
            'feedback_count': self._feedback_count,
            'metrics_samples': len(self._metrics),
            'delivery_rate_mean': _mean(delivery_rates),
            'delivery_rate_min': min(delivery_rates, default=0.0),
            'latency_ms_mean': _mean(latencies),
            'jitter_ms_mean': _mean(jitters),
            'aoi_ms_mean': _mean(ages),
            'aoi_ms_max': max(ages, default=0.0),
            'sent_packets': metric.get('sent_packets', 0),
            'delivered_packets': metric.get('delivered_packets', 0),
            'application_dropped_packets': metric.get(
                'application_dropped_packets', 0
            ),
            'transport_dropped_packets': metric.get(
                'transport_dropped_packets', 0
            ),
            'out_of_order_packets': metric.get('out_of_order_packets', 0),
            'good_duration_sec': self._state_durations.get('GOOD', 0.0),
            'degraded_duration_sec': self._state_durations.get('DEGRADED', 0.0),
            'stopped_duration_sec': self._state_durations.get('STOPPED', 0.0),
            'error': '',
        }


def _append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open('a', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, '') for field in CSV_FIELDS})
        stream.flush()


def _completed_keys(path: Path):
    if not path.exists():
        return set()
    with path.open(newline='', encoding='utf-8') as stream:
        rows = csv.DictReader(stream)
        return {
            (
                row.get('reliability', ''),
                row.get('profile', ''),
                int(row.get('repetition', '0')),
                int(row.get('qos_depth', '0')),
                int(row.get('random_seed', '0')),
            )
            for row in rows
            if not row.get('error') and row.get('action_status') != 'ERROR'
        }


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def _start_demo(reliability: str, depth: int, seed: int, log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_path.open('w', encoding='utf-8')
    command = [
        'ros2', 'launch', 'linkguard_bringup', 'demo.launch.py',
        f'command_qos_reliability:={reliability}',
        f'command_qos_depth:={depth}',
        f'random_seed:={seed}',
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    except Exception:
        log_stream.close()
        raise
    return process, log_stream


def _stop_demo(process, log_stream) -> None:
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2.0)
    finally:
        log_stream.close()


def _parse_args(args):
    parser = argparse.ArgumentParser(
        description='Run repeated LinkGuard QoS/profile experiments.',
    )
    parser.add_argument('--repetitions', type=int, default=10)
    parser.add_argument(
        '--profiles', nargs='+',
        choices=['good', 'congested', 'disconnected'],
        default=['good', 'congested', 'disconnected'],
    )
    parser.add_argument(
        '--reliabilities', nargs='+',
        choices=['reliable', 'best_effort'],
        default=['reliable', 'best_effort'],
    )
    parser.add_argument('--qos-depth', type=int, default=10)
    parser.add_argument('--target-x', type=float, default=2.0)
    parser.add_argument('--target-y', type=float, default=1.0)
    parser.add_argument('--tolerance', type=float, default=0.1)
    parser.add_argument('--timeout', type=float, default=40.0)
    parser.add_argument('--startup-timeout', type=float, default=15.0)
    parser.add_argument('--base-seed', type=int, default=1000)
    parser.add_argument('--cooldown-sec', type=float, default=1.0)
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Keep the existing CSV and skip completed trial keys.',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('experiments/results/qos_trials.csv'),
    )
    parsed = parser.parse_args(args)
    if parsed.repetitions <= 0:
        parser.error('--repetitions must be positive')
    if parsed.qos_depth <= 0:
        parser.error('--qos-depth must be positive')
    return parsed


def main(args=None) -> None:
    raw_args = sys.argv if args is None else [sys.argv[0], *args]
    cli_args = remove_ros_args(args=raw_args)[1:]
    options = _parse_args(cli_args)
    output = options.output.expanduser().resolve()
    logs = output.parent / 'logs'
    if output.exists() and output.stat().st_size > 0 and not options.resume:
        raise FileExistsError(
            f'{output} already exists; move it or pass --resume'
        )
    completed_keys = _completed_keys(output) if options.resume else set()
    environment = {
        'hostname': socket.gethostname(),
        'platform': platform.platform(),
        'ros_distro': os.environ.get('ROS_DISTRO', 'unknown'),
        'rmw_implementation': os.environ.get('RMW_IMPLEMENTATION', 'default'),
        'git_commit': _git_commit(),
    }

    rclpy.init(args=[])
    probe = ExperimentProbe()
    total = len(options.reliabilities) * len(options.profiles) * options.repetitions
    completed = 0
    try:
        for profile_index, profile in enumerate(options.profiles):
            for repetition in range(1, options.repetitions + 1):
                for reliability in options.reliabilities:
                    # The same profile/repetition receives the same seed for both
                    # reliabilities, enabling a paired comparison.
                    seed = options.base_seed + profile_index * 100 + repetition
                    label = f'{reliability}-{profile}-{repetition:02d}'
                    log_path = logs / f'{label}.log'
                    key = (
                        reliability,
                        profile,
                        repetition,
                        options.qos_depth,
                        seed,
                    )
                    if key in completed_keys:
                        completed += 1
                        print(f'[{completed}/{total}] {label}: skipped (complete)')
                        continue
                    base = {
                        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                        **environment,
                        'reliability': reliability,
                        'qos_depth': options.qos_depth,
                        'profile': profile,
                        'repetition': repetition,
                        'random_seed': seed,
                        'goal_x': options.target_x,
                        'goal_y': options.target_y,
                        'tolerance': options.tolerance,
                        'timeout_sec': options.timeout,
                    }
                    process = None
                    log_stream = None
                    try:
                        process, log_stream = _start_demo(
                            reliability,
                            options.qos_depth,
                            seed,
                            log_path,
                        )
                        probe.wait_until_ready(options.startup_timeout, process)
                        probe.set_profile(profile)
                        result = probe.run_goal(
                            options.target_x,
                            options.target_y,
                            options.tolerance,
                            options.timeout,
                        )
                        row = {**base, **result}
                    except Exception as error:  # Keep later repetitions usable.
                        row = {
                            **base,
                            'success': False,
                            'action_status': 'ERROR',
                            'message': '',
                            'error': str(error),
                        }
                    finally:
                        if process is not None and log_stream is not None:
                            _stop_demo(process, log_stream)
                            probe.wait_until_stopped()
                    _append_row(output, row)
                    completed += 1
                    print(
                        f'[{completed}/{total}] {label}: '
                        f'status={row.get("action_status")} '
                        f'success={row.get("success")} '
                        f'elapsed={row.get("elapsed_sec", "-")} '
                        f'error={row.get("error", "")}',
                        flush=True,
                    )
                    time.sleep(max(0.0, options.cooldown_sec))
    except KeyboardInterrupt:
        print('Experiment interrupted; completed CSV rows were preserved.')
    finally:
        probe.destroy_node()
        rclpy.shutdown()

    print(f'Raw results: {output}')


if __name__ == '__main__':
    main()
