"""Sequence-gap accounting for the publisher-to-emulator DDS hop."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class SequenceObservation:
    accepted: bool
    missing_sequences: List[int] = field(default_factory=list)
    source_restarted: bool = False


class SequenceGapTracker:
    """Infer missing packets from one monotonically increasing publisher."""

    def __init__(self) -> None:
        self._highest_sequence = -1
        self.transport_dropped_packets = 0

    def observe(self, sequence: int) -> SequenceObservation:
        if sequence < 0:
            raise ValueError('sequence must be non-negative')
        if sequence == 0 and self._highest_sequence > 0:
            # The command publisher was restarted while this node stayed alive.
            # Start a new sequence epoch instead of rejecting every new command.
            self._highest_sequence = 0
            return SequenceObservation(accepted=True, source_restarted=True)
        if sequence <= self._highest_sequence:
            return SequenceObservation(accepted=False)

        missing = list(range(self._highest_sequence + 1, sequence))
        self.transport_dropped_packets += len(missing)
        self._highest_sequence = sequence
        return SequenceObservation(accepted=True, missing_sequences=missing)
