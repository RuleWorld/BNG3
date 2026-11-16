import pytest
from click.testing import CliRunner

from bionetgen.cli import main


@pytest.mark.parametrize("option", [["--log", "run.log"], ["--no-bngsim"]])
@pytest.mark.parametrize("input_option", [[], ["--input"]])
def test_unimplemented_run_controls_fail_before_execution(tmp_path, option, input_option):
    model = tmp_path / "model.bngl"
    model.write_text("begin model\nend model\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["run", *input_option, str(model), *option])

    assert result.exit_code != 0
    assert "not supported" in result.output.lower()
