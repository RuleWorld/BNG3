#!/usr/bin/env python3
"""Diff two identity_check.py output trees and report per-model agreement.

usage: compare_identity.py <base_dir> <changed_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    base, changed = Path(sys.argv[1]), Path(sys.argv[2])
    names = sorted(p.name for p in base.iterdir() if p.is_dir())
    rows = []
    for n in names:
        b = (base / n / "SHA256SUMS")
        c = (changed / n / "SHA256SUMS")
        if not c.exists():
            rows.append((n, "MISSING", ""))
            continue
        bt = b.read_text() if b.exists() else ""
        ct = c.read_text()
        nb = len([x for x in bt.splitlines() if x])
        nc = len([x for x in ct.splitlines() if x])
        if not nb or not nc:
            rows.append((n, "INCONCLUSIVE", f"artifacts base={nb} changed={nc}"))
        elif bt == ct:
            rows.append((n, "IDENTICAL", f"{nb} artifacts"))
        else:
            bd = {l.split()[1]: l.split()[0] for l in bt.splitlines() if l}
            cd = {l.split()[1]: l.split()[0] for l in ct.splitlines() if l}
            diff = sorted(set(bd) ^ set(cd)) + \
                sorted(k for k in set(bd) & set(cd) if bd[k] != cd[k])
            rows.append((n, "DIFFERS", ", ".join(diff)))

    w = max(len(r[0]) for r in rows)
    ident = 0
    for n, verdict, detail in rows:
        print(f"{n:<{w}}  {verdict:<13} {detail}")
        if verdict == "IDENTICAL":
            ident += 1
    print(f"\n{ident}/{len(rows)} models byte-identical "
          f"(.gdat/.cdat/.net SHA-256) between the two binaries")
    return 0 if ident == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
