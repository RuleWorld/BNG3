"""Native execution honors the retained CLI logging and timeout controls."""

import subprocess

import pytest
from _extdep import require_extension

from bionetgen.core.exc import BNGRunError
from bionetgen.core.tools.cli import BNGCLI

require_extension()

MODEL = """begin model
begin molecule types
A()
end molecule types
begin seed species
A() 1
end seed species
end model
quit()
"""


def _cli(tmp_path, **options):
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "BNG2.pl").write_text("# never used by native execution\n")
    model = tmp_path / "model.bngl"
    model.write_text(MODEL)
    return BNGCLI(str(model), str(tmp_path / "output"), str(reference), **options)


@pytest.mark.parametrize("kind", ["file", "directory", "trailing-separator"])
def test_native_cli_writes_actual_output_to_requested_log(tmp_path, kind):
    if kind == "file":
        target = tmp_path / "nested" / "native.log"
        expected = target
    else:
        target = tmp_path / "logs"
        if kind == "directory":
            target.mkdir()
        expected = target / "model.log"
    requested = str(target) + ("/" if kind == "trailing-separator" else "")
    cli = _cli(tmp_path, log_file=requested, suppress=True)
    cli.run()
    assert cli.result.process_return == 0
    text = expected.read_text()
    assert "quit()" in text
    # Product #757 made the native diagnostic ASCII-only, so the two capture
    # paths are byte-for-byte identical on every platform. Compare exactly:
    # the log-vs-return equality is the actual contract under test.
    assert "\n".join(cli.result.output) == text.rstrip("\n")


def test_native_cli_output_is_ascii_without_replacement_chars(tmp_path):
    # Encoding regression guard for #757. A non-ASCII emitter (the old em dash)
    # is mangled to U+FFFD by a UTF-8-decoding parent when MSVC uses a local
    # execution charset; keep a focused check that both captured paths are
    # clean ASCII even if the exact-comparison test above is later refactored.
    log = tmp_path / "ascii.log"
    cli = _cli(tmp_path, log_file=str(log), suppress=True)
    cli.run()
    assert cli.result.process_return == 0
    for value in ("\n".join(cli.result.output), log.read_text()):
        assert value.isascii(), value
        assert "\ufffd" not in value


def test_native_cli_honors_timeout_and_does_not_report_success(tmp_path):
    cli = _cli(tmp_path, timeout=0.000001, suppress=True)
    with pytest.raises(subprocess.TimeoutExpired):
        cli.run()
    assert cli.result is None


def test_native_cli_preserves_parse_error_in_log(tmp_path):
    log = tmp_path / "error.log"
    cli = _cli(tmp_path, log_file=str(log), suppress=True)
    (tmp_path / "model.bngl").write_text("begin model\ninvalid syntax\nend model\n")
    with pytest.raises(BNGRunError) as error:
        cli.run()
    assert cli.result is None
    assert "ParseError" in log.read_text()
    assert "ParseError" in error.value.stdout


@pytest.mark.parametrize("foreign", ["package", "native"])
def test_native_worker_refuses_a_foreign_runtime(tmp_path, foreign):
    from pathlib import Path
    import sys

    import bionetgen
    import bionetgen.core.tools.cli as cli_module
    from bionetgen.model import _cpp

    worker = (
        Path(cli_module.__file__).resolve().parents[2]
        / "compat"
        / "_native_cli_worker.py"
    )
    source = tmp_path / "model.bngl"
    source.write_text(MODEL)
    package = Path(bionetgen.__file__).resolve()
    native = Path(_cpp.__file__).resolve()
    if foreign == "package":
        package = tmp_path / "foreign" / "__init__.py"
    else:
        native = tmp_path / "foreign.so"
    process = subprocess.run(
        [sys.executable, str(worker), str(source), str(package), str(native), "1"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode != 0
    message = "Python package" if foreign == "package" else "native extension"
    assert "imported a different " + message in process.stderr
