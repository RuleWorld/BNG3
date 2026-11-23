"""``--require`` version guard parity with pinned PyBioNetGen 28bf351a."""

from click.testing import CliRunner

from bionetgen.cli import main


def test_satisfied_requirement_runs_the_command():
    result = CliRunner().invoke(main, ["--require", "0.8.6", "info", "--help"])
    assert result.exit_code == 0, result.output


def test_unsatisfied_requirement_is_refused():
    result = CliRunner().invoke(main, ["--require", "99.0.0", "info", "--help"])
    assert result.exit_code != 0
    assert "version" in (result.output + str(result.exception)).lower()
