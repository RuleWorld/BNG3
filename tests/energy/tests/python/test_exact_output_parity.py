from pathlib import Path
from scripts import exact_output_parity as parity


def test_same_bytes_pass(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"abc")
    b.write_bytes(b"abc")
    assert parity.compare(a, b)["passed"]


def test_different_bytes_fail_even_same_size(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"abc")
    b.write_bytes(b"abd")
    assert not parity.compare(a, b)["passed"]
