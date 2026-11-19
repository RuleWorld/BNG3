"""Differential case for #171: PyBioNetGen public model loading.

Selected row: ``py.modelapi.bngfile.BNGFile.strip_actions`` exercised through
the public ``bionetgen.bngmodel(path)`` model-loading entry point. Both
PyBioNetGen 28bf351 (distribution version 0.8.7) and BNG3 advertise loading a
BNGL model from a file; the pinned reference keeps model definitions whose
identifiers merely *contain* an action name as a substring.

Pinned reference contract: ``BNGFile._not_action`` anchors action detection at
the start of the left-stripped line. A definition such as
``conversion(t) = t * k`` (``conversion(`` contains the ``version`` action
token) is model content, not an action, and must survive into the stripped
BNGL and the loaded model. A real action line is still stripped and recorded
in ``parsed_actions``.

Why existing tests miss it: ``tests/python/test_bngfile_compat.py`` and the
other PyBioNetGen differential tests use only simple identifiers (``k``,
``A``, ``A_tot``) and assert basic ``write_xml``/``bngmodel`` success. None
contains an action-name substring in a definition, so the substring-vs-anchor
difference in ``_not_action`` was never observed.

Installed-environment differential evidence (separate clean venvs, same input
model and arguments): pinned reference 0.8.7 loads the model with the function
intact and an empty ``parsed_actions``; the BNG3 3.0.0a1 wheel at origin/main
raises ``BNGParseError: ... Failed to parse action conversion(t)=t*k`` and
drops the function; the repaired wheel matches the reference exactly.

The continuation cases at the bottom of this file encode the same pinned
reference's ``strip_actions`` behavior for a comment-held `\`, an inline
comment, a real continued live line (with and without trailing whitespace),
and a quoted `#` marker.
"""

from __future__ import annotations

from pathlib import Path

import bionetgen
from bionetgen.modelapi.bngfile import BNGFile

MODEL_WITH_CONVERSION_FUNCTION = """begin model
begin parameters
    k 1
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin functions
    conversion(t) = t * k
end functions
begin observables
    Molecules A_tot A()
end observables
begin reaction rules
    A() -> 0 k
end reaction rules
end model
"""

MODEL_WITH_REAL_ACTION = MODEL_WITH_CONVERSION_FUNCTION.replace(
    "end model",
    "begin actions\n    generate_network({overwrite=>1})\nend actions\nend model",
)


def _write_model(tmp_path: Path, text: str, name: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _strip(model_path: Path, tmp_path: Path):
    folder = tmp_path / "stripped"
    folder.mkdir()
    bng_file = BNGFile(str(model_path))
    stripped_path = Path(bng_file.strip_actions(str(model_path), str(folder)))
    return bng_file, stripped_path.read_text(encoding="utf-8")


def test_bngmodel_loads_function_name_containing_action_substring(tmp_path):
    """Pinned reference loads this model; base BNG3 raised BNGParseError."""

    model_path = _write_model(tmp_path, MODEL_WITH_CONVERSION_FUNCTION, "fn.bngl")
    model = bionetgen.bngmodel(str(model_path))

    assert [str(item) for item in model.functions] == ["conversion"]
    assert "conversion(t)" in str(model)


def test_strip_actions_keeps_definition_with_action_substring(tmp_path):
    model_path = _write_model(tmp_path, MODEL_WITH_CONVERSION_FUNCTION, "fn.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    assert "conversion(t) = t * k" in stripped
    assert bng_file.parsed_actions == []


def test_strip_actions_still_strips_a_real_action_edge_case(tmp_path):
    """Guards against over-correction: genuine actions remain actions."""

    model_path = _write_model(tmp_path, MODEL_WITH_REAL_ACTION, "fn_action.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    assert "conversion(t) = t * k" in stripped
    assert "generate_network" not in stripped
    assert bng_file.parsed_actions == ["generate_network({overwrite=>1})"]

    # The same model still loads through the public entry point.
    model = bionetgen.bngmodel(str(model_path))
    assert [str(item) for item in model.functions] == ["conversion"]


# ---------------------------------------------------------------------------
# Line-continuation handling. The four fixtures below encode the retained text
# produced by the pinned reference (PyBioNetGen 28bf351, distribution 0.8.7)
# through the public BNGFile.strip_actions entry point. The reference collapses
# `\`+newline only when the marker precedes any `#` on its physical line:
#
#   re.sub(r"^([^#\n]*)\\[ \t]*\n", r"\1", mstr, flags=re.MULTILINE)
#
# A marker inside a comment (or after a quoted `#`) is left alone; an actual
# continued live line is joined, including the trailing-whitespace form BNG2.pl
# tolerates. BNG3 used to collapse every `\`+newline, gluing a live definition
# into the preceding comment and dropping it from the stripped model.
# ---------------------------------------------------------------------------

MODEL_COMMENT_CONTINUATION = (
    "begin functions\n"
    "   # commented-out definition whose continuation marker is inside a comment\n"
    "   # foo()=if(t<42,0,\\\n"
    "   foo()=if(t<42,9.899,\\\n"
    "          1/(1+t))\n"
    "end functions\n"
)

MODEL_CONTINUED_LIVE_LINE = (
    "begin functions\n"
    "   foo()=if(t<42,9.899,\\\n"
    "          1/(1+t))\n"
    "   bar()=if(t<1,2,\\   \n"
    "          3/(1+t))\n"
    "end functions\n"
)

MODEL_INLINE_COMMENT = (
    "begin functions\n"
    "   foo()=if(t<42,9.899,\\ # inline note\n"
    "          1/(1+t))\n"
    "end functions\n"
)

MODEL_QUOTED_COMMENT_MARKER = (
    "begin actions\n"
    '  generate_network({suffix=>"x#y",\\\n'
    "    overwrite=>1})\n"
    "end actions\n"
)


def test_strip_actions_keeps_live_definition_after_comment_continuation(tmp_path):
    """A `\` inside a comment must not consume the following live definition."""

    model_path = _write_model(tmp_path, MODEL_COMMENT_CONTINUATION, "comment_cont.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    # The comment line survives verbatim, with its trailing continuation marker.
    assert "   # foo()=if(t<42,0,\\\n" in stripped
    # The two physical lines of the live definition are joined into one line.
    assert "   foo()=if(t<42,9.899,          1/(1+t))\n" in stripped
    assert bng_file.parsed_actions == []


def test_strip_actions_collapses_continued_lines_with_trailing_whitespace(tmp_path):
    """An actual continued live line is joined, including trailing spaces after `\`."""

    model_path = _write_model(tmp_path, MODEL_CONTINUED_LIVE_LINE, "continued.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    assert "   foo()=if(t<42,9.899,          1/(1+t))\n" in stripped
    assert "   bar()=if(t<1,2,          3/(1+t))\n" in stripped
    assert bng_file.parsed_actions == []


def test_strip_actions_inline_comment_does_not_join_next_line(tmp_path):
    """A `\` followed by an inline comment is not a continuation marker."""

    model_path = _write_model(tmp_path, MODEL_INLINE_COMMENT, "inline_comment.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    assert "foo()=if(t<42,9.899,\\ # inline note\n" in stripped
    assert "          1/(1+t))" in stripped
    assert bng_file.parsed_actions == []


def test_strip_actions_quoted_comment_marker_keeps_line_separate(tmp_path):
    """A quoted `#` blocks continuation collapse, as in the pinned reference."""

    model_path = _write_model(tmp_path, MODEL_QUOTED_COMMENT_MARKER, "quoted_hash.bngl")
    bng_file, stripped = _strip(model_path, tmp_path)

    assert stripped.strip() == ""
    # The action ends at the quoted-`#` line; the following physical line is not
    # folded into it. BNG3 normalizes spaces in action text, so assert the
    # continuation shape rather than the reference's exact leading whitespace.
    assert len(bng_file.parsed_actions) == 1
    assert bng_file.parsed_actions[0].rstrip().endswith("\\")
    assert "overwrite=>1" not in bng_file.parsed_actions[0]
