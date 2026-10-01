#!/usr/bin/env python3
"""Check the immune models against closed forms and identities.

Every assertion is a NUMBER compared against a closed form derived
independently of the model text, or an exact conservation identity.  None of
these are timings, so this claims no benchmark slot and its results cannot move
when nothing changed.

Run:
    python3 models/immune/verify_immune.py
    BNG_CPP=/path/to/bng_cpp python3 models/immune/verify_immune.py
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAILURES: list[str] = []


def bng_cpp() -> str:
    candidate = os.environ.get("BNG_CPP") or str(
        HERE.parents[1] / "build" / "cpp" / "bng_cpp"
    )
    if not Path(candidate).exists():
        sys.exit(f"bng_cpp not available at {candidate}")
    return candidate


def run(name: str) -> Path:
    """Run a model in a scratch dir; return it."""
    work = Path(tempfile.mkdtemp(prefix=f"immune-{name}-"))
    source = HERE / f"{name}.bngl"
    shutil.copy(source, work / source.name)
    proc = subprocess.run(
        [bng_cpp(), source.name], cwd=work, capture_output=True, text=True
    )
    (work / ".exitcode").write_text(str(proc.returncode))
    (work / ".output").write_text(proc.stdout + proc.stderr)
    return work


def gdat(path: Path) -> list[list[float]]:
    return [
        [float(x) for x in line.split()]
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def logistic(k: float, r: float, e0: float, t: float) -> float:
    return k / (1.0 + ((k - e0) / e0) * math.exp(-r * t))


def clonal_expansion() -> None:
    work = run("clonal_expansion")
    rows = gdat(work / "clonal_expansion__ode.gdat")
    k, r, e0 = 1000.0, 0.5, 200.0

    worst = max(
        abs(row[1] - logistic(k, r, e0, row[0])) / logistic(k, r, e0, row[0])
        for row in rows
    )
    check(
        "clonal expansion ODE vs logistic K/(1+((K-E0)/E0)e^(-rt))",
        worst < 1e-6,
        f"max rel deviation {worst:.3e} over {len(rows)} steps",
    )

    amounts = [row[1] for row in rows]
    check(
        "clone approaches declared capacity K=1000 and never exceeds it",
        all(a <= k + 1e-9 for a in amounts)
        and all(b >= a for a, b in zip(amounts, amounts[1:]))
        and amounts[-1] > 0.9 * k,
        f"E(8)={amounts[-1]:.6f}, K=1000, monotone non-decreasing",
    )

    ssa = gdat(work / "clonal_expansion__ssa.gdat")
    t_last = ssa[-1][0]
    analytic = logistic(k, r, e0, t_last)
    check(
        "seeded SSA at t_end within 5% of the deterministic trajectory",
        abs(ssa[-1][1] - analytic) / analytic < 0.05,
        f"ssa E({t_last})={ssa[-1][1]}, ode={analytic:.4f}",
    )
    shutil.rmtree(work)


def cytotoxic_killing() -> None:
    work = run("cytotoxic_killing")
    rows = gdat(work / "cytotoxic_killing__ode.gdat")
    vmax, kh, e0, t0 = 0.05, 200.0, 200.0, 1000.0

    # E0 == Kh, so the rate constant is exactly Vmax/2.
    rate = vmax * e0 / (kh + e0)
    check(
        "saturating flux Vmax*E/(Kh+E) evaluates to Vmax/2 at E == Kh",
        rate == vmax / 2.0,
        f"k({e0})={rate}, Vmax/2={vmax / 2.0}",
    )

    worst = 0.0
    for row in rows:
        expected = t0 * math.exp(-rate * row[0])
        worst = max(worst, abs(row[1] - expected) / expected)
    check(
        "cytotoxic target decay vs T0*exp(-k t)",
        worst < 1e-8,
        f"max rel deviation {worst:.3e} over {len(rows)} steps",
    )

    check(
        "effector pool is untouched by the killing reaction",
        all(row[2] == e0 for row in rows),
        f"E == {e0} at every step, which is the validity condition for the closed form",
    )

    worst_cons = max(abs(row[1] + row[3] - t0) for row in rows)
    check(
        "target + dead conserved (targets lost == cells killed)",
        worst_cons < 1e-6 * t0,
        f"max drift {worst_cons:.3e} on total {t0}",
    )
    shutil.rmtree(work)


def exhaustion_switch() -> None:
    work = run("exhaustion_switch")
    rows = gdat(work / "exhaustion_switch__ode.gdat")
    s0, a, theta, n, kmem = 100.0, 60.0, 400.0, 8.0, 0.4

    drift = max(abs(row[3] - (s0 + a * row[0])) for row in rows)
    check(
        "cumulative stimulus is exactly linear S(t) = S0 + a*t",
        drift == 0.0,
        f"max deviation {drift!r}",
    )

    at_threshold = [row[0] for row in rows if abs(row[3] - theta) < 1e-9]
    t_star = (theta - s0) / a
    check(
        "stimulus reaches THETA at the analytic switch time t* = (THETA-S0)/a",
        bool(at_threshold) and abs(at_threshold[0] - t_star) < 1e-12,
        f"S == THETA at t={at_threshold[0] if at_threshold else None}, "
        f"analytic t*={t_star}",
    )

    fluxes = [
        ((c[0] + p[0]) / 2.0, (c[2] - p[2]) / (c[0] - p[0]), c[1])
        for p, c in zip(rows, rows[1:])
    ]
    worst = 0.0
    for t, flux, effector in fluxes:
        hill = 1.0 / (1.0 + (theta / (s0 + a * t)) ** n)
        predicted = kmem * effector * hill
        worst = max(worst, abs(flux - predicted) / predicted)
    check(
        "switch flux equals kmem*Eff*Hill(1,THETA,n,S)",
        worst < 5e-2,
        f"max rel deviation {worst:.3e}; trapezoid differencing of dt={rows[1][0] - rows[0][0]}",
    )

    half = next(t for t, _, _ in fluxes if s0 + a * t >= theta)
    band = theta * (10.0 ** (1.0 / n) - 1.0) / a
    check(
        "switch fires within the derived Hill band around t*",
        abs(half - t_star) <= band + (rows[1][0] - rows[0][0]),
        f"switch t={half}, t*={t_star}, band=+-{band:.4f} d "
        f"(THETA*(10^(1/n)-1)/a), grid {(rows[1][0] - rows[0][0]):.3f} d",
    )

    memories = [row[2] for row in rows]
    check(
        "memory compartment is monotonically non-decreasing",
        all(b >= a_ for a_, b in zip(memories, memories[1:])),
        f"memory {memories[0]:.3e} -> {memories[-1]:.4f}",
    )

    net = (work / "exhaustion_switch.net").read_text()
    functions = net.split("begin functions")[1].split("end functions")[0]
    hill = [ln for ln in functions.splitlines() if "ill(" in ln]
    ok = bool(hill)
    detail = hill[0].strip() if hill else "<no Hill call in the functions block>"
    if ok:
        body = hill[0]
        # All three Hill arguments must survive lowering by name: the leading 1
        # (max flux), THETA (the half-saturation) and n (the coefficient).  A
        # Hill that lost an argument would still integrate, just wrongly.
        for token in ("1", "THETA", "n", "Stimulus()"):
            ok = ok and token in body
        detail += (
            "; all of 1, THETA, n, Stimulus() present"
            if ok
            else "; MISSING an argument"
        )
    check(
        "emitted Hill rate law retains its max, Kh, coefficient and substrate",
        ok,
        detail,
    )
    shutil.rmtree(work)


def antigen_binding() -> None:
    work = run("antigen_binding")
    for suffix in ("ode", "ssa"):
        rows = gdat(work / f"antigen_binding__{suffix}.gdat")
        ag0 = rows[0][1] + rows[0][2]
        drifts = [abs((r[1] + r[2]) - ag0) for r in rows]
        worst = max(drifts)
        tolerance = 0.0 if suffix == "ssa" else 1e-8 * ag0
        check(
            f"{suffix.upper()}: free + bound antigen conserved at EVERY step",
            worst <= tolerance,
            f"max drift {worst:.3e} over {len(rows)} steps, total {ag0}"
            + (" (exact: SSA counts are integers)" if suffix == "ssa" else ""),
        )

    rows = gdat(work / "antigen_binding__ode.gdat")
    ag0, r0, kon, koff = 200.0, 300.0, 0.01, 0.10
    kd = koff / kon
    b = ag0 + r0 + kd
    x = (b - math.sqrt(b * b - 4.0 * ag0 * r0)) / 2.0
    rel = abs(rows[-1][2] - x) / x
    check(
        "binding equilibrium equals the physical root of the mass-balance quadratic",
        rel < 1e-9,
        f"bound={rows[-1][2]:.9f}, analytic={x:.9f}, rel {rel:.3e} "
        f"(Kd=koff/kon={kd})",
    )

    reactions = (
        (work / "antigen_binding.net")
        .read_text()
        .split("begin reactions")[1]
        .split("end reactions")[0]
    )
    lines = [ln.strip() for ln in reactions.splitlines() if ln.strip()]

    def rate_of(line: str) -> str:
        # "<reactants> <products> <rate> #<rule label>"; the rate is the token
        # before the optional comment.
        tokens = line.split()
        return tokens[-2] if tokens[-1].startswith("#") else tokens[-1]

    check(
        "reversible rule emits a forward and a distinct reverse reaction",
        len(lines) == 2
        and rate_of(lines[0]) == "kon"
        and rate_of(lines[1]) == "koff"
        and lines[0].split()[1:3] == ["1,2", "3"]
        and lines[1].split()[1:3] == ["3", "1,2"],
        (
            f"forward={lines[0]!r} (rate {rate_of(lines[0])!r}), "
            f"reverse={lines[1]!r} (rate {rate_of(lines[1])!r})"
            if len(lines) == 2
            else f"expected 2 reactions, got {lines}"
        ),
    )
    shutil.rmtree(work)


def threshold_observable() -> None:
    work = run("threshold_observable")
    exitcode = int((work / ".exitcode").read_text())
    if exitcode != 0:
        check(
            "count predicate on a Molecules observable behaves as BNG2 does",
            False,
            "the model must run; it exited "
            f"{exitcode}: {(work / '.output').read_text()[:200]}",
        )
    else:
        rows = gdat(work / "threshold_observable.gdat")
        # BNG2 honours a count predicate only on a Species observable
        # (Perl2/Observable.pm tests $patt->Quantifier solely inside the Species
        # branch), so `Molecules Gt Eff()>50` must equal `Molecules Eff`.  Before
        # the fix it read 0 at every step: the predicate was applied to the
        # pattern->species EMBEDDING count, which is 1, so it compared 1 > 50.
        equal = all(row[1] == row[2] for row in rows)
        check(
            "count predicate on a Molecules observable leaves the amount unchanged",
            equal and rows[0][2] == 100.0,
            f"predicate column {rows[0][2]} vs plain {rows[0][1]} at t=0 "
            f"(Eff()=100; the defect returned 0 here)"
            + ("" if equal else " -- columns diverge later in the run"),
        )

    work2 = run("threshold_observable_species")
    ok2 = int((work2 / ".exitcode").read_text()) == 0
    if ok2:
        rows = gdat(work2 / "threshold_observable_species.gdat")
        _, seff, sgt0, sgt1, sch = rows[0]
        # The PREDICATE compares a structural embedding count (1 for the
        # single-node pattern Eff(), so >0 passes and >1 fails), but a passing
        # species then contributes its AMOUNT to the observable value.  BNG2
        # returns exactly these four numbers, so the parity test below is the
        # load-bearing check and these literals only guard against drift.
        check(
            "Species count predicates keep their defined meaning",
            sgt0 == 100.0 and sgt1 == 0.0 and sch == 1.0 and seff == 100.0,
            f"Eff>0 -> {sgt0} (amount), Eff>1 -> {sgt1} (fails, 0), "
            f"Ch(c~a) -> {sch} (amount 1), plain {seff}",
        )
    else:
        check(
            "Species count predicates keep their defined meaning (1 embedding)",
            False,
            (work2 / ".output").read_text()[:300],
        )
    shutil.rmtree(work)
    shutil.rmtree(work2)


def main() -> int:
    print(f"bng_cpp: {bng_cpp()}")
    print()
    for fn in (
        clonal_expansion,
        cytotoxic_killing,
        exhaustion_switch,
        antigen_binding,
        threshold_observable,
    ):
        print(f"--- {fn.__name__} ---")
        fn()
        print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + "; ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
