"""Seed folding must not compile regexes for symbols absent from an expression."""

from bionetgen.atomizer.modern import writer


def test_seed_folding_regex_work_depends_on_referenced_symbols(monkeypatch):
    original = writer.re.subn
    calls = 0

    def counted_substitution(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(writer.re, "subn", counted_substitution)
    symbols = {f"unreferenced_{index}": float(index) for index in range(600)}
    symbols["seed"] = 6.0

    assert writer._substitute_seed_symbols("seed() + seed", symbols) == 12.0
    # Adding unrelated model parameters must not cause a regex compilation
    # sweep over their names. This deterministic work bound avoids a flaky
    # wall-clock assertion while catching the large-model timeout mechanism.
    assert calls <= 8


def test_seed_folding_preserves_names_and_function_arguments():
    symbols = {"seed": 6.0, "seed_extra": 2.0, "e": 9.0, "time": 0.0}
    assert (
        writer._substitute_seed_symbols("seed() + seed_extra + 1e-3 + time()", symbols)
        == 8.001
    )
    assert writer._substitute_seed_symbols("unresolved + seed", symbols) is None
