"""Pinned native NFsim parity checks for #137 compartments and functions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np

from tests.validation import compare, oracle_nfsim
from tests.validation.strict import require_oracle

COMPARTMENT_MODEL = """begin model
begin parameters
  k_t 0.5
  k_bind 0.1
end parameters
begin compartments
  EC 3 2.0
  PM 2 1.0 EC
  CP 3 1.0 PM
end compartments
begin molecule types
  L(r)
  R(l)
end molecule types
begin seed species
  @EC:L(r) 40
  @PM:R(l) 20
end seed species
begin observables
  Molecules L_ec @EC:L(r)
  Molecules L_cp @CP:L(r)
  Molecules Bound_R R(l!+)@PM
  Molecules Bound_L_PM L(r!1)@PM.R(l!1)@PM
end observables
begin reaction rules
  transport: @EC:L(r) -> @CP:L(r) k_t
  bind: L(r)@EC + R(l)@PM -> L(r!1)@PM.R(l!1)@PM k_bind
end reaction rules
end model
"""

TFUN_GLOBAL_FUNCTION_MODEL = """begin model
begin parameters
  k0 1.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 50
  B() 0
end seed species
begin observables
  Molecules Atot A()
  Molecules Btot B()
end observables
begin functions
  f_rate() = tfun([0, 1, 2], [0.5, 1.5, 2.5], time)
  prod() = k0 + 0.1 * Atot
end functions
begin reaction rules
  A() -> B() f_rate()
  0 -> A() prod()
end reaction rules
end model
"""


def _require_bng2_xml(source_text: str, tmp_path: Path, stem: str) -> Path:
    configured = os.environ.get("BNG2_PERL")
    require_oracle(
        bool(configured) and Path(configured).is_file(),
        "independent BNG2 XML translation requires explicit BNG2_PERL",
    )
    assert configured is not None
    bng2_script = Path(configured).resolve()
    env = dict(os.environ, BNGPATH=str(bng2_script.parent))
    bngl = tmp_path / f"{stem}_oracle.bngl"
    bngl.write_text(source_text + "\nwriteXML({overwrite=>1})\n", encoding="utf-8")
    proc = subprocess.run(
        [
            os.environ.get("PERL", "perl"),
            str(bng2_script),
            "--outdir",
            str(tmp_path),
            str(bngl),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    xml_path = tmp_path / f"{stem}_oracle.xml"
    assert xml_path.is_file(), f"BNG2 produced no XML for {stem}"
    return xml_path


def _assert_direct_matches_native(
    source_text: str, api, tmp_path: Path, monkeypatch, stem: str, *, cb: bool = False
) -> None:
    require_oracle(
        oracle_nfsim.nfsim_available(), "native NFsim binary not found (set NFSIM_BIN)"
    )
    native = oracle_nfsim.nfsim_binary()
    assert native is not None
    xml_path = _require_bng2_xml(source_text, tmp_path, stem)
    native_out = tmp_path / f"{stem}_native.gdat"
    cmd = [
        str(native),
        "-xml",
        str(xml_path),
        "-o",
        str(native_out),
        "-sim",
        "2.0",
        "-oSteps",
        "10",
        "-seed",
        "7",
    ]
    if cb:
        cmd.append("-cb")
    proc = subprocess.run(
        cmd, cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    native_data, native_cols = compare.parse_gdat(native_out)
    assert native_data is not None and native_cols is not None

    bngl = tmp_path / f"{stem}_bng3.bngl"
    bngl.write_text(source_text, encoding="utf-8")
    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
    result = api.load(str(bngl)).simulate(
        method="nfcore", t_end=2.0, n_steps=10, seed=7
    )
    assert result.construction_path == "direct"
    bng3_cols = ["time", *list(result.observables)]
    bng3_data = np.column_stack(
        [np.asarray(result.time, dtype=float)]
        + [
            np.asarray(result.observables[col], dtype=float)
            for col in result.observables
        ]
    )
    diff = compare.compare_trajectories(
        native_data,
        native_cols,
        bng3_data,
        bng3_cols,
        rtol=0.0,
        atol=0.0,
        columns=compare.COLUMNS_EXACT,
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"NFsim parity mismatch [{stem}]: {diff.summary()}"


def test_nfsim_compartments_match_pinned_native_nfsim(api, tmp_path, monkeypatch):
    """Compare compartment hierarchy, transport, and binding against pinned NFsim."""
    _assert_direct_matches_native(
        COMPARTMENT_MODEL, api, tmp_path, monkeypatch, "compartments", cb=True
    )


def test_nfsim_tfun_and_global_function_match_pinned_native_nfsim(
    api, tmp_path, monkeypatch
):
    """Compare inline TFUN and global functions against pinned native NFsim."""
    _assert_direct_matches_native(
        TFUN_GLOBAL_FUNCTION_MODEL, api, tmp_path, monkeypatch, "tfun_global"
    )
