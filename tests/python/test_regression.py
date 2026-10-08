import pytest
from bionetgen.modelapi.pattern_reader import BNGPatternReader


def test_pattern_reader_accepts_repeated_component_separators():
    pat_str = "A(x,,y)"
    r = BNGPatternReader(pat_str)
    assert str(r.pattern) == "A(x,y)"
    assert len(r.pattern.molecules[0].components) == 2
    assert r.pattern.molecules[0].components[0].name == "x"
    assert r.pattern.molecules[0].components[1].name == "y"
