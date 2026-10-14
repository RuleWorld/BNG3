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
