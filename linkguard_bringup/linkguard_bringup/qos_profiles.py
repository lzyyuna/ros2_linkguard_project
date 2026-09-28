"""Explicit QoS profiles shared by the LinkGuard nodes."""

from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)


def _reliability(name: str) -> QoSReliabilityPolicy:
    normalized = name.strip().lower()
    if normalized == 'reliable':
        return QoSReliabilityPolicy.RELIABLE
    if normalized in ('best_effort', 'besteffort'):
        return QoSReliabilityPolicy.BEST_EFFORT
    raise ValueError('QoS reliability must be reliable or best_effort')


def command_qos(reliability: str = 'reliable', depth: int = 10) -> QoSProfile:
    if depth <= 0:
        raise ValueError('QoS depth must be positive')
    return QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=_reliability(reliability),
        durability=QoSDurabilityPolicy.VOLATILE,
    )


def telemetry_qos(depth: int = 10) -> QoSProfile:
    if depth <= 0:
        raise ValueError('QoS depth must be positive')
    return QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        durability=QoSDurabilityPolicy.VOLATILE,
    )


def reliable_qos(depth: int = 10) -> QoSProfile:
    return command_qos('reliable', depth)


def state_qos() -> QoSProfile:
    return QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    )
