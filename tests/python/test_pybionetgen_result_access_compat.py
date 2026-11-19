"""Differential case for #171: PyBioNetGen public result access.

Selected rows: ``py.core.tools.result.BNGResult`` and its public ``load``,
``find_dat_files`` and ``load_results`` methods (result-access surface).

Installed-environment differential: the same hand-written ``.gdat``/``.cdat``/
``.scan`` folder was passed through the public ``BNGResult`` entry points in
separate clean venvs. Pinned PyBioNetGen 28bf351 (distribution 0.8.7) and the
BNG3 3.0.0a1 wheel produced byte-identical behavioral snapshots for folder
loading, extension filtering, direct-file loading, explicit ``folder_path``
methods, indexing/iteration and both edge cases below; only provenance fields
(interpreter, package path, version) differed. Raw snapshots:
``/tmp/pycompat_case/{ref,bng3_fixed}_result_access.json``.

These tests retain that verified contract so the rows stay covered.

Why existing tests miss it: ``tests/python/test_pybionetgen_differential_behaviors.py``
only loads a single ``.gdat`` produced by a real run and a folder from that
run. It never exercises mixed-extension folders, the ``ext`` filter, direct
``.scan`` files, explicit ``folder_path`` arguments, or malformed/unknown
files.
"""

from __future__ import annotations

import numpy as np
import pytest

from bionetgen.core.exc import BNGFileError
from bionetgen.core.tools.result import BNGResult


def _write_dat(folder, name, header, rows):
    path = folder / name
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def result_folder(tmp_path):
    _write_dat(tmp_path, "a.gdat", "# time A_tot", ["0 10", "1 5", "2 2.5"])
    _write_dat(tmp_path, "b.cdat", "# time B_count", ["0 3", "1 4"])
    _write_dat(tmp_path, "c.scan", "# k A_tot", ["0.5 10", "1.0 20"])
    _write_dat(tmp_path, "ignored.txt", "# time X", ["0 1"])
    return tmp_path


def test_folder_loading_and_extension_filter(result_folder):
    result = BNGResult(str(result_folder))

    assert sorted(result.gdats) == ["a"]
    assert sorted(result.cdats) == ["b"]
    assert sorted(result.scans) == ["c"]
    assert sorted(result.gnames) == ["a"]
    assert sorted(result.cnames) == ["b"]
    assert sorted(result.snames) == ["c"]

    gdat = result.gdats["a"]
    assert gdat.dtype.names == ("time", "A_tot")
    np.testing.assert_allclose(gdat["A_tot"], [10.0, 5.0, 2.5])
    np.testing.assert_allclose(result.scans["c"]["k"], [0.5, 1.0])

    assert sorted(str(x) for x in result) == ["a"]
    np.testing.assert_allclose(result[0]["time"], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(result["a"]["A_tot"], [10.0, 5.0, 2.5])
    assert sorted(result.__repr__().splitlines()) == [
        "cdats from 1 models: b ",
        "gdats from 1 models: a ",
        "scans from 1 models: c ",
    ]

    filtered = BNGResult(str(result_folder), ext="cdat")
    assert sorted(filtered.gdats) == []
    assert sorted(filtered.cdats) == ["b"]
    assert sorted(filtered.scans) == []


def test_direct_gdat_and_scan_paths(result_folder):
    gdat = BNGResult(str(result_folder / "a.gdat"))
    assert gdat.file_name == "a"
    assert gdat.file_extension == ".gdat"
    np.testing.assert_allclose(gdat.gdats["a"]["time"], [0.0, 1.0, 2.0])

    # Pinned contract: a direct .scan file is dispatched to load(), which
    # stores the array in gdats; scans stays empty for the direct-path form.
    scan = BNGResult(str(result_folder / "c.scan"))
    assert scan.file_name == "c"
    assert scan.file_extension == ".scan"
    assert sorted(scan.gdats) == ["c"]
    assert sorted(scan.scans) == []
    np.testing.assert_allclose(scan.gdats["c"]["A_tot"], [10.0, 20.0])


def test_explicit_folder_path_methods(result_folder):
    result = BNGResult()
    result.find_dat_files(folder_path=str(result_folder))
    result.load_results(folder_path=str(result_folder))

    assert sorted(result.gdats) == ["a"]
    assert sorted(result.cdats) == ["b"]
    assert sorted(result.scans) == ["c"]


def test_no_header_raises_bngfile_error(tmp_path):
    bad = tmp_path / "bad.gdat"
    bad.write_text("0 1\n1 2\n", encoding="utf-8")

    with pytest.raises(BNGFileError, match="No header line that starts with #"):
        BNGResult(str(bad))


def test_unknown_extension_direct_path_loads_nothing(result_folder):
    result = BNGResult(str(result_folder / "ignored.txt"))

    assert result.file_extension == ".txt"
    assert result.gdats.get("ignored") is None
