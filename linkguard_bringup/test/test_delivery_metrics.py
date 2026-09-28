import pytest

from linkguard_bringup.delivery_metrics import SlidingWindowDeliveryMetrics


def test_window_uses_only_recent_finalized_outcomes():
    metrics = SlidingWindowDeliveryMetrics(window_size=3)
    metrics.record_drop(1)
    metrics.record_delivery(2, 1_000_000_000, 1_100_000_000)
    metrics.record_delivery(3, 2_000_000_000, 2_100_000_000)

    snapshot = metrics.snapshot(2_200_000_000)
    assert snapshot.delivery_rate == pytest.approx(2.0 / 3.0)
    assert snapshot.window_sample_count == 3

    metrics.record_delivery(4, 3_000_000_000, 3_100_000_000)
    snapshot = metrics.snapshot(3_200_000_000)
    assert snapshot.delivery_rate == 1.0
    assert snapshot.mean_latency_ms == pytest.approx(100.0)


def test_latency_samples_leave_with_the_same_packet_window():
    metrics = SlidingWindowDeliveryMetrics(window_size=2)
    metrics.record_delivery(1, 1_000_000_000, 1_100_000_000)
    metrics.record_delivery(2, 2_000_000_000, 2_300_000_000)
    metrics.record_drop(3)
    metrics.record_drop(4)

    snapshot = metrics.snapshot(3_000_000_000)
    assert snapshot.delivery_rate == 0.0
    assert snapshot.mean_latency_ms == 0.0
    assert snapshot.jitter_ms == 0.0


def test_latency_jitter_and_information_age_are_measured():
    metrics = SlidingWindowDeliveryMetrics(window_size=10)
    metrics.record_delivery(10, 1_000_000_000, 1_100_000_000)
    metrics.record_delivery(11, 2_000_000_000, 2_300_000_000)

    snapshot = metrics.snapshot(2_500_000_000)
    assert snapshot.mean_latency_ms == pytest.approx(200.0)
    assert snapshot.jitter_ms == pytest.approx(100.0)
    assert snapshot.age_of_information_ms == pytest.approx(500.0)


def test_out_of_order_delivery_is_counted_without_making_information_older():
    metrics = SlidingWindowDeliveryMetrics(window_size=10)
    metrics.record_delivery(20, 2_000_000_000, 2_100_000_000)
    metrics.record_delivery(22, 2_200_000_000, 2_300_000_000)
    metrics.record_delivery(21, 2_100_000_000, 2_400_000_000)

    snapshot = metrics.snapshot(2_500_000_000)
    assert snapshot.out_of_order_packets == 1
    assert snapshot.age_of_information_ms == pytest.approx(300.0)


def test_window_size_must_be_positive():
    with pytest.raises(ValueError):
        SlidingWindowDeliveryMetrics(window_size=0)
