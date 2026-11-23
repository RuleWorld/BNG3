"""PyBioNetGen atomizer CLI spellings are accepted by BNG3's atomize command."""

from click.testing import CliRunner

from bionetgen.cli import main

EXPECTED_FLAGS = (
    "--input-file",
    "--output-file",
    "--annotation",
    "--convention-file",
    "--naming-conventions",
    "--user-structures",
    "--molecule-id",
    "--isomorphism-check",
    "--ignore",
    "--memoized-resolver",
    "--keep-local-parameters",
    "--quiet-mode",
    "--obs-map-file",
    "--log-level",
    "--bionetgen-analysis",
    "--convert-units",
    "--pathwaycommons",
)


def test_atomize_accepts_pinned_option_spellings():
    help_text = CliRunner().invoke(main, ["atomize", "--help"]).output
    for flag in EXPECTED_FLAGS:
        assert flag in help_text, f"missing CLI flag {flag}"


def test_input_file_alias_performs_a_real_translation(tmp_path):
    source = "tests/fixtures/sbml_test_suite_reaction_rate/01385-sbml-l3v2.xml"
    destination = tmp_path / "translated.bngl"
    result = CliRunner().invoke(
        main,
        [
            "atomize",
            "--input-file",
            source,
            "--output-file",
            str(destination),
            "--annotation",
        ],
    )
    assert result.exit_code == 0, result.output
    text = destination.read_text()
    assert "begin model" in text and "begin reaction rules" in text
