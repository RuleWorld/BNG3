"""Source-derived contracts for the public Playground BNGL writer facade."""

from bionetgen.atomizer.modern import bnglReaction, bngl_reaction
from bionetgen.atomizer.modern.helpers import logger
from bionetgen.atomizer.modern.structures import read_from_string


def test_bngl_reaction_renders_zero_order_named_irreversible_rule():
    assert (
        bngl_reaction(
            [],
            [],
            "k0",
            {},
            reversible=False,
            reaction_name="source",
        )
        == "source: 0  -> 0  k0"
    )


def test_bngl_reaction_expands_integer_stoichiometry_and_compartment_tags():
    result = bnglReaction(
        [("A", 2, "cytosol")],
        [("B", 1, "cytosol")],
        "k1",
        {"cytosol": "@cell"},
        is_compartments=True,
        reversible=False,
        comment="# source",
        reaction_name="r1",
    )

    assert result == "r1: A@cell + A@cell -> B@cell k1 # source"


def test_bngl_reaction_uses_translated_patterns_and_renumbers_bonds():
    translator = {
        "A": read_from_string("A(site!7).B(site!7)"),
        "C": read_from_string("C()"),
    }

    result = bngl_reaction(
        [("A", 1, "cytosol")],
        [("C", 1, "cytosol")],
        "k1",
        {"cytosol": "cell"},
        translator=translator,
        is_compartments=True,
        reversible=True,
    )

    assert result == "A(site!1)@cell.B(site!1)@cell <-> C@cell k1"


def test_bngl_reaction_reports_fractional_stoichiometry_and_keeps_one_term():
    logger.clear()
    result = bngl_reaction(
        [("A", 0.5, "")],
        [("B", 1, "")],
        "k1",
        {},
        reversible=False,
    )

    assert result == "A -> B k1"
    assert any(
        message.code == "BNW002" and "Non-integer stoichiometry" in message.message
        for message in logger.getMessages()
    )
    logger.clear()
