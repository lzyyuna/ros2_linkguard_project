from linkguard_bringup.sequence_tracker import SequenceGapTracker


def test_contiguous_sequences_have_no_gaps():
    tracker = SequenceGapTracker()
    assert tracker.observe(0).missing_sequences == []
    assert tracker.observe(1).missing_sequences == []
    assert tracker.transport_dropped_packets == 0


def test_missing_sequences_are_reported_once():
    tracker = SequenceGapTracker()
    tracker.observe(0)
    observation = tracker.observe(3)
    assert observation.missing_sequences == [1, 2]
    assert tracker.transport_dropped_packets == 2


def test_duplicate_or_late_sequence_is_rejected():
    tracker = SequenceGapTracker()
    tracker.observe(2)
    observation = tracker.observe(1)
    assert not observation.accepted


def test_zero_starts_a_new_publisher_epoch():
    tracker = SequenceGapTracker()
    tracker.observe(10)
    observation = tracker.observe(0)
    assert observation.accepted
    assert observation.source_restarted
    assert tracker.observe(1).accepted


def test_negative_sequence_is_rejected():
    tracker = SequenceGapTracker()
    try:
        tracker.observe(-1)
    except ValueError:
        return
    raise AssertionError('negative sequence was accepted')
