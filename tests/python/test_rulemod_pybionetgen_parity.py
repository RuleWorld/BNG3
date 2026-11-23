"""RuleMod parity with pinned PyBioNetGen 28bf351a behaviour.

Expected values are authored from the pinned upstream source
(``bionetgen/modelapi/rulemod.py``), not from the BNG3 implementation.
"""

import pytest

from bionetgen.core.exc import BNGParseError
from bionetgen.modelapi.rulemod import RuleMod


def test_constructor_accepts_modifier_list_and_preserves_insertion_order():
    mod = RuleMod("DeleteMolecules", ["include_reactants(1,R)", "TotalRate"])
    assert mod.type == "DeleteMolecules"
    assert mod.modifiers == ["include_reactants(1,R)", "TotalRate"]
    assert str(mod) == "include_reactants(1,R) TotalRate"


def test_add_modifier_ignores_blank_and_duplicate_entries():
    mod = RuleMod()
    mod.add_modifier("  DeleteMolecules  ")
    mod.add_modifier("DeleteMolecules")
    mod.add_modifier("")
    assert mod.modifiers == ["DeleteMolecules"]
    assert str(mod) == "DeleteMolecules"
    assert repr(mod) == "Rule modifier of type None"


def test_invalid_type_raises_bngparse_error():
    with pytest.raises(BNGParseError, match="not a valid type"):
        RuleMod("NotAModifier")
