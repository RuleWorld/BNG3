from pathlib import Path
from scripts import compare_numeric_tables as cmp


def test_whitespace_tables_compare_exactly(tmp_path: Path):
    a = tmp_path / "a.gdat"
    b = tmp_path / "b.gdat"
    text = "time A B\n0 1 2\n1 3 4\n"
    a.write_text(text)
    b.write_text(text)
    assert cmp.compare(a, b)["passed"]


def test_csv_supported(tmp_path: Path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("time,A\n0,1\n")
    b.write_text("time,A\n0,1.0000001\n")
    assert cmp.compare(a, b, rtol=1e-6)["passed"]


def test_header_mismatch_fails(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("time A\n0 1\n")
    b.write_text("time B\n0 1\n")
    assert not cmp.compare(a, b)["passed"]


def test_numeric_difference_reports_location(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("time A\n0 1\n")
    b.write_text("time A\n0 2\n")
    r = cmp.compare(a, b)
    assert not r["passed"]
    assert r["failures"][0]["column"] == "A"


def test_nonfinite_mismatch_fails_explicitly(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("time A\n0 inf\n")
    b.write_text("time A\n0 1\n")
    r = cmp.compare(a, b)
    assert not r["passed"]
    assert r["failures"][0]["kind"] == "nonfinite"
