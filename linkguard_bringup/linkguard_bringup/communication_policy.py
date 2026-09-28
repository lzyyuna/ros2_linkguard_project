"""Pure communication-health policy used by the mission controller."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class LinkState(str, Enum):
    GOOD = 'GOOD'
    DEGRADED = 'DEGRADED'
    STOPPED = 'STOPPED'
    ABORTED = 'ABORTED'


@dataclass(frozen=True)
class LinkHealth:
    delivery_rate: float = 1.0
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    age_of_information_ms: float = 0.0
    window_sample_count: int = 0


@dataclass(frozen=True)
class PolicyConfig:
    degraded_delivery_rate: float = 0.85
    stopped_delivery_rate: float = 0.40
    degraded_latency_ms: float = 150.0
    stopped_latency_ms: float = 500.0
    degraded_jitter_ms: float = 50.0
    stopped_aoi_ms: float = 750.0
    degraded_speed_scale: float = 0.50
    metrics_min_samples: int = 10
    metrics_warmup_sec: float = 1.0
    metrics_timeout_sec: float = 1.5

    def validate(self) -> None:
        if not 0.0 <= self.stopped_delivery_rate <= self.degraded_delivery_rate <= 1.0:
            raise ValueError(
                'delivery thresholds must satisfy '
                '0 <= stopped <= degraded <= 1'
            )
        if not 0.0 < self.degraded_latency_ms < self.stopped_latency_ms:
            raise ValueError(
                'latency thresholds must satisfy 0 < degraded < stopped'
            )
        if self.degraded_jitter_ms <= 0.0:
            raise ValueError('degraded_jitter_ms must be positive')
        if self.stopped_aoi_ms <= 0.0:
            raise ValueError('stopped_aoi_ms must be positive')
        if not 0.0 < self.degraded_speed_scale <= 1.0:
            raise ValueError('degraded_speed_scale must be in (0, 1]')
        if self.metrics_min_samples <= 0:
            raise ValueError('metrics_min_samples must be positive')
        if self.metrics_warmup_sec < 0.0:
            raise ValueError('metrics_warmup_sec must be non-negative')
        if self.metrics_timeout_sec <= 0.0:
            raise ValueError('metrics_timeout_sec must be positive')


@dataclass(frozen=True)
class PolicyDecision:
    state: LinkState
    speed_scale: float
    reason: str


def evaluate_link_health(
    health: LinkHealth,
    config: PolicyConfig,
    mission_elapsed_sec: float,
    metrics_age_sec: Optional[float],
) -> PolicyDecision:
    """Classify measured communication health for an active mission."""

    config.validate()

    if mission_elapsed_sec < config.metrics_warmup_sec:
        return PolicyDecision(LinkState.GOOD, 1.0, 'collecting fresh mission samples')

    if metrics_age_sec is None or metrics_age_sec > config.metrics_timeout_sec:
        return PolicyDecision(LinkState.STOPPED, 0.0, 'network metrics timed out')

    if health.window_sample_count < config.metrics_min_samples:
        return PolicyDecision(
            LinkState.DEGRADED,
            config.degraded_speed_scale,
            'insufficient communication samples',
        )

    stopped_reasons = []
    if health.delivery_rate < config.stopped_delivery_rate:
        stopped_reasons.append(
            f'delivery {health.delivery_rate:.2f} below '
            f'{config.stopped_delivery_rate:.2f}'
        )
    if health.latency_ms > config.stopped_latency_ms:
        stopped_reasons.append(
            f'latency {health.latency_ms:.1f}ms above '
            f'{config.stopped_latency_ms:.1f}ms'
        )
    if health.age_of_information_ms > config.stopped_aoi_ms:
        stopped_reasons.append(
            f'AoI {health.age_of_information_ms:.1f}ms above '
            f'{config.stopped_aoi_ms:.1f}ms'
        )
    if stopped_reasons:
        return PolicyDecision(LinkState.STOPPED, 0.0, '; '.join(stopped_reasons))

    degraded_reasons = []
    if health.delivery_rate < config.degraded_delivery_rate:
        degraded_reasons.append(
            f'delivery {health.delivery_rate:.2f} below '
            f'{config.degraded_delivery_rate:.2f}'
        )
    if health.latency_ms > config.degraded_latency_ms:
        degraded_reasons.append(
            f'latency {health.latency_ms:.1f}ms above '
            f'{config.degraded_latency_ms:.1f}ms'
        )
    if health.jitter_ms > config.degraded_jitter_ms:
        degraded_reasons.append(
            f'jitter {health.jitter_ms:.1f}ms above '
            f'{config.degraded_jitter_ms:.1f}ms'
        )
    if degraded_reasons:
        return PolicyDecision(
            LinkState.DEGRADED,
            config.degraded_speed_scale,
            '; '.join(degraded_reasons),
        )

    return PolicyDecision(LinkState.GOOD, 1.0, 'communication healthy')
