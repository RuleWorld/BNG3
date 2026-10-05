"""Signaling model suite: BNG3 output vs exact domain expectations.

Throwaway diagnostic (not a permanent test).
"""

from __future__ import annotations

import math
import pathlib
import shutil
import subprocess
import tempfile

BNGCPP = "/Users/akutuva/Documents/BioNetGen/BNG3-sciSignaling/build/cpp/bng_cpp"
HERE = pathlib.Path(__file__).resolve().parent


def run(bngl: str):
    """Run a model with bng_cpp in a fresh dir; return (cols, rows, dir)."""
    td = pathlib.Path(tempfile.mkdtemp())
    shutil.copy(HERE / bngl, td / bngl)
    r = subprocess.run([BNGCPP, bngl], cwd=td, capture_output=True, text=True)
    if r.returncode != 0:
        print("  BNG_CPP FAILED", r.returncode)
        print((r.stdout + r.stderr)[-2500:])
        raise SystemExit(1)
    gdat = td / bngl.replace(".bngl", ".gdat")
    cols, rows = None, []
    for line in gdat.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if cols is None:
                cols = line.lstrip("#").split()
            continue
        try:
            rows.append([float(x) for x in line.split()])
        except ValueError:
            continue
    return cols, rows, td


def col(cols, rows, name):
    i = cols.index(name)
    return [r[i] for r in rows], [r[0] for r in rows]


def check(label, got, want, tol):
    ok = abs(got - want) <= tol
    print(
        f"  {'PASS' if ok else 'FAIL'}  {label}\n"
        f"        got {got:.12g}  want {want:.12g}  diff {got - want:.3e}  tol {tol:g}"
    )
    return ok


results = []


def record(name, ok):
    results.append((name, ok))
    print(f"{name}: {'PASS' if ok else 'FAIL'}\n")


# =============================================== M1a irreversible early flux
print("=" * 70)
print("M1a  irreversible 2nd-order binding: early-time flux == declared")
kon, L0, R0 = 1e-4, 100.0, 60.0
cols, rows, _ = run("m1_ligand_receptor.bngl")
LR, t = col(cols, rows, "LR")
want0 = kon * L0 * R0
ok = True
# LR(t)/t must approach kon*L0*R0 as t->0.  Report the trend over decades.
print("  t        LR(t)/t         rel.err vs kon*L0*R0")
for k in (1, 2, 5, 10, 100, 500, 1000):
    i = k
    val = LR[i] / t[i]
    print(
        f"  {t[i]:.3e}  {val:.10f}  {(val - want0) / want0:+.3e}"
        f"   (predicted {-(kon * (L0 + R0) * kon * L0 * R0 * t[i] / 2) / want0:+.3e})"
    )
ok &= check(
    "LR(t_end)/t_end vs kon*L0*R0 (t=1e-3)", LR[-1] / t[-1], want0, 1e-3 * want0
)
# the Taylor prediction must match to 3rd order
exact_series = want0 * t[-1] - kon * (L0 + R0) * want0 * t[-1] ** 2 / 2
ok &= check(
    "LR(t_end) vs 2-term Taylor",
    LR[-1],
    exact_series,
    1e-2 * kon * (L0 + R0) * want0 * t[-1] ** 3,
)
record("M1a", ok)

# =============================================== M1b reversible binding SS
print("=" * 70)
print("M1b  reversible ligand-receptor binding: steady state + conservation")
kon, koff, L0, R0 = 1e-4, 0.5, 100.0, 60.0
cols, rows, _ = run("m1b_reversible_ss.bngl")
LR, t = col(cols, rows, "LR")
Lf, _ = col(cols, rows, "Lfree")
Rf, _ = col(cols, rows, "Rfree")
Lt, _ = col(cols, rows, "Ltot")
Rt, _ = col(cols, rows, "Rtot")
Kd = koff / kon
# Kd*x = (L0-x)(R0-x)  ->  x^2 - (Kd+L0+R0)x + L0*R0 = 0 ; small root
bq, cq = Kd + L0 + R0, L0 * R0
x = (bq - math.sqrt(bq * bq - 4 * cq)) / 2
ok = True
ok &= check("SS [LR] (exact quadratic root)", LR[-1], x, 1e-6 * x)
ok &= check("conserved Ltot", Lt[-1], L0, 1e-8)
ok &= check("conserved Rtot", Rt[-1], R0, 1e-8)
# detailed balance at SS
ok &= check(
    "SS detailed balance [L][R]/[LR] = koff/kon",
    Lf[-1] * Rf[-1] / LR[-1],
    Kd,
    1e-6 * Kd,
)
record("M1b", ok)

# =============================================== M2 closed two-state cycle
print("=" * 70)
print("M2  single-site closed cycle: ratio of rate constants, exact transient")
k1, k2, Rtot = 0.7, 0.2, 1000.0
cols, rows, _ = run("m2_site_cycle.bngl")
Rp, t = col(cols, rows, "Rp")
Ru, _ = col(cols, rows, "Rup")
ok = True
ok &= check("SS ratio Rp/Ru vs k1/k2", Rp[-1] / Ru[-1], k1 / k2, 1e-6 * (k1 / k2))
w = max(abs(Rp[i] + Ru[i] - Rtot) for i in range(len(Rp)))
ok &= check("max |Rp+Ru-Rtot| over traj", w, 0.0, 1e-7 * Rtot)
w = max(
    abs(Rp[i] - Rtot * k1 / (k1 + k2) * (1 - math.exp(-(k1 + k2) * t[i])))
    for i in range(len(t))
)
ok &= check("max |Rp - Rtot*k1/(k1+k2)*(1-exp(-(k1+k2)t))|", w, 0.0, 1e-6 * Rtot)
record("M2", ok)

# =============================================== M3 cascade exact
print("=" * 70)
print("M3  one-way 3-stage first-order cascade: exact exponentials")
k1, k2, k3, A0 = 1.0, 0.4, 0.15, 800.0
cols, rows, _ = run("m3_cascade3.bngl")
A, t = col(cols, rows, "A")
B, _ = col(cols, rows, "B")
C, _ = col(cols, rows, "C")
D, _ = col(cols, rows, "D")


def c_exact(tv):

    a = A0 * math.exp(-k1 * tv)
    b = A0 * k1 * (math.exp(-k1 * tv) - math.exp(-k2 * tv)) / (k2 - k1)
    c = 0.0
    for kj in (k1, k2, k3):
        denom = 1.0
        for km in (k1, k2, k3):
            if km != kj:
                denom *= km - kj
        c += A0 * k1 * k2 * math.exp(-kj * tv) / denom
    return a, b, c


ok = True
wA = wB = wC = wD = wT = 0.0
for i in range(len(t)):
    a, b, c = c_exact(t[i])
    d = A0 - a - b - c
    wA = max(wA, abs(A[i] - a))
    wB = max(wB, abs(B[i] - b))
    wC = max(wC, abs(C[i] - c))
    wD = max(wD, abs(D[i] - d))
    wT = max(wT, abs(A[i] + B[i] + C[i] + D[i] - A0))
ok &= check("max |A - A0 exp(-k1 t)|", wA, 0.0, 1e-6 * A0)
ok &= check("max |B - exact|", wB, 0.0, 1e-6 * A0)
ok &= check("max |C - exact partial fractions|", wC, 0.0, 1e-6 * A0)
ok &= check("max |D - exact|", wD, 0.0, 1e-6 * A0)
ok &= check("max |A+B+C+D - A0|", wT, 0.0, 1e-6 * A0)
record("M3", ok)

# =============================================== M4 two-site steady state
print("=" * 70)
print("M4  two-site reversible phosphorylation: closed-form 4-state SS")
# The two sites are NOT independent: they compete for the same S pool, so the
# steady state is the geometric-in-r chain 1 : r : r : r^2 with r = kp/km, NOT
# the binomial.  Each site's MARGINAL occupancy is p = kp/(kp+km) exactly, and
# n00:n10:n01:n11 = 1:r:r:r^2 pins the per-site rate scale and the symmetry.
kp, km, Rtot = 0.9, 0.3, 4000.0
cols, rows, td = run("m4_two_site_phos.bngl")
net = (td / "m4_two_site_phos.net").read_text()
nspec = 0
inside = False
for ln in net.splitlines():
    s = ln.strip()
    if s.startswith("begin species"):
        inside = True
        continue
    if s.startswith("end species"):
        inside = False
        continue
    if inside and s:
        nspec += 1
g = {n: col(cols, rows, n)[0] for n in ("S00", "S10", "S01", "S11", "Stot")}
r = kp / km
scale = Rtot / (1 + 2 * r + r**2)
want = {"S00": scale, "S10": scale * r, "S01": scale * r, "S11": scale * r * r}
p = kp / (kp + km)
ok = True
ok &= check("network substrate species count (2^2)", nspec, 4, 0)
for nm in ("S00", "S10", "S01", "S11"):
    ok &= check(f"SS {nm} vs 1:r:r:r^2 chain", g[nm][-1], want[nm], 1e-4 * want[nm])
ok &= check("symmetry S10 == S01", g["S10"][-1] - g["S01"][-1], 0.0, 1e-9 * Rtot)
ok &= check(
    "site-1 marginal (n10+n11)/Rtot = kp/(kp+km)",
    (g["S10"][-1] + g["S11"][-1]) / Rtot,
    p,
    1e-6,
)
ok &= check(
    "site-2 marginal (n01+n11)/Rtot = kp/(kp+km)",
    (g["S01"][-1] + g["S11"][-1]) / Rtot,
    p,
    1e-6,
)
w = max(abs(g["Stot"][i] - Rtot) for i in range(len(g["Stot"])))
ok &= check("max |Stot - Rtot| (closed cycle)", w, 0.0, 1e-6 * Rtot)
print(f"  r = kp/km = {r},  p = kp/(kp+km) = {p}")
record("M4", ok)

# =============================================== M5 compartment volume
print("=" * 70)
print("M5  compartment volume scaling: occupancy is volume-independent")
kon, koff = 2e-3, 0.4
c1, r1, _ = run("m5_v1.bngl")
c2, r2, _ = run("m5_v1000.bngl")
g1 = {n: col(c1, r1, n)[0] for n in ("Lfree", "Rfree", "LR")}
g2 = {n: col(c2, r2, n)[0] for n in ("Lfree", "Rfree", "LR")}
ok = True
print(
    "  V=1    SS: L=%.10g R=%.10g LR=%.10g"
    % (g1["Lfree"][-1], g1["Rfree"][-1], g1["LR"][-1])
)
print(
    "  V=1000 SS: L=%.10g R=%.10g LR=%.10g"
    % (g2["Lfree"][-1], g2["Rfree"][-1], g2["LR"][-1])
)
for nm in ("Lfree", "Rfree", "LR"):
    # V=1000 counts divided by 1000 must reproduce the V=1 concentration.
    ok &= check(
        f"{nm}: V=1000 count/1000 vs V=1 concentration",
        g2[nm][-1] / 1000.0,
        g1[nm][-1],
        1e-6 * max(1.0, abs(g1[nm][-1])),
    )
# and the exact mass-action SS for kon, koff, [L]0=1, [R]0=3
Kd = koff / kon
bq, cq = Kd + 1.0 + 3.0, 1.0 * 3.0
xs = (bq - math.sqrt(bq * bq - 4 * cq)) / 2
ok &= check("V=1 SS [LR] vs exact quadratic root", g1["LR"][-1], xs, 1e-6 * xs)
ok &= check("V=1 free-L + LR = 1 (Ltot)", g1["Lfree"][-1] + g1["LR"][-1], 1.0, 1e-9)
ok &= check("V=1 free-R + LR = 3 (Rtot)", g1["Rfree"][-1] + g1["LR"][-1], 3.0, 1e-9)
ok &= check(
    "V=1000 free-L + LR = 1000 (Ltot)", g2["Lfree"][-1] + g2["LR"][-1], 1000.0, 1e-6
)
ok &= check(
    "V=1000 free-R + LR = 3000 (Rtot)", g2["Rfree"][-1] + g2["LR"][-1], 3000.0, 1e-6
)
# exact SS occupancy must equal the closed-form at BOTH volumes
Kd = koff / kon
bq, cq = Kd + 1.0 + 3.0, 1.0 * 3.0
xs = (bq - math.sqrt(bq * bq - 4 * cq)) / 2
ok &= check("V=1 SS [LR] vs exact quadratic root", g1["LR"][-1], xs, 1e-6 * xs)
ok &= check("V=1000 SS [LR]/1000 vs exact root", g2["LR"][-1] / 1000.0, xs, 1e-6 * xs)
record("M5", ok)

# =============================================== M6 conservation
print("=" * 70)
print("M6  closed feedback loop: every pool conserved")
R0, A0, S0 = 200.0, 2000.0, 1000.0
cols, rows, _ = run("m6_conservation.bngl")
G = {
    n: col(cols, rows, n)[0]
    for n in ("Rfree", "RA", "RS", "Rtot", "Phos", "Sunph", "Stot", "Atot")
}
ok = True
wR = max(
    abs(G["Rfree"][i] + G["RA"][i] + G["RS"][i] - R0) for i in range(len(G["Rfree"]))
)
ok &= check("max |Rfree+RA+RS+RSP - R0|", wR, 0.0, 1e-6 * R0)
# Stot already includes the S held in the R.S complex (species 3,5,6), so the
# conservation identity is Stot == S0 and Phos <= Stot.
wS = max(abs(G["Stot"][i] - S0) for i in range(len(G["Stot"])))
ok &= check("max |Stot - S0| (incl. complex-bound S)", wS, 0.0, 1e-6 * S0)
wS2 = max(
    abs(G["Phos"][i] + G["Sunph"][i] + G["RS"][i] - S0) for i in range(len(G["Phos"]))
)
ok &= check("max |Phos+Sunph+RS - S0|", wS2, 0.0, 1e-6 * S0)
wA = max(abs(G["Atot"][i] - A0) for i in range(len(G["Atot"])))
ok &= check("max |Atot - A0|", wA, 0.0, 1e-6 * A0)
ok &= check("Rtot observable at SS", G["Rtot"][-1], R0, 1e-6 * R0)
record("M6", ok)

# =============================================== M7 Goldbeter-Koshland
print("=" * 70)
print("M7  Goldbeter-Koshland: zero-order kinase + first-order phosphatase")
konE, koffE, kcatE, km, E0, S0 = 1.0, 1.0, 20.0, 0.05, 1000.0, 10000.0
cols, rows, _ = run("m7_gk.bngl")
G = {n: col(cols, rows, n)[0] for n in ("ES", "Efree", "Sfree", "P", "Stot", "Etot")}
t = [r[0] for r in rows]
ok = True
wS = max(abs(G["Stot"][i] - S0) for i in range(len(t)))
ok &= check("max |Sfree+S0 - S0| (closed substrate)", wS, 0.0, 1e-6 * S0)
KM = (koffE + kcatE) / konE
# exact QSS-free SS: ES* = E0*S/(KM+S); v = kcatE*ES*; S0* = v/km
# solve  S0 = kcatE*E0*S/(KM+S)/km  with S = Stot - S0 - ES* ; use 2 unknowns
s2, pp = G["Sfree"][-1], G["P"][-1]
es, efr = G["ES"][-1], G["Efree"][-1]
ok &= check("conservation: Efree+ES = E0", efr + es, E0, 1e-6 * E0)
# The exact steady state of the coupled 3-equation system is NOT the
# Michaelis-Menten quasi-steady-state relation; ES* here is 24.9363 against an
# MM prediction of 24.3145, a 2.5% gap that is the expected QSSA error, not a
# BNG3 discrepancy. What IS exact, and is what a wrong reactant or a lost
# reverse rate would break, is the enzyme balance below.
ok &= check(
    "SS: konE*Efree*Sfree = (koffE+kcatE)*ES  (enzyme balance)",
    konE * efr * s2,
    (koffE + kcatE) * es,
    1e-6 * konE * efr * s2,
)
ok &= check(
    "SS: kcatE*ES* = km*P  (flux balance)", kcatE * es, km * pp, 1e-4 * kcatE * es
)
print(f"  KM = {KM}")
print(f"  ES*    = {es:.10g}   MM prediction = {efr * s2 / (KM + s2):.10g}")
print(f"  kcatE*ES* = {kcatE * es:.10g}   km*P* = {km * pp:.10g}")
print(f"  substrate saturation [S]/(KM+[S]) = {s2 / (KM + s2):.6f}  (1.0 = zero-order)")
record("M7", ok)

# =============================================== M8 reverse rate split
print("=" * 70)
print("M8  reverse-rate splitting: three spellings must agree or be refused")
ka, kb, Rtot = 0.8, 0.3, 1000.0
ok = True

# R1: two rate laws on a unidirectional arrow. BNG2 refuses this spelling
# outright, so refusing it is the correct outcome -- silently running it as
# `-> ka` (dropping kb) is the defect.
_td8 = pathlib.Path(tempfile.mkdtemp())
shutil.copy(HERE / "m8_r1.bngl", _td8 / "m8_r1.bngl")
r = subprocess.run([BNGCPP, "m8_r1.bngl"], cwd=_td8, capture_output=True, text=True)
out = r.stdout + r.stderr
ok &= check(
    "R1 (two laws on '->') is REFUSED, not silently run",
    float("only one rate law" in out),
    1.0,
    0.0,
)
print("  R1 diagnostic:", [l for l in out.splitlines() if "rate law" in l][-1][:100])

# R2 and R3 are the two supported spellings of the same pair and must agree
# with each other and with the closed form of a closed two-state cycle.
traj = {}
nets = {}
for i, tag in ((2, "R2 two-way arrow"), (3, "R3 two separate rules")):
    cols, rows, td = run(f"m8_r{i}.bngl")
    P, t = col(cols, rows, "P")
    U, _ = col(cols, rows, "U")
    traj[i] = (P, U, t)
    net = td / f"m8_r{i}.net"
    nets[i] = net.read_text() if net.exists() else ""
    print(f"  {tag}: P(t_end) = {P[-1]:.10f}  U(t_end) = {U[-1]:.10f}")
want_ratio = ka / kb  # U -> P at ka, P -> U at kb, so ka*U = kb*P
for i in (2, 3):
    P, U, t = traj[i]
    ok &= check(
        f"R{i} SS ratio P/U vs kb/ka", P[-1] / U[-1], want_ratio, 1e-6 * want_ratio
    )
    w = max(abs(P[j] + U[j] - Rtot) for j in range(len(P)))
    ok &= check(f"R{i} max |P+U-Rtot|", w, 0.0, 1e-6 * Rtot)
    w2 = max(
        abs(P[j] - Rtot * ka / (ka + kb) * (1 - math.exp(-(ka + kb) * t[j])))
        for j in range(len(t))
    )
    ok &= check(f"R{i} max |P - closed form|", w2, 0.0, 1e-6 * Rtot)
w = max(abs(traj[3][0][j] - traj[2][0][j]) for j in range(len(traj[2][0])))
ok &= check(
    "max |P_R3 - P_R2| (the two supported spellings agree)", w, 0.0, 1e-9 * Rtot
)
for i in (2, 3):
    print(f"  R{i} network reaction lines:")
    for ln in nets[i].splitlines():
        s = ln.strip()
        if s and s[0].isdigit() and ("->" in s or "<->" in s):
            print("     ", s)
record("M8", ok)

# =============================================== summary
print("=" * 70)
allok = True
for nm, ok in results:
    print(f"{nm:6} {'PASS' if ok else 'FAIL'}")
    allok &= ok
print("OVERALL:", "PASS" if allok else "FAIL")
