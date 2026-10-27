"""Tests for the standalone validation harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.cross_validate import _stage_model
from scripts.validate import copy_referenced_support_files


def test_validation_harness_copies_referenced_net_support_file(tmp_path):
    validate_dir = tmp_path / "Validate"
    dat_dir = validate_dir / "DAT_validate"
    source_dir = validate_dir / "INPUT_FILES"
    dat_dir.mkdir(parents=True)
    source_dir.mkdir()
    model = validate_dir / "model.bngl"
    model.write_text('readFile({file=>"model.net"})\n', encoding="utf-8")
    (dat_dir / "model.net").write_text("begin species\nend species\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    copied = copy_referenced_support_files(model, validate_dir, dat_dir, work_dir)

    assert copied == [work_dir / "model.net"]
    assert (work_dir / "model.net").read_text(encoding="utf-8") == (
        "begin species\nend species\n"
    )


def test_validation_harness_copies_tfun_table_from_either_argument_position(tmp_path):
    validate_dir = tmp_path / "Validate"
    dat_dir = validate_dir / "DAT_validate"
    dat_dir.mkdir(parents=True)
    model = validate_dir / "model.bngl"
    model.write_text(
        "f_bng3() = tfun('tables/increase.tfun', nested(time, 2))\n"
        'f_bng2() = TFUN(nested(time, 2), "tables/increase.tfun")\n',
        encoding="utf-8",
    )
    source = dat_dir / "tables" / "increase.tfun"
    source.parent.mkdir()
    source.write_text("0 1\n1 2\n", encoding="utf-8")
    work_dir = tmp_path / "work"

    copied = copy_referenced_support_files(model, validate_dir, dat_dir, work_dir)

    staged = work_dir / "tables" / "increase.tfun"
    assert copied == [staged]
    assert staged.read_text(encoding="utf-8") == "0 1\n1 2\n"


def test_cross_validation_stages_the_tfun_corpus_sidecar(tmp_path):
    models_dir = Path(__file__).resolve().parents[1] / "models"
    model = models_dir / "test_tfun_file.bngl"

    staged_model = _stage_model(model, models_dir, tmp_path / "reference")

    staged_table = staged_model.parent / "test_data.tfun"
    assert staged_table.read_bytes() == (models_dir / "test_data.tfun").read_bytes()


def test_cross_validation_stages_explicit_validation_companions_only(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model = models_dir / "fixture.bngl"
    model.write_text(
        'begin actions\n'
        '  readFile({file=>"INPUT_FILES/source.xml"})\n'
        '  readFile({file=>"fixture.net"})\n'
        'end actions\n',
        encoding="utf-8",
    )
    support_root = tmp_path / "Validate"
    xml = support_root / "INPUT_FILES" / "source.xml"
    net = support_root / "DAT_validate" / "fixture.net"
    unrelated = support_root / "DAT_validate" / "unreferenced.net"
    xml.parent.mkdir(parents=True)
    net.parent.mkdir(parents=True)
    xml.write_text("<sbml/>", encoding="utf-8")
    net.write_text("begin species\nend species\n", encoding="utf-8")
    unrelated.write_text("not referenced", encoding="utf-8")

    staged = _stage_model(
        model,
        models_dir,
        tmp_path / "staged",
        support_roots=(support_root,),
    )

    assert (staged.parent / "INPUT_FILES/source.xml").read_text() == "<sbml/>"
    assert (staged.parent / "fixture.net").read_text() == (
        "begin species\nend species\n"
    )
    assert not (staged.parent / "unreferenced.net").exists()


def test_cross_validation_rejects_conflicting_companion_sources(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model = models_dir / "fixture.bngl"
    model.write_text('readFile({file=>"INPUT_FILES/source.xml"})\n', encoding="utf-8")
    primary = models_dir / "INPUT_FILES" / "source.xml"
    primary.parent.mkdir()
    primary.write_text("<sbml id='primary'/>", encoding="utf-8")
    support_root = tmp_path / "Validate"
    fallback = support_root / "INPUT_FILES" / "source.xml"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("<sbml id='fallback'/>", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting staged support file"):
        _stage_model(
            model,
            models_dir,
            tmp_path / "staged",
            support_roots=(support_root,),
        )


@pytest.mark.parametrize(
    ("model_name", "support_file"),
    [
        ("test_sbml_flat", "INPUT_FILES/test_sbml_flat_SBML.xml"),
        ("test_sbml_structured", "INPUT_FILES/test_sbml_structured_SBML.xml"),
        ("michment_cont", "michment_cont.net"),
        ("test_sat_cont", "test_sat_cont.net"),
    ],
)
def test_conformance_models_stage_validation_fixture_companions(
    tmp_path, model_name, support_file
):
    repository = Path(__file__).resolve().parents[1]
    models_dir = repository / "models"
    support_root = repository / "tests" / "validation" / "Validate"
    source = models_dir / f"{model_name}.bngl"

    staged = _stage_model(
        source,
        models_dir,
        tmp_path / model_name,
        support_roots=(support_root,),
    )

    actual = staged.parent / support_file
    if support_file.startswith("INPUT_FILES/"):
        expected = support_root / support_file
    else:
        expected = support_root / "DAT_validate" / support_file
    assert actual.read_bytes() == expected.read_bytes()
