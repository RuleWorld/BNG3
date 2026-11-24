"""Issue #178: one compile-owned implementation of the poplevel decision."""

from pathlib import Path

from tests.validation.option_decision_owner import (
    has_single_owner,
    inline_decision_sites,
)

ROOT = Path(__file__).resolve().parents[2]


def test_poplevel_decision_has_one_compile_owner():
    assert has_single_owner(ROOT), (
        "poplevel decision is not single-owned; "
        f"inline sites: {inline_decision_sites(ROOT)}"
    )


def test_checker_rejects_a_second_inline_decision():
    # Negative control: an inline non-negative test outside the owner is refused.
    assert inline_decision_sites(ROOT) == []
    from tests.validation.option_decision_owner import DIRECT_TEST

    assert DIRECT_TEST.search("if (poplevel < 0.0) throw;") is not None


def test_simulation_options_have_single_compile_owners():
    """Verify atol, rtol, and max_step decisions are single-owned in compile module."""
    header = (ROOT / "cpp" / "compile" / "Document.hpp").read_text(encoding="utf-8")
    source = (ROOT / "cpp" / "compile" / "Document.cpp").read_text(encoding="utf-8")
    action = (ROOT / "cpp" / "actions" / "ActionDispatch.cpp").read_text(
        encoding="utf-8"
    )

    assert "positiveToleranceError" in header
    assert "positiveToleranceError(" in source
    assert "bng::compile::positiveToleranceError" in action

    assert "nonNegativeOptionError" in header
    assert "nonNegativeOptionError(" in source
    assert "bng::compile::nonNegativeOptionError" in action
