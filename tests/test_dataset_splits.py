import pytest

from ai_wagvid.dataset_splits import DatasetSample, Split, SplitRatios, assign_splits, find_leakage


def sample(name, athlete, event, routine, digest_character):
    return DatasetSample(name, "research", athlete, event, routine, digest_character * 64)


def test_connected_athlete_event_routine_and_hash_groups_never_split():
    samples = (
        sample("a", "athlete-1", "event-1", "routine-1", "a"),
        sample("b", "athlete-1", "event-2", "routine-2", "b"),
        sample("c", "athlete-2", "event-2", "routine-3", "c"),
        sample("d", "athlete-3", "event-3", "routine-4", "d"),
        sample("e", "athlete-4", "event-4", "routine-5", "d"),
    )
    assignments = assign_splits(samples, salt="split-policy-v1")
    assert assignments["a"] == assignments["b"] == assignments["c"]
    assert assignments["d"] == assignments["e"]
    assert find_leakage(samples, assignments) == {}


def test_assignment_is_stable_across_input_order():
    samples = (
        sample("a", "athlete-1", "event-1", "routine-1", "a"),
        sample("b", "athlete-2", "event-2", "routine-2", "b"),
    )
    assert assign_splits(samples, salt="v1") == assign_splits(tuple(reversed(samples)), salt="v1")


def test_leakage_audit_reports_manual_cross_split_assignments():
    samples = (
        sample("a", "athlete-1", "event-1", "routine-1", "a"),
        sample("b", "athlete-1", "event-2", "routine-2", "b"),
    )
    leaked = find_leakage(samples, {"a": Split.TRAIN, "b": Split.TEST})
    assert leaked["athlete:athlete-1"] == {Split.TRAIN, Split.TEST}


def test_invalid_samples_ratios_and_assignments_fail_closed():
    with pytest.raises(ValueError, match="sha256"):
        sample("a", "athlete", "event", "routine", "x")
    with pytest.raises(ValueError, match="sum"):
        SplitRatios(0.8, 0.2, 0.2)
    valid = (sample("a", "athlete", "event", "routine", "a"),)
    with pytest.raises(ValueError, match="salt"):
        assign_splits(valid, salt="")
    with pytest.raises(ValueError, match="missing"):
        find_leakage(valid, {})
