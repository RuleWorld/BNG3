import pyparsing as pp
from bionetgen.modelapi.pattern_reader import BNGPatternReader


def test_pattern_reader_accepts_repeated_component_separators():
    pat_str = "A(x,,y)"
    r = BNGPatternReader(pat_str)
    assert str(r.pattern) == "A(x,y)"
    assert len(r.pattern.molecules[0].components) == 2
    assert r.pattern.molecules[0].components[0].name == "x"
    assert r.pattern.molecules[0].components[1].name == "y"


def test_pattern_reader_without_delimited_list_class(monkeypatch):
    # pyparsing 3.0.9 exposes the function but not the later public class.
    monkeypatch.delattr(pp, "DelimitedList", raising=False)
    monkeypatch.setattr(BNGPatternReader, "_shared_parsers", None)
    pattern = BNGPatternReader("A(x,,y).B(z)").pattern
    assert str(pattern) == "A(x,y).B(z)"
