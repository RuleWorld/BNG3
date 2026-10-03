#!/bin/bash
# Interleaved A/B runner for the CPU batch-SSA pool.
#
# Usage: run_ab.sh <binA> <binB> <reps> <config...>
# where <config...> are the remaining bench_batch_ssa arguments.
#
# Interleaves A and B in one session, reversing the first arm every round, so
# host drift (other operators share this machine) cannot masquerade as an
# effect. Prints the execution order, both streams, and a min/spread summary.

set -euo pipefail

if (( $# < 4 )); then
  echo "usage: run_ab.sh <binA> <binB> <reps> <config...>" >&2
  exit 2
fi

BIN_A="$1"; BIN_B="$2"; REPS="$3"; shift 3
if ! [[ "$REPS" =~ ^[1-9][0-9]*$ ]]; then
  echo "reps must be a positive integer" >&2
  exit 2
fi

OUT_A=$(mktemp); OUT_B=$(mktemp)
OUT_ORDER=$(mktemp)
OUT_A_TIME=$(mktemp); OUT_B_TIME=$(mktemp)
cleanup() { rm -f "$OUT_A" "$OUT_B" "$OUT_ORDER" "$OUT_A_TIME" "$OUT_B_TIME"; }
trap cleanup EXIT

run_arm() {
  local arm="$1"; shift
  if [[ "$arm" == A ]]; then
    if [[ "$(uname -s)" == Darwin ]]; then
      /usr/bin/time -l "$BIN_A" "$@" >> "$OUT_A" 2>> "$OUT_A_TIME"
    else
      "$BIN_A" "$@" >> "$OUT_A"
    fi
  else
    if [[ "$(uname -s)" == Darwin ]]; then
      /usr/bin/time -l "$BIN_B" "$@" >> "$OUT_B" 2>> "$OUT_B_TIME"
    else
      "$BIN_B" "$@" >> "$OUT_B"
    fi
  fi
}

for round in $(seq 1 "$REPS"); do
  if (( round % 2 == 1 )); then
    printf 'round %s: A then B\n' "$round" >> "$OUT_ORDER"
    run_arm A "$@"
    run_arm B "$@"
  else
    printf 'round %s: B then A\n' "$round" >> "$OUT_ORDER"
    run_arm B "$@"
    run_arm A "$@"
  fi
done

EVENTS_A=$(awk -F, '/^[0-9]+,/ {print $5}' "$OUT_A")
EVENTS_B=$(awk -F, '/^[0-9]+,/ {print $5}' "$OUT_B")
if [[ -z "$EVENTS_A" || -z "$EVENTS_B" ]]; then
  echo "ERROR: baseline and candidate must both produce measurement rows" >&2
  exit 1
fi
if [[ "$EVENTS_A" != "$EVENTS_B" ]]; then
  echo "ERROR: baseline and candidate total-event samples differ" >&2
  printf 'A events:\n%s\nB events:\n%s\n' "$EVENTS_A" "$EVENTS_B" >&2
  exit 1
fi

echo "=== execution order ==="; cat "$OUT_ORDER"
echo "=== A ($BIN_A) ==="; cat "$OUT_A"
echo "=== B ($BIN_B) ==="; cat "$OUT_B"
if [[ "$(uname -s)" == Darwin ]]; then
  echo "=== A process time samples (real/user/sys) ==="
  awk '/real/ && /user/ && /sys/ {print}' "$OUT_A_TIME"
  echo "=== B process time samples (real/user/sys) ==="
  awk '/real/ && /user/ && /sys/ {print}' "$OUT_B_TIME"
  echo "=== A peak RSS samples (bytes, /usr/bin/time -l) ==="
  awk '/maximum resident set size/ {print $1}' "$OUT_A_TIME"
  echo "=== B peak RSS samples (bytes, /usr/bin/time -l) ==="
  awk '/maximum resident set size/ {print $1}' "$OUT_B_TIME"
fi

summarize() {
  awk -F, '/^[0-9]+,/ {
      n++; t=$6; e=$7; tt=$8; et=$9;
      if (n==1 || t<minT) minT=t; if (t>maxT) maxT=t;
      if (n==1 || tt<minTT) minTT=tt; if (tt>maxTT) maxTT=tt;
      if (n==1 || e<minE) minE=e; if (e>maxE) maxE=e;
      if (n==1 || et<minET) minET=et; if (et>maxET) maxET=et;
    }
    END {
      printf "  traj/s sim   min=%.1f  max=%.1f  spread=%.2f%%\n", minT, maxT, 100*(maxT-minT)/minT;
      printf "  events/s sim min=%.1f  max=%.1f  spread=%.2f%%\n", minE, maxE, 100*(maxE-minE)/minE;
      printf "  traj/s total min=%.1f  max=%.1f  spread=%.2f%%\n", minTT, maxTT, 100*(maxTT-minTT)/minTT;
      printf "  ev/s   total min=%.1f  max=%.1f  spread=%.2f%%\n", minET, maxET, 100*(maxET-minET)/minET;
    }' "$1"
}

echo "--- summary A ---"; summarize "$OUT_A"
echo "--- summary B ---"; summarize "$OUT_B"
