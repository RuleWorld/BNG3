import pytest
from click.testing import CliRunner

from bionetgen.cli import main


@pytest.mark.parametrize("option", [["--log", "run.log"], ["--no-bngsim"]])
@pytest.mark.parametrize("input_option", [[], ["--input"]])
def test_unimplemented_run_controls_fail_before_execution(
    tmp_path, option, input_option
):
    # Retain the historical case IDs; these controls now require execution.
    model = tmp_path / "model.bngl"
    model.write_text(MODEL, encoding="utf-8")
    output = tmp_path / ("results" if input_option else "result.tsv")
    requested = list(option)
    if requested[0] == "--log":
        requested[1] = str(tmp_path / "run.log")
    result = CliRunner().invoke(
        main,
        [
            "run",
            *input_option,
            str(model),
            *requested,
            "--output",
            str(output),
            "--t-end",
            "1",
            "--n-steps",
            "4",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (output / "model.gdat" if input_option else output).is_file()
    if requested[0] == "--log":
        assert (tmp_path / "run.log").read_text().strip()


@pytest.mark.parametrize("option", [["--timeout", "0"], ["--format", "bngl"]])
def test_positional_run_rejects_unimplemented_legacy_controls(tmp_path, option):
    # Preserve both cases while requiring the requested control's behavior.
    model = tmp_path / "model.bngl"
    model.write_text(MODEL, encoding="utf-8")
    output = tmp_path / "result.tsv"
    result = CliRunner().invoke(
        main,
        [
            "run",
            str(model),
            *option,
            "--output",
            str(output),
            "--t-end",
            "1",
            "--n-steps",
            "4",
        ],
    )
    if option[0] == "--timeout":
        assert result.exit_code != 0
        assert "timed out" in result.output
        assert not output.exists()
    else:
        assert result.exit_code == 0, result.output
        assert output.is_file()


MODEL = """begin model
begin parameters
k 0.5
end parameters
begin molecule types
A()
end molecule types
begin seed species
A() 10
end seed species
begin observables
Molecules total A()
end observables
begin reaction rules
A() -> 0 k
end reaction rules
end model
simulate({method=>"ode",t_end=>1,n_steps=>4})
"""


@pytest.mark.parametrize("input_option", [[], ["--input"]])
@pytest.mark.parametrize("control", ["log", "timeout", "no-bngsim"])
def test_run_process_controls_execute_in_the_worker(
    tmp_path, monkeypatch, input_option, control
):
    import numpy as np
    import bionetgen

    source = tmp_path / "decay.bngl"
    source.write_text(MODEL)
    output = tmp_path / ("results" if input_option else "result.tsv")
    log = tmp_path / "native.log"
    options = {
        "log": ["--log", str(log)],
        "timeout": ["--timeout", "30"],
        "no-bngsim": ["--no-bngsim"],
    }[control]

    def no_parent_parse(*args, **kwargs):
        pytest.fail("process control executed a native parse in the parent")

    monkeypatch.setattr(bionetgen._bionetgen_cpp, "parse_file", no_parent_parse)
    result = CliRunner().invoke(
        main,
        [
            "run",
            *input_option,
            str(source),
            "--output",
            str(output),
            "--t-end",
            "1",
            "--n-steps",
            "4",
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    data_file = output / "decay.gdat" if input_option else output
    values = np.loadtxt(data_file)
    np.testing.assert_allclose(values[:, 0], [0, 0.25, 0.5, 0.75, 1])
    assert values[0, 1] == 10
    assert values[-1, 1] < 10
    if control == "log":
        assert log.read_text().strip()
    assert source.read_text() == MODEL


@pytest.mark.parametrize("input_option", [[], ["--input"]])
def test_run_deadline_does_not_write_success_output(tmp_path, input_option):
    source = tmp_path / "decay.bngl"
    source.write_text(MODEL)
    output = tmp_path / ("results" if input_option else "result.tsv")
    result = CliRunner().invoke(
        main,
        [
            "run",
            *input_option,
            str(source),
            "--output",
            str(output),
            "--timeout",
            "0",
        ],
    )
    assert result.exit_code != 0
    assert "timed out" in result.output
    if input_option:
        assert not list(output.glob("*.gdat"))
    else:
        assert not output.exists()


def test_positional_parse_error_is_preserved_in_the_log(tmp_path):
    source = tmp_path / "invalid.bngl"
    source.write_text(
        "begin model\nbegin parameters\nk = (\nend parameters\nend model\n"
    )
    log = tmp_path / "error.log"
    result = CliRunner().invoke(main, ["run", str(source), "--log", str(log)])
    assert result.exit_code != 0
    assert "invalid.bngl" in log.read_text()
    assert "not supported" not in result.output


@pytest.mark.parametrize("input_option", [[], ["--input"]])
def test_run_non_bngl_format_is_explicitly_rejected(tmp_path, input_option):
    source = tmp_path / "model.bngl"
    source.write_text(MODEL)
    result = CliRunner().invoke(
        main, ["run", *input_option, str(source), "--format", "sbml"]
    )
    assert result.exit_code != 0
    assert "convert other formats first" in result.output


def test_explicit_bngl_hint_cannot_silently_select_an_xml_loader(tmp_path):
    source = tmp_path / "model.xml"
    source.write_text(MODEL)
    result = CliRunner().invoke(main, ["run", str(source), "--format", "bngl"])
    assert result.exit_code != 0
    assert "requires a .bngl input file" in result.output
