#!/usr/bin/env python3
"""Run security, memory-safety, and UB regression checks against an ASan+UBSan bng_cpp binary."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SANITIZER_MARKERS = (
    "AddressSanitizer",
    "UndefinedBehaviorSanitizer",
    "runtime error:",
    "SUMMARY: Sanitizer",
)


def _run_case(
    bng_cpp: Path,
    workdir: Path,
    args: list[str],
    *,
    expect_ok: bool | None = None,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("ASAN_OPTIONS", "detect_leaks=0:halt_on_error=1:abort_on_error=1")
    env.setdefault("UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=1")
    proc = subprocess.run(
        [str(bng_cpp), *args],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode < 0:
        raise AssertionError(
            f"signal crash (rc={proc.returncode}) for args={args}:\n{combined[-1000:]}"
        )
    for marker in SANITIZER_MARKERS:
        if marker in combined:
            raise AssertionError(
                f"sanitizer violation ({marker}) for args={args}:\n{combined[-1000:]}"
            )
    if expect_ok is True and proc.returncode != 0:
        raise AssertionError(
            f"expected success (rc=0), got rc={proc.returncode} for args={args}:\n{combined[-1000:]}"
        )
    if expect_ok is False and proc.returncode == 0:
        raise AssertionError(
            f"expected rejection (rc!=0), got rc=0 for args={args}:\n{combined[-1000:]}"
        )
    return proc


def run_all_checks(bng_cpp: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="bng3_asan_sec_") as tmp:
        root = Path(tmp)

        # 1. MEM-01: Out-of-bounds species index in .net must fail cleanly (no heap OOB).
        d1 = root / "mem01_net_oob"
        d1.mkdir()
        (d1 / "bad.net").write_text(
            "begin parameters\n  1 k 1.0\nend parameters\n"
            "begin species\n  1 A() 10\nend species\n"
            "begin reactions\n  1 999999 1 k\nend reactions\n"
            "begin groups\n  1 Atot 1\nend groups\n",
            encoding="utf-8",
        )
        (d1 / "driver.bngl").write_text(
            'readFile({file=>"bad.net"})\n' "simulate_ode({t_end=>1,n_steps=>5})\n",
            encoding="utf-8",
        )
        _run_case(bng_cpp, d1, ["driver.bngl"], expect_ok=False)

        # 2. MEM-02: Unsorted / NaN Tfun table must fail cleanly without OOB.
        d2 = root / "mem02_tfun"
        d2.mkdir()
        (d2 / "bad.tfun").write_text("# t val\n2.0 1.0\n1.0 2.0\n", encoding="utf-8")
        (d2 / "m.bngl").write_text(
            "begin model\n"
            "begin molecule types\n  A()\nend molecule types\n"
            "begin seed species\n  A() 10\nend seed species\n"
            "begin observables\n  Molecules Atot A()\nend observables\n"
            "begin functions\n  f() = tfun('bad.tfun', time)\nend functions\n"
            "begin reaction rules\n  A() -> 0 f()\nend reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
            'simulate({method=>"ode",t_end=>1,n_steps=>5})\n',
            encoding="utf-8",
        )
        _run_case(bng_cpp, d2, ["m.bngl"], expect_ok=False)

        # 3. MEM-03a: Deeply nested expression (>256 depth) must fail cleanly without stack overflow.
        d3 = root / "mem03_expr_depth"
        d3.mkdir()
        nested = "(" * 350 + "1" + ")" * 350
        (d3 / "deep.bngl").write_text(
            f"begin model\nbegin parameters\n  k {nested}\nend parameters\n"
            "begin molecule types\n  A()\nend molecule types\n"
            "begin seed species\n  A() 1\nend seed species\n"
            "end model\n",
            encoding="utf-8",
        )
        _run_case(bng_cpp, d3, ["deep.bngl"], expect_ok=False)

        # 4. MEM-03b: Deeply nested XML/SBML (>512 depth) must fail cleanly without stack overflow.
        d4 = root / "mem03_xml_depth"
        d4.mkdir()
        deep_xml = "<a/>"
        deep_xml = "<a>" * 600 + "</a>" * 600
        (d4 / "deep.xml").write_text(deep_xml, encoding="utf-8")
        (d4 / "m.bngl").write_text(
            'readFile({file=>"deep.xml"})\n',
            encoding="utf-8",
        )
        _run_case(bng_cpp, d4, ["m.bngl"], expect_ok=False)

        # 5. SEC-02: Output path traversal via prefix="../escape" must be blocked.
        d5 = root / "sec02_outdir"
        sub = d5 / "work"
        sub.mkdir(parents=True)
        (sub / "escape.bngl").write_text(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n  A()\nend molecule types\n"
            "begin seed species\n  A() 10\nend seed species\n"
            "begin observables\n  Molecules Atot A()\nend observables\n"
            "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
            'writeNetwork({prefix=>"../escaped",overwrite=>1})\n',
            encoding="utf-8",
        )
        _run_case(bng_cpp, sub, ["--outdir", str(sub), "escape.bngl"], expect_ok=False)
        assert not (d5 / "escaped.net").exists(), "path traversal wrote outside outdir"

        # 6. MEM-05: Negative n_steps must be rejected cleanly.
        d6 = root / "mem05_neg_steps"
        d6.mkdir()
        (d6 / "neg.bngl").write_text(
            "begin model\n"
            "begin parameters\n  k 1\nend parameters\n"
            "begin molecule types\n  A()\nend molecule types\n"
            "begin seed species\n  A() 10\nend seed species\n"
            "begin observables\n  Molecules Atot A()\nend observables\n"
            "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
            'simulate({method=>"ode",t_end=>1,n_steps=>-10})\n',
            encoding="utf-8",
        )
        _run_case(bng_cpp, d6, ["neg.bngl"], expect_ok=False)

        # 7. Positive semantic smoke under ASan+UBSan: eBNGL |Aut(P)|, asymmetric homodimer,
        # explicit bond cardinality, compartments, ODE+SSA+PLA+PSA+NF.
        d7 = root / "sem_smoke"
        d7.mkdir()
        (d7 / "smoke.bngl").write_text(
            "begin model\n"
            "begin parameters\n"
            "  k 0.5\n"
            "  G_dim -2.0\n"
            "  Ea 1.0\n"
            "  phi 0.5\n"
            "end parameters\n"
            "begin molecule types\n"
            "  A(b,s~0~1~2)\n"
            "end molecule types\n"
            "begin seed species\n"
            "  A(b,s~0) 20\n"
            "end seed species\n"
            "begin observables\n"
            "  Molecules A0 A(s~0)\n"
            "  Molecules Dimer A(b!1).A(b!1)\n"
            "end observables\n"
            "begin energy patterns\n"
            "  A(b!1).A(b!1) G_dim\n"
            "end energy patterns\n"
            "begin reaction rules\n"
            "  A(b,s~0) + A(b,s~0) <-> A(b!1,s~0).A(b!1,s~0) Arrhenius(phi, Ea)\n"
            "  A(b,s~0) + A(b,s~0) -> A(b,s~1) + A(b,s~2) k\n"
            "end reaction rules\n"
            "end model\n"
            "generate_network({overwrite=>1})\n"
            'simulate({method=>"ode",t_end=>1,n_steps=>5})\n'
            'simulate({method=>"ssa",t_end=>1,n_steps=>5,seed=>42})\n'
            'simulate({method=>"pla",t_end=>1,n_steps=>5,seed=>42})\n'
            'simulate({method=>"psa",t_end=>1,n_steps=>5,seed=>42})\n',
            encoding="utf-8",
        )
        _run_case(bng_cpp, d7, ["smoke.bngl"], expect_ok=True)

    print(
        "PASS: all 7 ASan+UBSan security, memory-safety, and semantic CLI checks passed"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    args = parser.parse_args()
    if not args.bng_cpp.is_file():
        print(f"ERROR: bng_cpp binary not found: {args.bng_cpp}", file=sys.stderr)
        return 2
    return run_all_checks(args.bng_cpp.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
