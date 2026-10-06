"""BNG-XML Delete operations must match BNG2's (RxnRule.pm, MolDel construction).

BNG2 deletes the whole species matching a reactant pattern only when every molecule of
that pattern is deleted and the rule lacks DeleteMolecules. Otherwise each deleted
molecule gets its own Delete, carrying the rule's DeleteMolecules flag. The expected
operations below are BNG2.pl's writeXML output for the same model.
"""

import re

from _extdep import require_extension

require_extension()
import bionetgen

MODEL = """
begin model
begin parameters
    k 1
end parameters
begin molecule types
    A(b)
    B(a,c)
    C(b)
end molecule types
begin seed species
    A(b!1).B(a!1,c) 10
    A(b!1).B(a!1,c!2).C(b!2) 10
    A(b) 10
    B(a,c) 10
end seed species
begin reaction rules
    R1: A(b!1).B(a!1) -> B(a) k
    R2: A(b!1).B(a!1) -> B(a) k DeleteMolecules
    R3: A(b) -> 0 k
    R4: A(b) + B(a,c) -> B(a,c) k
    R5: A(b!1).B(a!1,c!2).C(b!2) -> B(a,c) k
    R6: A(b!1).B(a!1,c) -> 0 k
    R7: A(b!1).B(a!1,c) -> 0 k DeleteMolecules
end reaction rules
end model
"""

# BNG2.pl writeXML on MODEL
EXPECTED = {
    "RR1": ['<Delete id="RR1_RP1_M1" DeleteMolecules="0"/>'],
    "RR2": ['<Delete id="RR2_RP1_M1" DeleteMolecules="1"/>'],
    "RR3": ['<Delete id="RR3_RP1" DeleteMolecules="0"/>'],
    "RR4": ['<Delete id="RR4_RP1" DeleteMolecules="0"/>'],
    "RR5": [
        '<Delete id="RR5_RP1_M1" DeleteMolecules="0"/>',
        '<Delete id="RR5_RP1_M3" DeleteMolecules="0"/>',
    ],
    "RR6": ['<Delete id="RR6_RP1" DeleteMolecules="0"/>'],
    "RR7": [
        '<Delete id="RR7_RP1_M1" DeleteMolecules="1"/>',
        '<Delete id="RR7_RP1_M2" DeleteMolecules="1"/>',
    ],
}


def _deletes_by_rule(xml):
    out, current = {}, None
    for line in xml.splitlines():
        m = re.search(r'<ReactionRule id="(RR\d+)"', line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current and "<Delete " in line:
            out[current].append(line.strip())
    return out


def test_delete_operations_match_bng2(tmp_path):
    path = tmp_path / "deletion.bngl"
    path.write_text(MODEL)
    deletes = _deletes_by_rule(bionetgen.load(str(path)).to_xml())
    assert deletes == EXPECTED


def test_partial_deletion_keeps_surviving_molecules(tmp_path):
    """A rule that deletes one molecule of a complex must not delete the whole pattern
    (which would remove the surviving molecules too and change the model's reactions).
    """
    path = tmp_path / "deletion.bngl"
    path.write_text(MODEL)
    deletes = _deletes_by_rule(bionetgen.load(str(path)).to_xml())
    assert '<Delete id="RR1_RP1" DeleteMolecules="0"/>' not in deletes["RR1"]
    assert '<Delete id="RR5_RP1" DeleteMolecules="0"/>' not in deletes["RR5"]
