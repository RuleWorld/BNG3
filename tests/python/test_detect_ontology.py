from bionetgen.atomizer.atomizer.detectOntology import levenshtein


def test_levenshtein_empty_strings():
    assert levenshtein("", "") == 0


def test_levenshtein_identical_strings():
    assert levenshtein("a", "a") == 0
    assert levenshtein("abc", "abc") == 0


def test_levenshtein_one_empty_string():
    assert levenshtein("", "a") == 1
    assert levenshtein("a", "") == 1
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "") == 3


def test_levenshtein_different_strings():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("flaw", "lawn") == 2
    assert levenshtein("abc", "bca") == 2
    assert levenshtein("book", "back") == 2
