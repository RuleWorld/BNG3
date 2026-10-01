#!/bin/bash
# Seeded SSA trajectory identity check for the C++ simulation lane.
#
# usage: benchmarks/check_engine_ssa_identity.sh <bng_cpp> <outdir>
#
# Runs fixed-seed SSA trajectories (a 4M-event synthetic ring network plus
# four repository models covering plain, function-driven, and continued
# rates) and writes SHA-256 hashes of every .gdat/.cdat/.net artifact to
# <outdir>/SHA256SUMS. Run it once with a pre-change binary and once with a
# post-change binary and diff the two SHA256SUMS files: engine performance
# changes are a win only when both diffs are empty, because the seeded
# trajectory is a behavior contract.
set -euo pipefail
BIN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$2"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

# 4M-event synthetic ring network from the benchmark generator
python3 - "$OUT" "$REPO" <<'PY'
import sys
from pathlib import Path
repo = Path(sys.argv[2])
sys.path.insert(0, str(repo / "benchmarks"))
from bench_engine_ssa import model_text
out = Path(sys.argv[1]) / "synth"
out.mkdir(parents=True, exist_ok=True)
(out / "model.bngl").write_text(model_text(150, 4_000_000, 12345))
PY
( cd "$OUT/synth" && "$BIN" model.bngl >/dev/null 2>stderr.txt )

mk_actions() { # file, actions...
  local f="$1"; shift
  python3 - "$f" "$@" <<'PY'
import re, sys
from pathlib import Path
f = Path(sys.argv[1]); actions = sys.argv[2:]
text = f.read_text()
text = re.sub(r"\n## actions ##\n.*$", "", text, flags=re.S)
text = re.sub(r"\nbegin actions\n.*?\nend actions\n", "\n", text, flags=re.S)
f.write_text(text + "\n## actions ##\n" + "\n".join(actions) + "\n")
PY
}

for name in isomerization gene_expr_simple gene_expr_func michment; do
  mkdir -p "$OUT/$name"
  cp "$REPO/models/$name.bngl" "$OUT/$name/model.bngl"
done
mk_actions "$OUT/isomerization/model.bngl" \
  'generate_network({overwrite=>1})' \
  'simulate_ssa({suffix=>"s",t_start=>0,t_end=>20000,n_steps=>400,seed=>7})'
mk_actions "$OUT/gene_expr_simple/model.bngl" \
  'generate_network({overwrite=>1})' \
  'simulate_ssa({suffix=>"s",t_start=>0,t_end=>100000,n_steps=>400,seed=>7})'
mk_actions "$OUT/gene_expr_func/model.bngl" \
  'generate_network({overwrite=>1})' \
  'simulate_ssa({suffix=>"s",t_start=>0,t_end=>100000,n_steps=>400,seed=>7})'
mk_actions "$OUT/michment/model.bngl" \
  'generate_network({overwrite=>1})' \
  'simulate_ssa({suffix=>"s",t_start=>0,t_end=>10000,n_steps=>400,seed=>7})'
for name in isomerization gene_expr_simple gene_expr_func michment; do
  ( cd "$OUT/$name" && "$BIN" model.bngl >/dev/null 2>stderr.txt )
done

( cd "$OUT" && find . \( -name '*.gdat' -o -name '*.cdat' -o -name '*.net' \) \
    | sort | xargs shasum -a 256 > SHA256SUMS )
cat "$OUT/SHA256SUMS"
