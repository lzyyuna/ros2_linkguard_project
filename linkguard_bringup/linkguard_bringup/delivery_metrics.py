"""ROS-independent sliding-window delivery measurements."""

from collections import deque
from dataclasses import dataclass
import statistics
from typing import Deque, Optional


@dataclass(frozen=True)
class DeliveryMetricsSnapshot:
    delivery_rate: float
    mean_latency_ms: float
    jitter_ms: float
    age_of_information_ms: float
    out_of_order_packets: int
    window_sample_count: int


class SlidingWindowDeliveryMetrics:
    """Measure finalized delivery outcomes over the most recent packets.

    Dropped packets are finalized when the emulator rejects them. Delivered
    packets are finalized when they leave the delayed queue. Packets still in
    the queue are intentionally excluded so ordinary latency is not mistaken
    for loss.
    """

    def __init__(self, window_size: int = 50) -> None:
        if window_size <= 0:
            raise ValueError('window_size must be positive')
        # None represents a finalized drop; a float represents the measured
        # latency of a finalized delivery. One deque keeps every metric on the
        # exact same packet window.
        self._samples: Deque[Optional[float]] = deque(maxlen=window_size)
        self._highest_delivered_sequence: Optional[int] = None
        self._newest_source_stamp_ns: Optional[int] = None
        self._out_of_order_packets = 0

    @property
    def window_size(self) -> int:
        return self._samples.maxlen

    def record_drop(self, _sequence: int) -> None:
        self._samples.append(None)

    def record_delivery(
        self,
        sequence: int,
        source_stamp_ns: int,
        received_stamp_ns: int,
    ) -> None:
        latency_ms = max(0.0, (received_stamp_ns - source_stamp_ns) / 1_000_000.0)
        self._samples.append(latency_ms)

        if (
            self._highest_delivered_sequence is not None
            and sequence <= self._highest_delivered_sequence
        ):
            self._out_of_order_packets += 1
        else:
            self._highest_delivered_sequence = sequence

        if (
            self._newest_source_stamp_ns is None
            or source_stamp_ns > self._newest_source_stamp_ns
        ):
            self._newest_source_stamp_ns = source_stamp_ns

    def snapshot(self, now_ns: int) -> DeliveryMetricsSnapshot:
        if self._samples:
            delivered_count = sum(sample is not None for sample in self._samples)
            delivery_rate = delivered_count / len(self._samples)
        else:
            delivery_rate = 1.0

        latencies_ms = [sample for sample in self._samples if sample is not None]
        if latencies_ms:
            mean_latency_ms = statistics.fmean(latencies_ms)
            jitter_ms = (
                statistics.pstdev(latencies_ms)
                if len(latencies_ms) > 1
                else 0.0
            )
        else:
            mean_latency_ms = 0.0
            jitter_ms = 0.0

        if self._newest_source_stamp_ns is None:
            age_of_information_ms = 0.0
        else:
            age_of_information_ms = max(
                0.0,
                (now_ns - self._newest_source_stamp_ns) / 1_000_000.0,
            )

        return DeliveryMetricsSnapshot(
            delivery_rate=delivery_rate,
            mean_latency_ms=mean_latency_ms,
            jitter_ms=jitter_ms,
            age_of_information_ms=age_of_information_ms,
            out_of_order_packets=self._out_of_order_packets,
            window_sample_count=len(self._samples),
        )
