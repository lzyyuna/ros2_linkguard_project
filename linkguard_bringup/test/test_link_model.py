import statistics

import pytest

from linkguard_bringup.link_model import LinkConfig, LinkModel, PROFILES


def test_invalid_drop_rate_is_rejected():
    with pytest.raises(ValueError):
        LinkConfig(10.0, 1.0, 1.1).validate()


def test_disconnected_profile_drops_every_packet():
    model = LinkModel(PROFILES['disconnected'])
    assert all(model.should_drop() for _ in range(100))


def test_sampled_delay_is_non_negative():
    model = LinkModel(LinkConfig(5.0, 100.0, 0.0))
    assert all(model.sample_delay_sec() >= 0.0 for _ in range(1000))


def test_delay_mean_is_close_to_configuration():
    model = LinkModel(LinkConfig(100.0, 10.0, 0.0), seed=42)
    delays_ms = [model.sample_delay_sec() * 1000.0 for _ in range(5000)]
    assert statistics.mean(delays_ms) == pytest.approx(100.0, abs=1.0)
