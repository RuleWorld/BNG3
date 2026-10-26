from unittest.mock import patch

from bionetgen.atomizer.atomizer.analyzeSBML import SBMLAnalyzer, get_close_matches


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


def _state_free_analyzer():
    """The methods below only use their arguments, not instance state."""
    return SBMLAnalyzer.__new__(SBMLAnalyzer)


def test_approximate_matching_keeps_its_difference_parameter_unchanged():
    analyzer = _state_free_analyzer()
    differences = ["_p"]
    reactants = ["A_p"]
    reaction = [reactants, ["A"]]

    analyzer.approximateMatching(reaction, differences)

    assert differences == ["_p"]
    assert reactants == ["A_p"]


def test_remove_exact_matches_decrements_each_side_independently():
    analyzer = _state_free_analyzer()
    reactant_list = [["A", "B"]]
    product_list = [["A", "C"]]

    new_reactants, new_products = analyzer.removeExactMatches(
        reactant_list, product_list
    )

    assert new_reactants == [["B"]]
    assert new_products == [["C"]]
    assert reactant_list == [["A", "B"]]
    assert product_list == [["A", "C"]]
