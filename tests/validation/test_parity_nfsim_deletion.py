"""Deletion scope qualification; native trajectory parity is a separate claim."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from tests.validation import compare, oracle_nfsim, runner
from tests.validation.strict import require_oracle

CASES = {
    "whole_species": "A(b!1).B(a!1) -> 0 k",
    "named_molecules": "A(b!1).B(a!1) -> 0 k DeleteMolecules",
    "partial_keyword": "A(b!1).B(a!1) -> B(a) k DeleteMolecules",
    "with_catalyst": "A(b!1).B(a!1) + D() -> D() k",
}


def model_source(rule: str) -> str:
    return f"""begin model
begin parameters
    k 1
end parameters
begin molecule types
    A(b)
    B(a,c)
    C(b)
    D()
end molecule types
begin seed species
    A(b!1).B(a!1,c!2).C(b!2) 100
    D() 1
end seed species
begin observables
    Molecules OA A()
    Molecules OB B()
    Molecules OC C()
    Molecules OD D()
end observables
begin reaction rules
    delete: {rule}
end reaction rules
end model
"""


def _assert_scope(name: str, data, columns):
    counts = {column: data[:, index] for index, column in enumerate(columns)}
    assert set(counts) == {"time", "OA", "OB", "OC", "OD"}
    assert counts["OA"][0] == 100
    assert counts["OA"][-1] < 100, "positive-time run fired no deletion"
    assert np.all(counts["OD"] == 1), "the catalyst must survive"
    if name == "partial_keyword":
        assert np.all(counts["OB"] == 100)
    else:
        np.testing.assert_array_equal(counts["OB"], counts["OA"])
    if name in {"named_molecules", "partial_keyword"}:
        assert np.all(counts["OC"] == 100), "unnamed context must survive"
    else:
        np.testing.assert_array_equal(counts["OC"], counts["OA"])


@pytest.mark.nf
@pytest.mark.parametrize("name", CASES)
def test_direct_and_xml_preserve_deletion_scope(name, api, tmp_path, monkeypatch):
    import bionetgen

    source = tmp_path / f"{name}.bngl"
    source.write_text(model_source(CASES[name]))
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    direct = runner._result_to_trajectory(
        bionetgen.load(source).simulate(method="nf", t_end=2, n_steps=20, seed=7)
    )
    assert direct.construction_path == "direct"
    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    xml = runner._result_to_trajectory(
        bionetgen.load(source).simulate(method="nf", t_end=2, n_steps=20, seed=7)
    )
    assert xml.construction_path == "in-memory-xml"
    assert direct.columns == xml.columns
    np.testing.assert_array_equal(direct.data, xml.data)
    _assert_scope(name, direct.data, direct.columns)


def test_conditional_partial_deletion_declines_direct_construction(
    api, tmp_path, monkeypatch, capfd
):
    import bionetgen

    source = tmp_path / "conditional.bngl"
    source.write_text(model_source("A(b!1).B(a!1) -> B(a) k"))
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    with pytest.raises(
        RuntimeError, match="stage 'reaction rules'.*XML fallback disabled"
    ):
        bionetgen.load(source).simulate(method="nf", t_end=2, n_steps=20, seed=7)
    assert (
        "conditional partial pattern deletion is unsupported; requires DeleteMolecules"
        in capfd.readouterr().err
    )


@pytest.mark.nf
@pytest.mark.parametrize("name", CASES)
def test_independent_bng2_xml_native_oracle_preserves_deletion_scope(
    name, api, tmp_path
):
    # Both the BNGL-to-XML translator and executable are external inputs.
    # BNG3-generated XML cannot independently qualify its own translation.
    configured = os.environ.get("BNG2_PERL")
    require_oracle(
        bool(configured) and Path(configured).is_file(),
        "independent BNG2 XML translation requires explicit BNG2_PERL",
    )
    require_oracle(oracle_nfsim.nfsim_available(), "set independent NFSIM_BIN")
    source = tmp_path / f"{name}.bngl"
    source.write_text(model_source(CASES[name]) + "writeXML();\n")
    proc = subprocess.run(
        [os.environ.get("PERL", "perl"), configured, str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    xml = tmp_path / f"{name}.xml"
    assert xml.is_file(), "independent BNG2 produced no XML"
    gdat, error = oracle_nfsim.run_nfsim(
        xml, tmp_path / "native", t_end=2, n_steps=20, seed=7
    )
    assert gdat is not None, error
    data, columns = compare.parse_gdat(gdat)
    assert data is not None and columns is not None
    assert len(data) == 21
    _assert_scope(name, data, columns)
