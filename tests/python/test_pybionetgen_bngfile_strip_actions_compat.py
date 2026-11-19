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
