"""Pin the identifier character classes the Atomizer relies on.

The whole-id class exists for one reason: `parser.py` serialises a genuine
MathML ``<minus>`` with surrounding spaces, so an *unspaced* hyphen can only be a
character inside an SBML id. Every id-run scan is defined by that class, and two
separate bugs this session — a fabricated event delay and a wrong ``TotalRate``
that changed a trajectory — were both a site reading text with a class narrower
than the one the producer used.

The class is currently typed out in three places, because `writer.py` imports
`events` at module scope and `events` therefore cannot import `writer` back. That
makes the agreement between them a property of a comment rather than of a test,
which is how the two copies drifted apart in the first place. These assertions
are what turns the comment into a guarantee.

Two classes are deliberately different and must not be unified:

- the *tolerant* whole-id class, used to scan text that still holds raw ids;
- the *strict* SId class, used where a name must be looked up and echoed, and
  for validating SBML Multi attributes, where SBML genuinely forbids a hyphen.

Unifying them would either start accepting ``-`` in a Multi attribute or stop
recognising a legitimate hyphenated id. These tests assert both classes exist,
that they differ, and that every copy of the tolerant one agrees.
"""

import re

import pytest

from bionetgen.atomizer.modern import events as ev
from bionetgen.atomizer.modern import writer as w
from bionetgen.atomizer.modern import types as ty

TOLERANT = r"[A-Za-z_][A-Za-z0-9_-]*"
STRICT = r"[A-Za-z_][A-Za-z0-9_]*"


def test_tolerant_class_has_one_canonical_definition():
    assert w._SBML_ID_RUN.pattern == TOLERANT


def test_events_tokenizer_copies_agree_with_the_canonical_class():
    # events.py cannot import writer at module scope -- writer imports events --
    # so the class is re-typed. It must still be the same class.
    assert ev._SBML_ID_TOKEN.pattern == TOLERANT
    # ...and inlined a second time inside the tokenizer's own alternation,
    # where it appears as one alternative among the number/operator branches.
    assert TOLERANT in ev._TOKEN.pattern


def test_strict_sid_class_is_deliberately_narrower():
    # Used where a name must be looked up and echoed. Unifying this with the
    # tolerant class would stop recognising a legitimate hyphenated id.
    assert ev._SBML_SID_TOKEN.pattern == STRICT
    assert ev._SBML_SID_TOKEN.pattern != ev._SBML_ID_TOKEN.pattern
    # The strict class must reject a hyphenated id; the tolerant one must not.
    assert ev._SBML_SID_TOKEN.fullmatch("A-B") is None
    assert ev._SBML_ID_TOKEN.fullmatch("A-B") is not None


def test_spaced_minus_is_not_an_id_character():
    # The invariant the tolerant class depends on. If this ever changes, the
    # class can no longer be widened safely: a spaced hyphen is the operator.
    assert ev._SBML_ID_TOKEN.fullmatch("A - B") is None
    assert ev._SBML_ID_TOKEN.findall("A - B") == ["A", "B"]
    assert ev._SBML_ID_TOKEN.findall("A-B") == ["A-B"]


def test_standardize_name_is_the_single_spelling_authority():
    # Every emitted name goes through this. `A*B` and `AmB` are the same name
    # reached two ways, which is a documented hazard rather than a coincidence.
    assert ty.standardize_name("A-B") == "A_B"
    assert ty.standardize_name("A_B") == "A_B"
    assert ty.standardize_name("A*B") == ty.standardize_name("AmB")
    assert ty.standardize_name("A.B") == "A_B"


@pytest.mark.parametrize("identifier", ["A-B", "A_B", "AB", "_x1", "a-1"])
def test_identifier_run_scan_is_whole_id_not_fragment(identifier):
    # The failure mode both bugs shared: a scan that stops at the hyphen yields
    # fragments, and the caller then resolves the wrong thing.
    assert w._id_runs(identifier) == {identifier}
    assert w._id_runs(f"k * {identifier}") == {"k", identifier}
    assert w._id_runs("k * A - B") == {"k", "A", "B"}
