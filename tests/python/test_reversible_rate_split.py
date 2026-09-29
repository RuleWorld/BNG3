"""Reversible-net-rate splitting and the ``TotalRate`` decision it feeds.

A hyphen inside an SBML id is an id character, not a difference operator, and
``standardize_name`` maps ``A-B`` and ``A_B`` to the same BNGL name.  These tests
pin the invariant that a species' source spelling cannot change the rate
semantics of its reaction: the emitted reaction rules, and the trajectory those
rules produce, must be identical for the two spellings.

The trajectory test is the acceptance criterion; the splitter tests exist to
localise a failure to the layer that caused it.
"""

from __future__ import annotations

import os
import subprocess
from collections import OrderedDict
from pathlib import Path

import pytest

from bionetgen.atomizer.modern import (
    ReversibleRateSplit,
    SBMLCompartment,
    SBMLKineticLaw,
    SBMLModel,
    SBMLParameter,
    SBMLReaction,
    SBMLSpecies,
    SBMLSpeciesReference,
    build_species_composition_table,
    generate_bngl,
    get_molecule_types,
    get_seed_species,
    split_reversible_rate,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIMULATE_ACTION = (
    '\nbegin actions\n  simulate({method=>"ode",t_end=>1,n_steps=>2})\nend actions\n'
)


# --------------------------------------------------------------------------
# The splitter's contract: split a *net* SBML flux into a positive and a
# negative law.  An arrow is not a difference, and a hyphen that belongs to a
# source id is not a difference either.
# --------------------------------------------------------------------------


def test_a_genuine_difference_between_two_laws_still_splits():
    assert split_reversible_rate("k*X - k2*Y") == ReversibleRateSplit(
        True, "k*X", "k2*Y"
    )


def test_a_difference_of_two_species_splits():
    assert split_reversible_rate("A - B") == ReversibleRateSplit(True, "A", "B")


def test_a_one_sided_law_is_not_a_net_flux():
    assert split_reversible_rate("k*X + k2*Y").success is False


@pytest.mark.parametrize("spelling", ["A-B", "k2 * A-B", "k1*A-B", "k2*A-B + kr*B"])
def test_a_hyphen_inside_a_source_id_is_not_a_difference(spelling):
    # ``parser.py`` serialises a genuine MathML ``<minus>`` with surrounding
    # spaces, so an unspaced hyphen can only be part of a source id.  The
    # splitter used to cut there and hand the caller a second law that is a
    # fragment of an id (``('k2 * A', 'B')``).
    assert split_reversible_rate(spelling).success is False


@pytest.mark.parametrize("spelling", ["A -> B", "A <-> B", "A <-> B + k*C"])
def test_an_arrow_is_not_a_difference_and_yields_no_reverse_law(spelling):
    # There is no arrow in MathML, so such a spelling is not a net flux.  The
    # old behaviour returned a reverse law of ``'> B'`` -- a rate expression
    # that means nothing.  Failing closed keeps the caller on the whole net law.
    result = split_reversible_rate(spelling)

    assert result.success is False
    assert result.reverse_rate == "0"


def test_a_hyphenated_id_does_not_shift_the_law_the_caller_looks_at():
    # The decision is made per split law, index-matched against the source law.
    # A bogus split misaligns that pairing, so the same source law is compared
    # against the wrong half of the rate.  Standardization happens at emission,
    # so the caller compares the same law for either spelling.
    hyphenated = split_reversible_rate("kf*A-B - kr*B")
    standardized = split_reversible_rate("kf*A_B - kr*B")

    assert hyphenated == ReversibleRateSplit(True, "kf*A-B", "kr*B")
    assert standardized == ReversibleRateSplit(True, "kf*A_B", "kr*B")


# --------------------------------------------------------------------------
# The emission: the same model written with either spelling.
# --------------------------------------------------------------------------


def _decay_model(species_id: str, law: str) -> SBMLModel:
    return SBMLModel(
        id="hyphen-decay",
        compartments=OrderedDict([("cell", SBMLCompartment(id="cell", size=1.0))]),
        species=OrderedDict(
            [
                (
                    species_id,
                    SBMLSpecies(
                        id=species_id,
                        compartment="cell",
                        initial_amount=10.0,
                        initial_amount_set=True,
                        has_only_substance_units=True,
                    ),
                )
            ]
        ),
        parameters=OrderedDict(
            [("k2", SBMLParameter(id="k2", value=0.3, constant=True))]
        ),
        reactions=OrderedDict(
            [
                (
                    "R2",
                    SBMLReaction(
                        id="R2",
                        reversible=False,
                        reactants=[
                            SBMLSpeciesReference(species=species_id, stoichiometry=1)
                        ],
                        products=[],
                        kinetic_law=SBMLKineticLaw(math=law.replace("%s", species_id)),
                    ),
                )
            ]
        ),
    )


def _reaction_rules(model: SBMLModel) -> str:
    sct = build_species_composition_table(model)
    bngl, _ = generate_bngl(
        model, sct, get_molecule_types(sct), get_seed_species(sct, model)
    )
    assert "begin reaction rules" in bngl, bngl
    return bngl.split("begin reaction rules")[1].split("end reaction rules")[0].strip()


# ``k2*(A-B)`` is what a MathML ``<power>``/parenthesised operand serialises to,
# ``k2*A-B`` is what a bare multiplicative ``<ci>`` operand serialises to.  The
# second is the spelling the splitter used to cut in half.
_LAWS = ("k2*(%s)", "k2*%s", "k2*(%s)^1")


@pytest.mark.parametrize("law", _LAWS)
def test_a_hyphenated_species_emits_the_same_rate_rule_as_its_standardized_spelling(
    law,
):
    hyphenated = _reaction_rules(_decay_model("A-B", law))
    standardized = _reaction_rules(_decay_model("A_B", law))

    assert hyphenated == standardized
    assert "TotalRate" not in hyphenated, hyphenated


def test_a_source_species_referenced_by_an_id_run_is_not_read_as_parameter_only():
    # The lowered law is the numeric coefficient ``0.3``; the source law says
    # the coefficient multiplies the species, so BNGL must supply the reactant
    # factor itself rather than being told the flux is complete.
    rules = _reaction_rules(_decay_model("A-B", "k2*(%s)"))

    assert rules == "R2: @cell:M_A_B() -> 0 0.3"


def test_a_hyphenated_species_keeps_its_reactant_factor_in_a_saturating_law():
    # The same test through a law whose reactant factor cannot be folded away:
    # a difference of the two spellings must not be classified differently.
    hyphenated = _reaction_rules(_decay_model("A-B", "k2*(%s)/(1+%s)"))
    standardized = _reaction_rules(_decay_model("A_B", "k2*(%s)/(1+%s)"))

    assert hyphenated == standardized


# --------------------------------------------------------------------------
# The acceptance criterion: the trajectory, not the emitted text.
# --------------------------------------------------------------------------


def _bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        _REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    if candidate.endswith(".exe") or Path(candidate).exists():
        if Path(candidate).exists():
            return candidate
    pytest.skip(f"bng_cpp not available at {candidate}")


def _simulate(tmp_path: Path, species_id: str, law: str) -> float:
    """Return the modelled amount of the species at t=1.0."""

    executable = _bng_cpp()
    model_path = tmp_path / f"{species_id}.bngl"
    sct_model = _decay_model(species_id, law)
    sct = build_species_composition_table(sct_model)
    text, _ = generate_bngl(
        sct_model, sct, get_molecule_types(sct), get_seed_species(sct, sct_model)
    )
    model_path.write_text(text.rstrip() + "\n" + _SIMULATE_ACTION)
    subprocess.run(
        [executable, model_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    gdat = tmp_path / f"{species_id}.gdat"
    assert gdat.exists(), sorted(p.name for p in tmp_path.iterdir())
    rows = [
        line.split()
        for line in gdat.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return float(rows[-1][1])


def test_the_two_spellings_integrate_to_the_same_amount(tmp_path):
    raw = _simulate(tmp_path, "A-B", "k2*(%s)")
    standardized = _simulate(tmp_path, "A_B", "k2*(%s)")

    assert raw == pytest.approx(standardized, abs=1e-9)
    # A first-order decay of an amount of 10 at k=0.3 over t=1: 10*exp(-0.3).
    assert raw == pytest.approx(10.0 * pow(2.718281828459045, -0.3), rel=1e-6)


def test_the_bare_operand_spelling_integrates_to_the_same_amount(tmp_path):
    # ``k2*A-B`` is the unparenthesised MathML form; this is the one the
    # splitter used to cut into ``('k2 * A', 'B')``.
    raw = _simulate(tmp_path, "A-B", "k2*%s")
    standardized = _simulate(tmp_path, "A_B", "k2*%s")

    assert raw == pytest.approx(standardized, abs=1e-9)
