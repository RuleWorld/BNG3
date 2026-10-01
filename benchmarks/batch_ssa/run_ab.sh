#!/bin/bash
# Interleaved A/B runner for the CPU batch-SSA pool.
#
# Usage: run_ab.sh <binA> <binB> <reps> <config...>
# where <config...> are the remaining bench_batch_ssa arguments.
#
# Runs A B A B ... in one session so that host drift (other operators share
# this machine) cannot masquerade as an effect. Prints both streams plus a
# min/spread summary computed over the pooled A and B samples.

set -euo pipefail

BIN_A="$1"; BIN_B="$2"; REPS="$3"; shift 3

OUT_A=$(mktemp); OUT_B=$(mktemp)

for _ in $(seq 1 "$REPS"); do
  "$BIN_A" "$@" >> "$OUT_A"
  "$BIN_B" "$@" >> "$OUT_B"
done

echo "=== A ($BIN_A) ==="; cat "$OUT_A"
echo "=== B ($BIN_B) ==="; cat "$OUT_B"

summarize() {
  awk -F, '/^[0-9]+,/ {
      n++; t=$6; e=$7; tt=$8; et=$9;
      if (n==1 || t<minT) minT=t; if (t>maxT) maxT=t;
      if (n==1 || tt<minTT) minTT=tt; if (tt>maxTT) maxTT=tt;
      if (n==1 || e<minE) minE=e; if (e>maxE) maxE=e;
      if (n==1 || et<minET) minET=et; if (et>maxET) maxET=et;
    }
    END {
      if (n == 0) {
        print "  NO DATA ROWS MATCHED /^[0-9]+,/ — the benchmark produced no CSV output." > "/dev/stderr";
        print "  Refusing to report min/spread over an empty set." > "/dev/stderr";
        exit 3;
      }
      if (minT == 0) {
        print "  traj/s sim minimum is 0 — divide-by-zero spread is undefined; check for a failed rep." > "/dev/stderr";
        exit 3;
      }
      printf "  traj/s sim   min=%.1f  max=%.1f  spread=%.2f%%\n", minT, maxT, 100*(maxT-minT)/minT;
      printf "  events/s sim min=%.1f  max=%.1f  spread=%.2f%%\n", minE, maxE, 100*(maxE-minE)/minE;
      printf "  traj/s total min=%.1f  max=%.1f  spread=%.2f%%\n", minTT, maxTT, 100*(maxTT-minTT)/minTT;
      printf "  ev/s   total min=%.1f  max=%.1f  spread=%.2f%%\n", minET, maxET, 100*(maxET-minET)/minET;
    }' "$1"
}

echo "--- summary A ---"; summarize "$OUT_A"
echo "--- summary B ---"; summarize "$OUT_B"
rm -f "$OUT_A" "$OUT_B"