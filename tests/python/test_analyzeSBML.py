from bionetgen.atomizer.atomizer.analyzeSBML import get_close_matches
from unittest.mock import patch


def test_get_close_matches_basic():
    """Test basic fuzzy matching functionality."""
    dataset = ["apple", "ape", "application", "banana"]
    matches = get_close_matches("appel", dataset)
    assert "apple" in matches


def test_get_close_matches_cutoff():
    """Test that cutoff parameter works correctly."""
    dataset = ["apple", "ape", "application", "banana"]
    # With low cutoff, both should match
    matches = get_close_matches("app", dataset, cutoff=0.3)
    assert "apple" in matches
    assert "ape" in matches

    # With high cutoff, fewer or no matches should be returned
    matches_strict = get_close_matches("app", dataset, cutoff=0.8)
    assert "ape" not in matches_strict


def test_get_close_matches_no_match():
    """Test behavior when no matches are close enough."""
    dataset = ["apple", "ape", "application", "banana"]
    matches = get_close_matches("xyz", dataset)
    assert matches == []


def test_get_close_matches_empty_dataset():
    """Test behavior with an empty dataset."""
    matches = get_close_matches("apple", [])
    assert matches == []


def test_get_close_matches_exact_match():
    """Test that an exact match is returned."""
    dataset = ["apple", "banana", "orange"]
    matches = get_close_matches("banana", dataset)
    assert matches[0] == "banana"


@patch("difflib.get_close_matches")
def test_get_close_matches_caching(mock_difflib):
    """Test that the @memoize decorator works as expected."""
    mock_difflib.return_value = ["apple"]
    dataset = ["apple", "banana"]
    # Clear cache before test if possible, or just use a unique input
    unique_str = "appl_unique_test_123"

    # The first call should hit difflib
    matches1 = get_close_matches(unique_str, dataset)

    # The second call should return the cached result
    matches2 = get_close_matches(unique_str, dataset)

    assert matches1 == matches2 == ["apple"]
    # verify difflib was only called once
    mock_difflib.assert_called_once()
