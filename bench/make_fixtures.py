#!/usr/bin/env python3
"""Regenerate bench/models/*_gen.bngl fixtures from models/ deterministically.

Each fixture is the source model truncated right after its LAST section-terminator
line (``end model`` / ``end observables`` / ...), with the protocol replaced by a
single ``generate_network`` action that reuses the model's own generate_network
arguments when the source declares them (falling back to ``{overwrite=>1}``).
This strips simulation / write* actions so the benchmark measures network
generation only.

Run from the repository root:
    python bench/make_fixtures.py
Then verify no drift:
    git diff --stat bench/models/
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "bench" / "models"

# fixture name -> source model path (relative to repo root)
SOURCES = {
    "PushPull": "models/simple_PushPull/PushPull.bngl",
    "Repressilator": "models/Repressilator.bngl",
    "blbr": "models/blbr.bngl",
    "e4": "models/multisite_phos/e4.bngl",
    "e5": "models/multisite_phos/e5.bngl",
    "e6": "models/multisite_phos/e6.bngl",
    "e7": "models/multisite_phos/e7.bngl",
    "egfr_net": "models/egfr_net.bngl",
    "fceri_ji": "models/fceRI_compendium/fceri_ji.bngl",
    "heise": "models/heise.bngl",
    "tlbr": "models/tlbr.bngl",
}

SECTION_END = re.compile(r"^end [A-Za-z_]+[^\n]*$", re.M)
GEN_NETWORK = re.compile(r"^#?generate_network\((.*)\)\s*;?\s*$", re.M)


def build(name: str, src: Path) -> str:
    text = src.read_text()
    ends = list(SECTION_END.finditer(text))
    if not ends:
        raise SystemExit(f"{src}: no section terminator found")
    head = text[: ends[-1].end()] + "\n"
    gens = GEN_NETWORK.findall(text)
    args = gens[0].strip() if gens else "{overwrite=>1}"
    if not args.startswith("{"):
        args = "{" + args + "}"
    return head + f"\n## actions ##\ngenerate_network({args})\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rel in sorted(SOURCES.items()):
        out = OUT_DIR / f"{name}_gen.bngl"
        out.write_text(build(name, ROOT / rel))
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
