"""ROS-independent network model logic, kept separate for fast unit tests."""

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class LinkConfig:
    latency_ms: float
    jitter_ms: float
    drop_rate: float

    def validate(self) -> None:
        if not 0.0 <= self.latency_ms <= 10_000.0:
            raise ValueError('latency_ms must be in [0, 10000]')
        if not 0.0 <= self.jitter_ms <= 10_000.0:
            raise ValueError('jitter_ms must be in [0, 10000]')
        if not 0.0 <= self.drop_rate <= 1.0:
            raise ValueError('drop_rate must be in [0, 1]')


PROFILES = {
    'good': LinkConfig(20.0, 5.0, 0.0),
    'congested': LinkConfig(180.0, 60.0, 0.25),
    'disconnected': LinkConfig(0.0, 0.0, 1.0),
}


class LinkModel:
    def __init__(self, config: LinkConfig, seed: int = 7) -> None:
        config.validate()
        self.config = config
        self._rng = random.Random(seed)

    def should_drop(self) -> bool:
        return self._rng.random() < self.config.drop_rate

    def sample_delay_sec(self) -> float:
        delay_ms = self._rng.gauss(self.config.latency_ms, self.config.jitter_ms)
        return max(0.0, delay_ms) / 1000.0

    def reconfigure(self, config: LinkConfig) -> None:
        config.validate()
        self.config = config
