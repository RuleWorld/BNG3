"""Focused regressions for SBML event lowering used by conversionFactor rows.

The fixture is the pinned source of official SBML Test Suite case 01000.
The assertion is a product regression: it checks exact lowering, not
acceptance answers or corpus membership.
"""

from pathlib import Path

from bionetgen.atomizer.modern import Atomizer

FIXTURE = Path(__file__).parent / "fixtures" / "sbml_01000.xml"




def test_rate_ruled_parameter_is_native_event_target_and_window_stays_scheduled():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    assert "begin bng3_events version 1" in bngl
    # A rate-ruled parameter is a native state even with a non-unit default
    # compartment, and its assignment reads the other promoted state.
    assert "assignment: k4_amt = k3_amt" in bngl
    assert "assignment: k5_amt = k4_amt" in bngl
    assert "assignment: k3_amt = k5_amt" in bngl
    # The pure clock window is exact as a scheduled action.
    assert "begin actions" in bngl
    assert "14.5" in bngl
    assert "remain untranslated" not in bngl


STOICHIOMETRY_FIXTURE = Path(__file__).parent / "fixtures" / "sbml_01398.xml"


def test_event_stoichiometry_change_transfers_the_added_amount_to_the_pool_state():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 10})
    result = atomizer.atomize(STOICHIOMETRY_FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    # The fast equilibrium holds S1 at zero; the source event's S1 write is
    # re-expressed as S2 += 5/5, and the stoichiometry parameter still changes.
    assert 'setConcentration("@default_compartment:M_S2()", "6")' in bngl
    assert 'setParameter("S1_stoichiometry", "5")' in bngl
    assert "remain untranslated" not in bngl
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning.get("severity") in {"dropped", "approximated"}
    ]


ZERO_SWITCH_FIXTURE = Path(__file__).parent / "fixtures" / "sbml_00988.xml"


def test_zero_interval_fast_coefficient_lowers_exactly():
    atomizer = Atomizer({"quietMode": True, "logLevel": "INFO", "t_end": 2})
    result = atomizer.atomize(ZERO_SWITCH_FIXTURE.read_text(encoding="utf-8"))
    assert result.success, result.error
    bngl = result.bngl
    # The fast reaction is removed; A is a rate-rule state whose production is
    # gated by the coefficient, B keeps the conserved pool, and the event that
    # turns the coefficient on also transfers A to the pool.
    assert "__rate_rule__A()" in bngl
    assert "setParameter(\"k2\", \"1\")" in bngl
    assert 'setConcentration("@comp:M_A()", "0")' in bngl
    assert "setParameter(\"k2\", \"0\")" in bngl
    assert "remain untranslated" not in bngl
    assert not [
        warning
        for warning in atomizer.model.import_warnings
        if warning.get("severity") in {"dropped", "approximated"}
    ]
