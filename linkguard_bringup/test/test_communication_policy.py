import pytest

from linkguard_bringup.communication_policy import (
    LinkHealth,
    LinkState,
    PolicyConfig,
    evaluate_link_health,
)


def test_warmup_allows_commands_before_fresh_samples_arrive():
    decision = evaluate_link_health(
        LinkHealth(age_of_information_ms=10_000.0),
        PolicyConfig(),
        mission_elapsed_sec=0.5,
        metrics_age_sec=None,
    )
    assert decision.state == LinkState.GOOD


def test_good_link_uses_full_speed():
    decision = evaluate_link_health(
        LinkHealth(0.98, 25.0, 5.0, 100.0, 50),
        PolicyConfig(),
        mission_elapsed_sec=2.0,
        metrics_age_sec=0.1,
    )
    assert decision.state == LinkState.GOOD
    assert decision.speed_scale == 1.0


def test_congested_link_degrades_speed():
    decision = evaluate_link_health(
        LinkHealth(0.70, 185.0, 62.0, 250.0, 50),
        PolicyConfig(),
        mission_elapsed_sec=2.0,
        metrics_age_sec=0.1,
    )
    assert decision.state == LinkState.DEGRADED
    assert decision.speed_scale == pytest.approx(0.5)


@pytest.mark.parametrize(
    'health',
    [
        LinkHealth(0.20, 20.0, 5.0, 100.0, 50),
        LinkHealth(1.00, 700.0, 5.0, 100.0, 50),
        LinkHealth(1.00, 20.0, 5.0, 900.0, 50),
    ],
)
def test_dangerous_link_stops(health):
    decision = evaluate_link_health(
        health,
        PolicyConfig(),
        mission_elapsed_sec=2.0,
        metrics_age_sec=0.1,
    )
    assert decision.state == LinkState.STOPPED
    assert decision.speed_scale == 0.0


def test_missing_metrics_stops_after_warmup():
    decision = evaluate_link_health(
        LinkHealth(),
        PolicyConfig(),
        mission_elapsed_sec=2.0,
        metrics_age_sec=2.0,
    )
    assert decision.state == LinkState.STOPPED


def test_invalid_threshold_order_is_rejected():
    with pytest.raises(ValueError):
        PolicyConfig(
            stopped_delivery_rate=0.9,
            degraded_delivery_rate=0.8,
        ).validate()
