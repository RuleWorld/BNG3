#!/usr/bin/env python3
"""Meta-test: future contracts may be opt-in, but individual cases cannot silently skip."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / "future_contract"
FORBIDDEN = [
    r"\bGTEST_SKIP\b",
    r"\bSKIP_TEST\b",
    r"\breturn\s*;\s*//\s*skip",
    r"\bTODO_SKIP\b",
    r"\bXFAIL\b",
]

bad = []
for p in ROOT.glob("*.cpp"):
    text = p.read_text(errors="replace")
    for pat in FORBIDDEN:
        if re.search(pat, text, re.I):
            bad.append(f"{p.name}: forbidden silent-skip marker {pat}")
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
print("future contracts contain no silent skip markers")
