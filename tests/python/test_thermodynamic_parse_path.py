"""The Python parse path must not discard thermodynamic metadata.

`normalizeThermodynamicSyntax()` rewrites `begin barrier patterns` into a
reaction rules block whose entries carry the reserved label
`__bng3_barrier_<N>`, and moves `driven_by(W)` onto a synthetic
`setOption("__bng3_driving_work:<k>", "W")`. Nothing in the grammar
understands either construct. `BNGAstVisitor::finalizeThermodynamicMetadata()`
is the post-visit pass that moves those synthetic rules back out into
`ast::BarrierPattern` and attaches the driving work to the ordinary rule at
index `<k>`.

`cpp/bindings/bind_parser.cpp` drove the visitor without that pass, so
`_bionetgen_cpp.parse_file` and `parse_string` returned a model in which the
barrier was an ordinary reaction rule, the ordinary rules were renumbered by
the number of synthetic rules ahead of them, `driving_work` read the neutral
zero on every rule, and the synthetic options had been consumed with nothing
put back. A model using either construct parsed without a diagnostic and then
ran as an equilibrium model.

These tests assert the values themselves — barrier list, rule names, driving
work, options — not merely that parsing succeeds.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

import bionetgen._bionetgen_cpp as _cpp

_HEADER = """begin model
begin parameters
  Gbar 2
  phi 0.5
  Ea 1
  GU 0
  GP 1
  muATP 20
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin energy patterns
  A(s~U) GU
  A(s~P) GP
end energy patterns
begin seed species
  10 A(s~U)
  10 A(s~P)
end seed species
"""

_FOOTER = "end model\n"

_BARRIER_FIRST = _HEADER + """begin barrier patterns
  slow: A(s~U) -> A(s~P) Gbar
end barrier patterns
begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)
end reaction rules
""" + _FOOTER

_BARRIER_LAST = _HEADER + """begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)
end reaction rules
begin barrier patterns
  slow: A(s~U) -> A(s~P) Gbar
end barrier patterns
""" + _FOOTER

_NO_BARRIER = _HEADER + """begin reaction rules
  R1: A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)
end reaction rules
""" + _FOOTER


def _ordinary_names(model) -> list[str]:
    return [rule.rule_name for rule in model.reaction_rules]


def test_barrier_patterns_survive_the_python_parse_path():
    model = _cpp.parse_string(_BARRIER_FIRST)

    assert len(model.barrier_patterns) == 1
    barrier = model.barrier_patterns[0]
    assert barrier.label == "slow"
    assert barrier.expression == "Gbar"

    # A barrier is a transition-state contribution, not an ordinary rule. If it
    # is still sitting in the rule list the metadata was never finalized.
    assert _ordinary_names(model) == ["R1"]


def test_driven_by_work_survives_the_python_parse_path():
    model = _cpp.parse_string(_BARRIER_FIRST)

    assert len(model.reaction_rules) == 1
    rule = model.reaction_rules[0]
    assert rule.has_driving_work is True
    assert rule.driving_work == "muATP"


def test_a_model_without_driven_by_reports_no_driving_work():
    model = _cpp.parse_string(_HEADER + """begin reaction rules
  A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
""" + _FOOTER)

    rule = model.reaction_rules[0]
    assert rule.has_driving_work is False
    # Zero is the neutral element, so a consumer that ignores the flag still
    # gets the undriven rate pair.
    assert rule.driving_work == "0"


def test_synthetic_options_are_consumed_and_user_options_survive():
    source = _BARRIER_FIRST.replace(
        "end model",
        'setOption("user_marker", "kept")\nend model',
    )
    model = _cpp.parse_string(source)

    assert model.options.get("user_marker") == "kept"
    # The `__bng3_*` channel is an internal hand-off between the source
    # normalizer and the post-visit pass. Anything left in it means the pass
    # never ran and its payload was dropped.
    assert [key for key in model.options if key.startswith("__bng3_")] == []


def test_a_barrier_block_does_not_shift_the_names_of_ordinary_rules():
    """A barrier must not renumber the rules the user wrote.

    The synthetic barrier rules consume rule names while parsing, and the
    surviving rules are renumbered so the model is indistinguishable from one
    written without a barrier block. Where that step is skipped, the synthetic
    rule keeps a name and every ordinary rule after it is pushed down by one —
    silently changing the identity of rules the model names itself.
    """
    without = _cpp.parse_string(_NO_BARRIER)
    first = _cpp.parse_string(_BARRIER_FIRST)
    last = _cpp.parse_string(_BARRIER_LAST)

    assert _ordinary_names(without) == ["R1"]
    assert _ordinary_names(first) == _ordinary_names(without)
    assert _ordinary_names(last) == _ordinary_names(without)

    # The user-written label travels with the rule it was written on.
    assert first.reaction_rules[0].label == "R1:"
    assert last.reaction_rules[0].label == "R1:"

    # And the driving work is bound to that same rule whichever order the two
    # blocks were written in.
    for model in (first, last):
        assert model.reaction_rules[0].has_driving_work is True
        assert model.reaction_rules[0].driving_work == "muATP"


def test_python_parse_round_trips_a_driven_by_model_through_the_bngl_writer():
    model = _cpp.parse_string(_BARRIER_FIRST)
    written = _cpp.io.write_bngl_string(model)

    assert "begin barrier patterns" in written
    assert "slow: A(s~U) -> A(s~P) Gbar" in written
    assert "driven_by(muATP)" in written

    # Re-reading the writer's own output must produce the same model; this is
    # the round trip that could not be performed at all before the fix.
    reparsed = _cpp.parse_string(written)
    assert len(reparsed.barrier_patterns) == 1
    assert reparsed.barrier_patterns[0].label == "slow"
    assert reparsed.reaction_rules[0].driving_work == "muATP"


def _bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        _REPO_ROOT / "build" / "cpp" / "bng_cpp"
    )
    if Path(candidate).exists():
        return candidate
    pytest.skip(f"bng_cpp not available at {candidate}")


@pytest.mark.skipif(
    not (
        os.environ.get("BNG_CPP") or (_REPO_ROOT / "build" / "cpp" / "bng_cpp").exists()
    ),
    reason="bng_cpp execution oracle is not built",
)
def test_the_python_parse_path_agrees_with_the_cpp_parse_path(tmp_path):
    """Both parse paths must produce the same model, checked on the network.

    `bng_cpp` reaches the parser through `parseModelFromFile`; the Python
    bindings reach it through `parse_file`. Comparing the `.net` each one
    generates for the same source compares the two parsers on the artifact the
    barrier actually changes, not just on the parse result.
    """
    source = _BARRIER_FIRST.replace(
        "end model",
        "begin actions\n  generate_network({overwrite=>1})\nend actions\nend model",
    )
    model_path = tmp_path / "driven.bngl"
    model_path.write_text(source)

    environment = dict(os.environ, BNG_NFSIM_GENERAL_ENERGY="1")
    completed = subprocess.run(
        [_bng_cpp(), str(model_path)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    cli_net = tmp_path / "driven.net"
    assert cli_net.exists()

    # Non-vacuity: two empty networks would compare equal while proving
    # nothing, so the artifact must actually carry the driven rate pair.
    assert "R1Rate_1" in cli_net.read_text()
    assert "R1rRate_1" in cli_net.read_text()

    # The energy gate is read from the environment when the rate laws are
    # lowered, not when the model is parsed, so it has to be set in-process too.
    with mock.patch.dict(os.environ, {"BNG_NFSIM_GENERAL_ENERGY": "1"}):
        native = _cpp.parse_file(str(model_path))
        network = _cpp.generate_network(native)
        python_net = tmp_path / "python.net"
        _cpp.io.write_net(native, network, str(python_net))

    assert python_net.read_text() == cli_net.read_text()


def test_hoisted_barrier_label_reaches_the_barrier_pattern():
    """The user label travels through the synthetic option channel.

    `normalizeThermodynamicSyntax()` cannot put the user's label on the
    synthetic rule, because the synthetic label has to own the leading
    position. It re-emits it as `setOption("__bng3_barrier_label:0", "slow")`
    and the post-visit pass puts it back on the barrier. If that option is
    dropped instead, the model still parses and still has exactly one barrier
    pattern; it has simply lost the name the user gave it, which is why this
    is asserted separately from the count.
    """
    model = _cpp.parse_string(_BARRIER_FIRST)

    assert len(model.barrier_patterns) == 1
    assert model.barrier_patterns[0].label == "slow"
