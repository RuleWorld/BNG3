"""The SBML specification references the Atomizer and its records make.

The Atomizer's diagnostics, its code comments, the campaign's documents and
the campaign's provenance data all name sections of the SBML specification.
A reader takes such a name at its word, so a name that points at the wrong
section is a false statement about the language, not a typo.

This module checks those names against the SBML Level 3 Version 2 Core
outline.  The outline below is derived from the specification's own LaTeX
source -- chapter 3, "Preliminary definitions and principles", and chapter 4,
"SBML components" -- not from memory and not from the citations being
checked.  Two properties are checked:

* every section number the repository cites is a section of that document;
* a citation that names a section's title names *that* section's title.

The level-dependent rule is checked separately, because a diagnostic that
depends on the document's level has to name the rule of that document's own
level: the ``fast`` attribute exists in Level 2 and Level 3 Version 1 and was
removed in Level 3 Version 2, so the diagnostic names a different section for
each.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
THIS_MODULE = Path(__file__).resolve()

# ---------------------------------------------------------------------------
# The SBML Level 3 Version 2 Core outline, derived from the specification's
# LaTeX source (the campaign's checkout of the specification has
# ``preliminary.tex`` for chapter 3 and ``components.tex`` for chapter 4).
# Chapter 3 is "Preliminary definitions and principles" and chapter 4 is
# "SBML components".
# ---------------------------------------------------------------------------
SBML_L3V2_SECTIONS: dict[str, str] = {
    "3.1": "Primitive data types",
    "3.1.1": "Type string",
    "3.1.2": "Type boolean",
    "3.1.3": "Type int",
    "3.1.4": "Type positiveInteger",
    "3.1.5": "Type double",
    "3.1.6": "Type ID",
    "3.1.7": "Type SId",
    "3.1.8": "Type SIdRef",
    "3.1.9": "Type UnitSId",
    "3.1.10": "Type UnitSIdRef",
    "3.1.11": "Type LocalSId",
    "3.1.12": "Type SBOTerm",
    "3.2": "Type SBase",
    "3.2.1": "The id attribute",
    "3.2.2": "The name attribute",
    "3.2.3": "The metaid attribute",
    "3.2.4": "The sboTerm attribute",
    "3.2.5": "Notes",
    "3.2.6": "Annotation",
    "3.3": "The id and name attributes on SBase",
    "3.3.1": "The id attribute and identifier scoping",
    "3.3.2": "Motivations for defining id and name on SBase",
    "3.3.3": (
        "Use of SBML Level 3 Version 1 packages and implications for identifiers"
    ),
    "3.4": "Mathematical formulas in SBML Level 3",
    "3.4.1": "Subset of MathML used in SBML Level 3 Core",
    "3.4.2": "Numbers and cn elements",
    "3.4.3": "Use of ci elements in MathML expressions in SBML",
    "3.4.4": "Interpretation of boolean values",
    "3.4.5": "Handling of whitespace",
    "3.4.6": "Use of csymbol elements in MathML expressions in SBML",
    "3.4.7": "Simulation time",
    "3.4.8": "Initial conditions and special considerations",
    "3.4.9": "Underdetermined models",
    "3.4.10": "Use and interpretation of the 'constant' attribute",
    "3.4.11": "MathML expression data types",
    "3.4.12": (
        "Consistency of units in mathematical expressions and treatment of "
        "unspecified units"
    ),
    "3.4.13": "SBML does not define implicit unit conversions",
    "4.1": "The SBML container",
    "4.1.1": "The id and name attributes",
    "4.1.2": "The model element",
    "4.1.3": "Package declarations",
    "4.2": "Model",
    "4.2.1": "The sboTerm attribute",
    "4.2.2": "The substanceUnits attribute",
    "4.2.3": "The timeUnits attribute",
    "4.2.4": "The volumeUnits, areaUnits and lengthUnits attributes",
    "4.2.5": "The extentUnits attribute",
    "4.2.6": "The conversionFactor attribute",
    "4.2.7": "The ListOf container classes",
    "4.3": "Function definitions",
    "4.3.1": "The id attribute",
    "4.3.2": "The math element",
    "4.3.3": "The sboTerm attribute",
    "4.3.4": "Calling user-defined functions",
    "4.3.5": "Examples",
    "4.4": "Unit definitions",
    "4.4.1": "UnitDefinition",
    "4.4.2": "Unit",
    "4.4.3": "Semantics of Unit and UnitDefinition",
    "4.4.4": "Use of units in a model",
    "4.5": "Compartments",
    "4.5.1": "The id attribute",
    "4.5.2": "The spatialDimensions attribute",
    "4.5.3": "The size attribute",
    "4.5.4": "The units attribute",
    "4.5.5": "The constant attribute",
    "4.5.6": "The sboTerm attribute",
    "4.5.7": "Examples",
    "4.6": "Species",
    "4.6.1": "The id attribute",
    "4.6.2": "The sboTerm attribute",
    "4.6.3": "The compartment attribute",
    "4.6.4": ("The initialAmount, initialConcentration, and substanceUnits attributes"),
    "4.6.5": "The hasOnlySubstanceUnits attribute",
    "4.6.6": "The constant and boundaryCondition attributes",
    "4.6.7": "The conversionFactor attribute",
    "4.6.8": (
        "Additional considerations for interpreting the numerical value of a " "species"
    ),
    "4.6.9": "Example",
    "4.7": "Parameters",
    "4.7.1": "The id attribute",
    "4.7.2": "The value attribute",
    "4.7.3": "The units attribute",
    "4.7.4": "The constant attribute",
    "4.7.5": "The sboTerm attribute",
    "4.7.6": "Example",
    "4.8": "Initial assignments",
    "4.8.1": "The id attribute",
    "4.8.2": "The symbol attribute",
    "4.8.3": "The math element",
    "4.8.4": "The sboTerm attribute",
    "4.8.5": "Semantics of initial assignments",
    "4.8.6": "Example",
    "4.9": "Rules",
    "4.9.1": "Common attributes in Rule",
    "4.9.2": "AlgebraicRule",
    "4.9.3": "AssignmentRule",
    "4.9.4": "RateRule",
    "4.9.5": "Additional restrictions on rules",
    "4.9.6": "Example of rule use",
    "4.10": "Constraints",
    "4.10.1": "The math element",
    "4.10.2": "Message",
    "4.10.3": "Semantics of constraints",
    "4.10.4": "Example",
    "4.11": "Reactions",
    "4.11.1": "Reaction",
    "4.11.2": "SimpleSpeciesReference",
    "4.11.3": "SpeciesReference",
    "4.11.4": "ModifierSpeciesReference",
    "4.11.5": "KineticLaw",
    "4.11.6": "LocalParameter",
    "4.11.7": "Mathematical interpretation of SBML reactions and kinetic laws",
    "4.11.8": "Use of reaction identifiers in mathematical expressions",
    "4.12": "Events",
    "4.12.1": "Event",
    "4.12.2": "Trigger",
    "4.12.3": "Priority",
    "4.12.4": "Delay",
    "4.12.5": "EventAssignment",
    "4.12.6": "Example Event definitions",
    "4.12.7": "Detailed semantics of events",
}

# The files whose SBML references are part of the product or of the
# campaign's records: the Atomizer, the native SBML reader and writer, the
# native event runtime, the harness, the campaign's documents and its
# provenance data, and the tests that pin the behaviour those references
# describe.
SCANNED_FILES = (
    "python/bionetgen/atomizer/modern/parser.py",
    "python/bionetgen/atomizer/modern/writer.py",
    "python/bionetgen/atomizer/modern/events.py",
    "python/bionetgen/atomizer/modern/fast_reactions.py",
    "python/bionetgen/atomizer/modern/structures.py",
    "python/bionetgen/atomizer/modern/core.py",
    "python/bionetgen/atomizer/modern/math_builtins.py",
    "cpp/io/SbmlReader.cpp",
    "cpp/io/SbmlWriter.cpp",
    "cpp/ast/EventSupport.hpp",
    "cpp/engine/OdeIntegrator.cpp",
    "cpp/engine/OdeIntegrator.hpp",
    "scripts/ci/validate_sbml_test_suite.py",
    "docs/ATOMIZER_LIMITATIONS.md",
    "docs/SBML_CONFORMANCE_FINDINGS.md",
    "docs/CURATED_BIOMODELS_CORPUS.md",
    "docs/SBML_ATOMIZER_COVERAGE_CAMPAIGN.md",
    "provenance/sbml-campaign/atomizer-limitations.json",
)

# A section number a citation names, on its own or with a title.
_CITATION = re.compile(
    r"(?:Sec(?:tion)?\.?\s+|§\s*)(?P<number>\d+(?:\.\d+){1,2})(?![0-9.])"
)

# A citation that names a title: a quoted title, a Markdown italic one or a
# reStructuredText literal one.  Only these are checked against the outline;
# a citation that follows its number with prose (``Sec. 4.9.1: a Rule with no
# math ...``) names no title and is covered by the corrected-citation test
# below.
_CITATION_WITH_TITLE = re.compile(
    r"(?:Sec(?:tion)?\.?\s+|§\s*)(?P<number>\d+(?:\.\d+){1,2})(?![0-9.])"
    r"\s*[,(]?\s*(?:"
    r"[\"“](?P<quoted>[^\"”()]{3,120})[\"”]"
    r"|\*(?P<italic>[^*()]{3,120})\*"
    r"|``(?P<literal>[^`()]{3,120})``"
    r")"
)

# The Level 2 specification's own numbering: Level 2 Version 2 added
# Compartment types and Species types, which moved Reactions from Section
# 4.11 to Section 4.13.  (Level 2 Version 1 numbered Reactions Section 4.9,
# a section number Level 3 also uses, for "Rules".)
_LEVEL_TWO_SECTIONS = {"4.11", "4.13"}


def _normalized(text: str) -> str:
    """Return ``text`` with its punctuation and spacing removed."""

    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _scanned_files() -> list[Path]:
    """Return every file whose SBML references are checked."""

    paths = [REPO / relative for relative in SCANNED_FILES]
    for pattern in ("tests/python/*.py", "tests/cpp/*.cpp"):
        paths.extend(sorted(REPO.glob(pattern)))
    return [path for path in paths if path.resolve() != THIS_MODULE]


def _iter_citations():
    """Yield ``(path, line, number, title)`` for every citation in the tree."""

    for path in _scanned_files():
        text = path.read_text(encoding="utf-8")
        for match in _CITATION_WITH_TITLE.finditer(text):
            title = (
                match.group("quoted")
                or match.group("italic")
                or match.group("literal")
                or ""
            )
            line = text.count("\n", 0, match.start()) + 1
            yield path, line, match.group("number"), title
        for match in _CITATION.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield path, line, match.group("number"), ""


def _is_level_two_citation(path: Path, line: int, number: str) -> bool:
    """Whether a citation names a section of the Level 2 specification.

    A diagnostic that depends on the document's level names the rule of that
    document's own level, so a citation that says "Level 2" may use a Level 2
    section number.
    """

    if number not in _LEVEL_TWO_SECTIONS:
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[max(0, line - 3) : line + 2])
    return "Level 2" in window


def test_every_cited_section_exists_in_the_specification():
    """No citation may name a section the document does not have."""

    unknown = [
        (str(path.relative_to(REPO)), line, number)
        for path, line, number, _ in _iter_citations()
        if number not in SBML_L3V2_SECTIONS
        and not _is_level_two_citation(path, line, number)
    ]
    assert not unknown, (
        "these citations name a section that SBML Level 3 Version 2 Core "
        f"does not have: {unknown}"
    )


def test_a_cited_title_matches_the_section_it_names():
    """A citation that names a title has to name that section's title."""

    wrong = []
    for path, line, number, title in _iter_citations():
        if not title:
            continue
        expected = SBML_L3V2_SECTIONS.get(number)
        if expected is None:
            continue
        expected_key = _normalized(expected)
        title_key = _normalized(title)
        if expected_key not in title_key and title_key not in expected_key:
            wrong.append(
                (
                    str(path.relative_to(REPO)),
                    line,
                    number,
                    title,
                    expected,
                )
            )
    assert not wrong, (
        "these citations name a title that is not the title of the section "
        f"they cite: {wrong}"
    )


def test_the_corrected_citations_name_the_right_sections():
    """The corrections this campaign made must not be undone silently."""

    expected = {
        "python/bionetgen/atomizer/modern/parser.py": [
            'Sec. 3.1.5 "Type double"',
            'Sec. 3.1.7 "Type SId"',
            'Sec. 3.4.6 ("Use of csymbol elements in MathML expressions',
            'Sec. 3.4.8 ("Initial conditions and special considerations")',
        ],
        "python/bionetgen/atomizer/modern/writer.py": [
            'Sec. 4.3.4, "Calling',
            'Sec. 3.4.6, "Use of csymbol elements in',
            'Sec. 4.11.8, "Use of reaction identifiers',
            "Sec. 4.8.5",
            'Sec. 4.6.4 ("The initialAmount,',
            "Sec. 4.11.6",
        ],
        "python/bionetgen/atomizer/modern/events.py": [
            'Sec. 4.12.2 "Trigger"',
        ],
        "python/bionetgen/atomizer/modern/fast_reactions.py": [
            "SBML Level 3 Version 1 Section 4.11 and SBML Level 2 Section 4.13",
        ],
        "cpp/io/SbmlReader.cpp": [
            'Sec. 3.4.6 ("Use of csymbol elements',
        ],
        "cpp/io/SbmlWriter.cpp": [
            'Sec. 3.4.6, "Use',
        ],
        "cpp/engine/OdeIntegrator.hpp": [
            "Sec. 4.12.7,",
        ],
        "cpp/engine/OdeIntegrator.cpp": [
            'Sec. 4.12.7 ("Detailed semantics of events")',
        ],
        "provenance/sbml-campaign/atomizer-limitations.json": [
            "Sec. 3.4.6 defines the delay and rateOf operators",
            "Sec. 4.6.6 lets a species carry the boundaryCondition attribute",
            "Sec. 3.1.5 makes positive infinity a value of the double type",
            "Sec. 3.1.5 makes not-a-number a value of the double type",
        ],
        "docs/SBML_CONFORMANCE_FINDINGS.md": [
            'section 4.12 ("Events") and section 4.6 ("Species")',
            'section 4.6.6 ("The constant and boundaryCondition attributes")',
            'section 4.6 ("Species") and the kinetic-law rules of section 4.11.7',
            'section 4.11.6 ("LocalParameter")',
            'section 4.12.2 ("Trigger")',
            "(Sec. 4.12.7)",
        ],
        "docs/CURATED_BIOMODELS_CORPUS.md": [
            'Sec. 4.11.8 ("Use of',
            'Sec. 4.2.5, "The extentUnits attribute"',
            '4.11.7, "Mathematical interpretation of SBML reactions and kinetic laws"',
            "Sec. 4.8.5",
        ],
    }
    missing = []
    for relative, fragments in expected.items():
        text = (REPO / relative).read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                missing.append((relative, fragment))
    assert not missing, f"these corrected citations are not in place: {missing}"


# The references that named the wrong section.  Each is a pairing the
# specification does not support: two sections of "Function definitions"
# cannot define the ``delay`` and ``rateOf`` operators, and "Event triggers"
# is not a section of "Reactions".
WRONG_CITATIONS = (
    "Sec. 4.3.4 and Sec. 4.3.5",
    'Sec. 4.11.4 "Event triggers"',
    'Sec. 4.9.2 "Local parameters"',
    "Sec. 4.8.5, *Compartment*",
    'Sec. 4.3, "Meaning of time"',
    "Sec. 3.1.2 defines no reserved",
    "Sec. 4.2.8",
    "Sec. 4.12.8",
    "Sec. 4.14",
)


@pytest.mark.parametrize("fragment", WRONG_CITATIONS)
def test_the_wrong_citations_are_gone(fragment):
    """The references that named the wrong section must not come back."""

    offenders = [
        str(path.relative_to(REPO))
        for path in _scanned_files()
        if fragment in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"{fragment!r} is back in {offenders}"


def test_no_citation_attributes_a_level_two_section_to_level_three():
    """A Level 2 section number must not be cited as a Level 3 one.

    Level 2 Version 4 moved "Reactions" to Section 4.13 when it added
    Compartment types and Species types; Level 3 has no Section 4.13 at all.
    A citation that says "Level 2" may name 4.13; a citation that says
    "Level 3" may not.
    """

    offenders = []
    for path, line, number, _ in _iter_citations():
        if number != "4.13":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        window = "\n".join(lines[max(0, line - 3) : line + 2])
        if "Level 2" not in window:
            offenders.append((str(path.relative_to(REPO)), line, number))
    assert (
        not offenders
    ), f"these citations name Level 2's Section 4.13 without saying so: {offenders}"


def test_a_level_two_section_is_never_cited_with_level_one_numbering():
    """A Level 3 Version 2 citation must not use Level 3 Version 1's numbers.

    Level 3 Version 2 added a numbered subsection to "Initial assignments",
    so "Semantics of initial assignments" is Section 4.8.5 in Level 3
    Version 2 and Section 4.8.4 in Level 3 Version 1, where Section 4.8.4 is
    "The sboTerm attribute".  A Level 3 Version 2 citation of Section 4.8.4
    would therefore name the wrong rule.
    """

    offenders = [
        str(path.relative_to(REPO))
        for path in _scanned_files()
        if "Sec. 4.8.4" in path.read_text(encoding="utf-8")
    ]
    assert (
        not offenders
    ), f"these files cite Level 3 Version 1's Section 4.8.4 numbering: {offenders}"


def test_the_level_dependent_fast_rule_names_each_level_own_section():
    """The one level-dependent rule names the section of the document's level.

    The ``fast`` attribute exists in Level 3 Version 1 and Level 2 and was
    removed in Level 3 Version 2, so the diagnostic has to name the section
    of the document's own level.  Its severity is the verdict the harness
    reads, so the correction may not change it.
    """

    from bionetgen.atomizer.modern import SBMLParser

    def message(level: int, version: int) -> dict:
        namespace = f"http://www.sbml.org/sbml/level{level}/version{version}/core"
        document = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="{namespace}" level="{level}" version="{version}">
  <model id="fast_case">
    <listOfCompartments>
      <compartment id="c" size="1" constant="true"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="c" initialAmount="1"
               hasOnlySubstanceUnits="true" constant="false"/>
      <species id="S2" compartment="c" initialAmount="0"
               hasOnlySubstanceUnits="true" constant="false"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false" fast="true">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="S2" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><ci>k</ci><ci>S1</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>"""
        model = SBMLParser().parse(document)
        warnings = [
            warning
            for warning in model.import_warnings
            if warning["category"] == "fastReaction"
        ]
        assert len(warnings) == 1, model.import_warnings
        return warnings[0]

    level_three_version_two = message(3, 2)
    assert level_three_version_two["severity"] == "approximated"
    assert (
        "SBML Level 3 Version 2 Core Sec. 4.11 removed the fast attribute"
        in level_three_version_two["message"]
    )

    level_three_version_one = message(3, 1)
    assert level_three_version_one["severity"] == "approximated"
    assert "SBML Level 3 Version 1 Core Sec. 4.11" in level_three_version_one["message"]

    # Level 2 numbered Reactions differently from Level 3, and differently
    # again from Level 2 Version 2 on, so the diagnostic has to name the
    # section of the document's own version.
    level_two_version_one = message(2, 1)
    assert level_two_version_one["severity"] == "approximated"
    assert "SBML Level 2 Sec. 4.9" in level_two_version_one["message"]

    level_two_version_three = message(2, 3)
    assert level_two_version_three["severity"] == "approximated"
    assert "SBML Level 2 Sec. 4.13" in level_two_version_three["message"]
