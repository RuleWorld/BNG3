"""Regression tests for BNG2 bifurcate continuation and per-observable .scan parity."""

from __future__ import annotations

import math
from pathlib import Path

import bionetgen._bionetgen_cpp as cpp

BASE_MODEL = """begin model
begin parameters
  kf 0.5
  kr 0.1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() <-> B() kf, kr
end reaction rules
end model
generate_network({overwrite=>1})
"""


def _analytic_two_state(a0: float, kf: float, kr: float, dt: float) -> float:
    """Exact closed-form A(t) for A <-> B with total A+B=100."""
    s = kf + kr
    a_eq = 100.0 * kr / s
    return a_eq + (a0 - a_eq) * math.exp(-s * dt)


def _parse_scan(path: Path) -> tuple[list[str], list[list[float]]]:
    lines = [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    header = lines[0].lstrip("#").split()
    rows = [[float(tok) for tok in ln.split()] for ln in lines[1:]]
    return header, rows


def test_bifurcate_carries_state_and_writes_per_observable_scan(tmp_path: Path):
    src = tmp_path / "probe.bngl"
    src.write_text(
        BASE_MODEL
        + 'bifurcate({parameter=>"kf",par_min=>0.1,par_max=>0.5,n_scan_pts=>3,method=>"ode",t_end=>5,n_steps=>5})\n',
        encoding="utf-8",
    )
    model = cpp.parse_file(str(src))
    cpp.execute(model, str(src), False)

    scan_a = tmp_path / "probe_bifurcation_A_obs.scan"
    scan_b = tmp_path / "probe_bifurcation_B_obs.scan"
    assert scan_a.is_file()
    assert scan_b.is_file()
    assert (tmp_path / "probe_bifurcation.gdat").is_file()

    header, rows = _parse_scan(scan_a)
    assert header == ["kf", "A_obs_fwd", "A_obs_bwd"]
    assert len(rows) == 3

    # Exact closed-form continuation (reset_conc=0 across forward -> backward)
    kfs = [0.1, 0.3, 0.5]
    a = 100.0
    fwd = []
    for kf in kfs:
        a = _analytic_two_state(a, kf, 0.1, 5.0)
        fwd.append(a)
    bwd_rev = []
    for kf in reversed(kfs):
        a = _analytic_two_state(a, kf, 0.1, 5.0)
        bwd_rev.append(a)
    bwd = list(reversed(bwd_rev))

    for i, kf in enumerate(kfs):
        assert math.isclose(rows[i][0], kf, rel_tol=1e-7)
        assert math.isclose(rows[i][1], fwd[i], rel_tol=1e-5, abs_tol=1e-6)
        assert math.isclose(rows[i][2], bwd[i], rel_tol=1e-5, abs_tol=1e-6)


def test_bifurcate_par_scan_vals_and_prefix_suffix(tmp_path: Path):
    src = tmp_path / "probe.bngl"
    src.write_text(
        BASE_MODEL
        + 'bifurcate({parameter=>"kf",par_scan_vals=>[0.1,0.4],prefix=>"custom",suffix=>"s1",method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    model = cpp.parse_file(str(src))
    cpp.execute(model, str(src), False)

    scan_a = tmp_path / "custom_s1_bifurcation_A_obs.scan"
    assert scan_a.is_file()
    header, rows = _parse_scan(scan_a)
    assert header == ["kf", "A_obs_fwd", "A_obs_bwd"]
    assert [round(r[0], 4) for r in rows] == [0.1, 0.4]
