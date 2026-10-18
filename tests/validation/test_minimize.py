from tests.validation import minimize


def test_delta_debugging_preserves_predicate_and_budget():
    attempts = []

    def reproduces(items):
        attempts.append(items)
        return 3 in items and 7 in items

    kept = minimize.ddmin(list(range(10)), reproduces, max_attempts=30)
    assert kept == [3, 7]
    assert len(attempts) <= 30


def test_unreproduced_failure_cannot_be_minimized():
    import pytest

    with pytest.raises(ValueError, match="does not reproduce"):
        minimize.ddmin([1, 2], lambda items: False, max_attempts=10)


def test_reduction_requires_fresh_final_confirmation_and_reserves_attempt():
    seen = []

    def intermittent(items):
        seen.append(list(items))
        return len(seen) < 3

    result = minimize.reduce_verified([1, 2], intermittent, max_attempts=3)
    assert len(seen) == 3
    assert result["verified"] is False
    assert result["attempts"] == 3


def test_reducer_distinguishes_different_species_with_same_count_mismatch():
    from tests.validation.compare import NetDiff

    one = NetDiff(False, 1, 2, 0, 0, set(), {"A()"}, [], [])
    other = NetDiff(False, 1, 2, 0, 0, set(), {"B()"}, [], [])
    assert minimize._signature(one) != minimize._signature(other)
