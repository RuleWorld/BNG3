"""Native CLI diagnostics must be ASCII-safe at the real subprocess/log consumer.

The Python parent captures native CLI output with ``encoding="utf-8",
errors="replace"``.  A non-ASCII emitter in the C++ log string is mangled to
U+FFFD by compilers that use a local execution charset (notably MSVC without
``/utf-8``), so the written log and the captured output no longer carry the
diagnostic verbatim.  This module pins the repaired quit() diagnostic at the
same consumer that broke on Windows and proves the detector rejects damaged
output with a negative control.

The expected string is ASCII-only; any non-ASCII byte, or a U+FFFD replacement
character after decoding, is a defect regardless of host compiler.
"""

from pathlib import Path
import subprocess

import pytest
from _extdep import require_extension

from bionetgen.core.tools.cli import BNGCLI

require_extension()

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "cpp" / "bng_cpp"
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
EXPECTED_QUIT = "[bng_cpp] quit() -- stopping action processing"


def _assert_clean_diagnostic(chunks):
    """Exact, encoding-aware detector: reject non-ASCII bytes and U+FFFD.

    ``chunks`` are raw byte strings.  The check is independent of locale and
    compiler: the repaired diagnostic is pure ASCII, so every emitted byte must
    be < 128 and its UTF-8 decoding must contain no replacement character.
    """
    for raw in chunks:
        assert all(
            byte < 128 for byte in raw
        ), f"non-ASCII byte in native CLI diagnostic: {raw!r}"
        assert "\ufffd" not in raw.decode(
            "utf-8", errors="replace"
        ), "UTF-8 replacement character in CLI diagnostic"


def _cli(tmp_path, log_file):
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "BNG2.pl").write_text("# never used by native execution\n")
    model = tmp_path / "model.bngl"
    model.write_text(MODEL)
    return BNGCLI(
        str(model),
        str(tmp_path / "output"),
        str(reference),
        log_file=log_file,
        suppress=True,
    )


def test_detector_negative_control_rejects_damaged_output():
    """Negative control: the detector must reject both historical failures.

    * the UTF-8 bytes of the original U+2014 em dash (valid on macOS/Linux);
    * the single MSVC local-codepage byte (0x97 in cp1252, invalid UTF-8).
    """
    utf8_emdash = b"[bng_cpp] quit() \xe2\x80\x94 stopping action processing\n"
    mscodepage_emdash = b"[bng_cpp] quit() \x97 stopping action processing\n"
    with pytest.raises(AssertionError):
        _assert_clean_diagnostic([utf8_emdash])
    with pytest.raises(AssertionError):
        _assert_clean_diagnostic([mscodepage_emdash])
    # The repaired ASCII text is accepted by the same detector.
    _assert_clean_diagnostic([(EXPECTED_QUIT + "\n").encode("ascii")])


def test_native_cli_quit_diagnostic_is_ascii_bytes(tmp_path):
    if not BINARY.is_file():
        pytest.skip("native bng_cpp binary not built")
    source = tmp_path / "quit.bngl"
    source.write_text(MODEL, encoding="utf-8")
    result = subprocess.run(
        [str(BINARY), "--verbose", str(source)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    lines = (result.stdout + result.stderr).splitlines()
    quit_lines = [line for line in lines if b"quit()" in line]
    assert quit_lines, "verbose quit diagnostic was not emitted"
    _assert_clean_diagnostic(quit_lines)
    assert any(EXPECTED_QUIT.encode("ascii") in line for line in quit_lines)


def test_consumer_log_and_capture_byte_fidelity(tmp_path):
    """Exercise the real subprocess/log consumer that failed on Windows.

    ``BNGCLI`` routes through ``execute_native`` which decodes captured native
    output with ``errors="replace"`` and writes the same text to the requested
    log.  With the ASCII repair both paths carry the diagnostic verbatim.
    """
    log = tmp_path / "native.log"
    cli = _cli(tmp_path, str(log))
    cli.run()
    assert cli.result.process_return == 0
    log_text = log.read_text(encoding="utf-8")
    captured = "\n".join(cli.result.output)
    assert "\ufffd" not in log_text
    assert "\ufffd" not in captured
    assert log_text.rstrip("\n") == captured, "log file and captured output diverged"
    assert any(EXPECTED_QUIT in line for line in captured.splitlines())
