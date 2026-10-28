import os
import subprocess
from pathlib import Path

import pytest

from scripts.cross_validate import (
    REPO,
    _network_only_text,
    _prepare_continuation_input,
    _short_process_error,
    _stage_model,
    _try_compare_network_files,
)
from tests.validation.compare import parse_net


def test_network_only_keeps_generation_after_sbml_import(tmp_path: Path):
    model = tmp_path / "imported.bngl"
    model.write_text(
        'readFile({file=>"INPUT_FILES/model.xml"})\n'
        "generate_network({overwrite=>1})\n",
        encoding="utf-8",
    )

    staged = _stage_model(model, tmp_path, tmp_path / "stage")

    assert 'readFile({file=>"INPUT_FILES/model.xml"})' in staged.read_text()
    assert "generate_network({overwrite=>1})" in staged.read_text()


def test_network_only_does_not_regenerate_after_reading_network(tmp_path: Path):
    model = tmp_path / "continuation.bngl"
    model.write_text('readFile({file=>"base.net"})\n', encoding="utf-8")

    staged = _stage_model(model, tmp_path, tmp_path / "stage")

    assert 'readFile({file=>"base.net"})' in staged.read_text()
    assert "generate_network(" not in staged.read_text()


@pytest.mark.parametrize(
    "model_name", ["localfunc", "isingspin_localfcn", "test_assignment"]
)
def test_bng2_generates_local_function_networks(model_name: str, tmp_path: Path):
    source = REPO / "tests" / "validation" / "Validate" / f"{model_name}.bngl"
    staged = _stage_model(source, source.parent, tmp_path, write_tfun_xml=True)
    perl = REPO / "legacy" / "perl" / "BNG2.pl"
    env = os.environ.copy()
    env["BNGPATH"] = str(perl.parent)

    result = subprocess.run(
        ["perl", str(perl), "--outdir", str(tmp_path), str(staged)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (tmp_path / f"{model_name}.net").is_file()


def test_bng2_still_rejects_undefined_global_rate(tmp_path: Path):
    source = tmp_path / "undefined_rate.bngl"
    source.write_text(
        """begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin reaction rules
    A() -> 0 missing_rate
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
end actions
""",
        encoding="utf-8",
    )
    perl = REPO / "legacy" / "perl" / "BNG2.pl"
    env = os.environ.copy()
    env["BNGPATH"] = str(perl.parent)

    result = subprocess.run(
        ["perl", str(perl), "--outdir", str(tmp_path), str(source)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing_rate" in result.stderr + result.stdout


def test_missing_continuation_producer_cannot_fall_back_to_reference(tmp_path: Path):
    corpus = tmp_path / "models"
    corpus.mkdir()
    work_dir = tmp_path / "perl"
    work_dir.mkdir()
    stale_reference = work_dir / "michment_cont.net"
    stale_reference.write_text("committed reference must not be consumed\n")

    error = _prepare_continuation_input(
        "Perl",
        Path("legacy/perl/BNG2.pl"),
        "perl",
        corpus,
        work_dir,
        "michment_cont",
        10,
    )

    assert error == "missing continuation base model michment.bngl"
    assert not stale_reference.exists()


def test_successful_base_process_without_network_cannot_fall_back_to_reference(
    monkeypatch, tmp_path: Path
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    base = REPO / "tests" / "validation" / "Validate" / "michment.bngl"
    (corpus / base.name).write_bytes(base.read_bytes())
    work_dir = tmp_path / "perl"
    work_dir.mkdir()
    stale_reference = work_dir / "michment_cont.net"
    stale_reference.write_text("stale reference\n")
    monkeypatch.setattr(
        "scripts.cross_validate._run_engine",
        lambda *_args, **_kwargs: (subprocess.CompletedProcess([], 0), None),
    )

    error = _prepare_continuation_input(
        "Perl",
        REPO / "legacy" / "perl" / "BNG2.pl",
        "perl",
        corpus,
        work_dir,
        "michment_cont",
        10,
    )

    assert error == "Perl base michment did not write michment_cont.net"
    assert not stale_reference.exists()


@pytest.mark.parametrize(
    ("engine", "model_name", "base_name"),
    [
        ("Perl", "michment_cont", "michment"),
        ("Perl", "test_sat_cont", "test_sat"),
        ("C++", "michment_cont", "michment"),
        ("C++", "test_sat_cont", "test_sat"),
    ],
)
def test_continuation_uses_live_base_writer_not_reference(
    engine: str, model_name: str, base_name: str, bng_cpp, tmp_path: Path
):
    corpus = tmp_path / "corpus"
    reference_dir = corpus / "DAT_validate"
    reference_dir.mkdir(parents=True)
    for name in (base_name, model_name):
        source = REPO / "tests" / "validation" / "Validate" / f"{name}.bngl"
        (corpus / source.name).write_bytes(source.read_bytes())
    poison = reference_dir / f"{model_name}.net"
    poison.write_text("poison reference must not survive prerequisite generation\n")

    work_dir = tmp_path / engine / model_name
    _stage_model(corpus / f"{model_name}.bngl", corpus, work_dir)
    staged_target = work_dir / f"{model_name}.net"
    assert staged_target.read_text() == poison.read_text()
    engine_path = REPO / "legacy" / "perl" / "BNG2.pl" if engine == "Perl" else bng_cpp

    error = _prepare_continuation_input(
        engine,
        Path(engine_path),
        "perl",
        corpus,
        work_dir,
        model_name,
        60,
    )

    assert error is None
    assert staged_target.is_file()
    assert staged_target.read_text() != poison.read_text()
    assert parse_net(staged_target) is not None


def test_invalid_tfun_reference_sidecar_is_a_model_error(monkeypatch, tmp_path: Path):
    def reject_sidecar(*_args, **_kwargs):
        raise ValueError("TFUN XML sidecar is inconsistent with reference network")

    monkeypatch.setattr("scripts.cross_validate.compare_network_files", reject_sidecar)

    diff, error = _try_compare_network_files(
        tmp_path / "reference.net",
        tmp_path / "test.net",
        reference_tfun_xml=tmp_path / "reference.xml",
    )

    assert diff is None
    assert error == "TFUN XML sidecar is inconsistent with reference network"


def test_engine_error_reports_terminal_abort_after_leading_warning():
    result = subprocess.CompletedProcess(
        ["BNG2.pl"],
        1,
        stdout="WARNING: preflight message\nABORT: invalid model\n",
        stderr="",
    )

    assert _short_process_error(result) == "ABORT: invalid model"


def test_weekly_sbml_translator_is_installed_in_bng2_lookup_directory():
    workflow = (REPO / ".github" / "workflows" / "weekly.yml").read_text(
        encoding="utf-8"
    )

    assert 'mkdir -p "$RUNNER_TEMP/oracle-bionetgen/bng2/bin"' in workflow
    assert '> "$RUNNER_TEMP/oracle-bionetgen/bng2/bin/sbmlTranslator"' in workflow
