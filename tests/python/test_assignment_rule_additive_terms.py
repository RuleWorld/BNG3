"""An assignment-rule body is a sum; every term of it must reach the model.

SBML Level 3 Version 1 section 4.11.1 defines an ``assignmentRule`` as an
identity that holds at every time point, so every expression that reads the
rule's ``variable`` must see the whole right-hand side.  The Atomizer lowers a
*bare additive* rule body -- one with no ``/ ^ ( )`` anywhere -- to a BNGL
``Molecules`` observable, because a weighted sum of species patterns is exactly
what such an observable computes.  That lowering is only lossless when every
``+`` term is an imported species with an integer coefficient.

Two term classes broke that precondition and were discarded instead of
abandoning the lowering:

* a bare numeric term (``p = A + 2``) was skipped, so the model claimed ``p``
  was ``A``;
* two terms naming the same species were merged with ``max`` rather than
  summed (``p = A + A`` became ``p = A``).

Both are silent: ``Atomizer.atomize`` returned ``success=True`` and emitted no
diagnostic, and the resulting BNGL is syntactically valid, so the loss is only
visible in a trajectory.  For ``p = A + 2`` driving a reaction, BNG3 integrated
``dA/dt = -A`` to ``A(1) = 3.678794247910`` where SBML requires
``dA/dt = -(A + 2)`` and therefore ``A(1) = 8*exp(-1) + 2 = 4.943035529372``.

The fix is to decline the observable lowering when a term is not accounted for,
which routes the rule to ``write_functions``.  That path is already correct and
already exercised: ``p = A/2`` contains parentheses, skips this branch, and is
emitted as ``p() = A / 2``.

The trajectory tests are the acceptance criterion, per the rule that a claim
about emitted text is a claim about code, not about behaviour.
"""

from __future__ import annotations

import os
import subprocess
from collections import OrderedDict
from pathlib import Path

import pytest

from bionetgen.atomizer.modern import (
    SBMLCompartment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLRule,
    SBMLSpecies,
    SBMLSpeciesReference,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIMULATE_ACTION = (
    '\nbegin actions\n  simulate({method=>"ode",t_start=>0,t_end=>1,n_steps=>10})\n'
    "end actions\n"
)
_E = 2.718281828459045


def _model(rule_math: str) -> SBMLModel:
    """One species ``A`` (10), one non-constant parameter ``p``, and ``A -> 0``.

    The reaction's kinetic law reads ``p``, so the assignment rule is on the
    trajectory rather than only in an observable nobody consumes.
    """

    return SBMLModel(
        id="assign-additive",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1.0))]),
        species=OrderedDict(
            [
                (
                    "A",
                    SBMLSpecies(
                        id="A",
                        compartment="cell",
                        initial_amount=10.0,
                        initial_amount_set=True,
                        has_only_substance_units=True,
                    ),
                )
            ]
        ),
        parameters=OrderedDict(
            [("p", SBMLParameter(id="p", value=1.0, constant=False))]
        ),
        rules=[
            SBMLRule(type="assignment", variable="p", math=rule_math),
        ],
        reactions=OrderedDict(
            [
                (
                    "R1",
                    SBMLReaction(
                        id="R1",
                        reversible=False,
                        reactants=[SBMLSpeciesReference(species="A", stoichiometry=1)],
                        products=[],
                        kinetic_law=SBMLKineticLaw(math="p"),
                    ),
                )
            ]
        ),
    )


def _emit(rule_math: str) -> str:
    model = _model(rule_math)
    sct = build_species_composition_table(model)
    text, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    return text


def _molecules_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("Molecules ")
    ]


# --------------------------------------------------------------------------
# The emission: no observable may claim to be the rule target while dropping a
# term of the rule body.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_math",
    [
        "A + 2",  # a bare numeric term
        "2 + A",  # the same term before the species
        "A + 2.5",  # a fractional term
        "A + B + 2",
    ],
)
def test_a_rule_body_with_a_numeric_term_emits_no_observable_for_it(rule_math):
    # ``Molecules p <pattern>`` states that the model's ``p`` *is* that sum of
    # species.  A numeric term contributes no pattern, so if it was dropped the
    # observable is a different function of the state than the rule declares;
    # the lowering must be declined and the rule routed to the functions block,
    # which can carry the constant.
    text = _emit(rule_math)
    for line in _molecules_lines(text):
        assert not line.startswith("Molecules p"), text
    assert "p()" in text, text


def test_a_repeated_species_term_is_summed_not_maximised():
    # ``p = A + A`` is two A.  A ``Molecules`` pattern spells a repeated species
    # as repeated pattern components, and ``max`` used to collapse the two
    # terms to one, halving the observable.
    lines = [
        line
        for line in _molecules_lines(_emit("A + A"))
        if line.startswith("Molecules p ")
    ]
    assert lines, _emit("A + A")
    assert all(line.count("@cell:M_A()") == 2 for line in lines), lines


def test_a_purely_additive_species_sum_still_uses_the_observable_lowering():
    # The lowering is valid when it is lossless, so it must be kept: this is the
    # case the code was written for, and `p = 2*A` was verified against the
    # closed form by `test_a_weighted_species_sum_integrates_to_twice_the_decay`.
    lines = _molecules_lines(_emit("2*A"))
    assert any(line.startswith("Molecules p ") for line in lines), lines


def test_a_single_species_rule_keeps_its_observable():
    lines = _molecules_lines(_emit("A"))
    assert any(line.startswith("Molecules p ") for line in lines), lines


# --------------------------------------------------------------------------
# The acceptance criterion: the trajectory.
# --------------------------------------------------------------------------


def _bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        _REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    if Path(candidate).exists():
        return candidate
    pytest.skip(f"bng_cpp not available at {candidate}")


def _amount_at_one(rule_math: str, tmp_path: Path) -> float:
    executable = _bng_cpp()
    model_path = tmp_path / "m.bngl"
    model_path.write_text(_emit(rule_math).rstrip() + "\n" + _SIMULATE_ACTION)
    subprocess.run(
        [executable, model_path.name], cwd=tmp_path, check=True, capture_output=True
    )
    gdat = tmp_path / "m.gdat"
    assert gdat.exists(), sorted(p.name for p in tmp_path.iterdir())
    rows = [
        line.split()
        for line in gdat.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return float(rows[-1][1])


def test_an_additive_constant_reaches_the_trajectory(tmp_path):
    # SBML: dA/dt = -(A + 2) with A(0) = 10.  Its solution is
    # A(t) + 2 = 12*exp(-t), so A(1) = 12*exp(-1) - 2.
    amount = _amount_at_one("A + 2", tmp_path)
    assert amount == pytest.approx(12.0 * pow(_E, -1) - 2.0, rel=1e-6), amount


def test_a_repeated_species_term_reaches_the_trajectory(tmp_path):
    # SBML: dA/dt = -(A + A) = -2A  =>  A(1) = 10*exp(-2).
    amount = _amount_at_one("A + A", tmp_path)
    assert amount == pytest.approx(10.0 * pow(_E, -2.0), rel=1e-6), amount


def test_a_weighted_species_sum_integrates_to_twice_the_decay(tmp_path):
    # The already-correct case, kept as the control: p = 2*A, dA/dt = -2A.
    amount = _amount_at_one("2*A", tmp_path)
    assert amount == pytest.approx(10.0 * pow(_E, -2.0), rel=1e-6), amount


def test_a_division_body_integrates_to_the_half_decay(tmp_path):
    # p = A/2 has always reached ``write_functions``; this is the path the
    # fixed cases now take as well, so it is pinned as their reference.
    amount = _amount_at_one("A/2", tmp_path)
    assert amount == pytest.approx(10.0 * pow(_E, -0.5), rel=1e-6), amount
