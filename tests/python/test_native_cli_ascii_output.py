"""Native CLI diagnostics must be ASCII-safe across compilers.

The Python parent captures native CLI output with a UTF-8 decoder. A non-ASCII
emitter in the C++ log string is mangled to U+FFFD by compilers using a local
execution charset (notably MSVC without /utf-8), which breaks log-file fidelity
and makes the captured output differ from the written log. Keep emitted
diagnostics ASCII; this pins the previously broken quit() message.
"""

from pathlib import Path
import subprocess

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


def test_native_cli_quit_diagnostic_is_ascii(tmp_path):
    if not BINARY.is_file():
        import pytest

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
    for line in quit_lines:
        assert all(
            byte < 128 for byte in line
        ), f"non-ASCII byte in native CLI diagnostic: {line!r}"
        assert b"\xef\xbf\xbd" not in line, "UTF-8 replacement char in CLI output"
