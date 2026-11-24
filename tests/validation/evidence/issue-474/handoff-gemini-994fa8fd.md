# #474 GPU workstream handoff (source revision `994fa8fdaee1348a32bb2a1877f6235534af5134`)

## Branch and merge state

- Isolated branch: `codex/issue474-gpu-qualification` in `/private/tmp/bng3-474`.
- Source candidate: `994fa8fd` = `60b9e2b9` (full-grid device fix and bounded NF workload coverage)
  merged with current `origin/main` through `a8983f6e` (merge commit `994fa8fd`).
- The original checkout `/Users/akutuva/Documents/BioNetGen/BNG3` was not modified.
- Evidence follow-up commit (`7d0c3559` and later) adds receipts only, no product changes.
- Do not close #474 or merge into main until Gemini has coordinated the branch merge; the
  CLOSED gate below is a dry run and no GitHub state was mutated.

## Product fix and scope

`simulate_ssa(batch_size>1, n_steps>0, batch_gpu_backend=<device>)` previously rejected the
device result because both GPU kernels recorded only final species while `OdeResult` consumes
a `[time][species]` grid; it silently fell back to the CPU pool. Both Metal and CUDA kernels
now record species at every output time, the shared converter preserves a full grid, and a
device result reports `backend="metal"`/`backend="cuda"`. Fail-closed rejection of unsupported
rate laws and unavailable devices is unchanged. CUDA source was updated symmetrically but
remains compile-unverified on this host (no nvcc).

`simulate_nfnext_gpu` now also reports cold `setup_time_ms` and `device_memory_bytes`.

## Verified Metal artifacts (exact source revision)

- Actual device: Apple M5 Pro, 16-core GPU, Metal 4, macOS 27.0.1 (26A434), Apple clang
  21.0.0, SDK 27.0, CMake 4.4.3, Ninja 1.13.2, Python 3.14.6. Clean Release build with
  `-DBNG3_ENABLE_METAL=ON -DBNG3_ENABLE_CUDA=OFF`.
- Native binary SHA-256: `1fd04b8ce3fcbed6c35a87cb46bf02a45ebfd1978d0edc56c327625944de190a`.
  MSL object digests and build options: `build-identity-metal.json`.
- Finite SSA: `metal-device-994fa8fd....json` — five prior models plus the new
  `toy-jim-public-route` row (backend attribution, 11x25 full grid, conservation, seed replay,
  prespecified Bonferroni distributional comparison; no pathwise CPU/GPU claim).
- Performance: `metal-performance-egfr-994fa8fd....json` (A/A null, 143/143 equivalence cells
  at alpha=0.001, self_cpu effect 0.0498x, wall 0.2622x, transfer/memory/startup) and six
  `metal-crossover-b*-994fa8fd....json` receipts (batches 1..1000, clock divergence and host
  contention caveats retained).
- Network-free: `nfnext-metal-994fa8fd....json` (two-state CTMC, 2048 trajectories, seed
  474141, 416398 events) plus `pinned-nfsim-994fa8fd....json` (NFsim `8c449bbc...`, artifact
  `caf0ad15...`, 256 runs, Bonferroni alpha 0.001). `nfnext-workloads-994fa8fd....json`
  adds three-state chain and particle-heavy classes (1,042,480 events total) with analytic
  laws, conservation, fixed seeds, setup/dispatch time, device memory and throughput. Binding,
  bound-rule, compartment, delayed-rule and CUDA classes are explicit refusals.
- Consuming selectors: `tests/validation/release/cases/issue-474/` — 18 passed with the exact
  report/workload receipts (no device needed for the receipt-consuming checks).

Claims remain bounded: this is the unary single-site state-change Metal route, not the full
network-free GPU corpus; no equal-seed pathwise CPU/GPU or native/GPU claim is made.

## CUDA status

- `nvidia-smi` and `nvcc` absent; `gh api repos/RuleWorld/BNG3/actions/runners` returns HTTP
  403; `gpu-device-qualification.yml` has 0 runs. `cuda-probe-994fa8fd....json`.
- Independently verified compile blocker: `cmake ... -DBNG3_ENABLE_CUDA=ON` exits 1 with
  "no CUDA compiler was found"; `cuda-build-probe-994fa8fd....json`. Compile-only evidence
  never counts as device execution.
- CUDA kernel sources were updated for the full species grid but cannot be compiled or run
  here. Metal evidence is not used to qualify CUDA.

## Gate and remaining check IDs

Single-issue CLOSED dry run at `994fa8fd` with the actual reports: exit 1 —
`release-metal-device` and `release-metal-performance` DEMONSTRATED; four checks remain
NOT_TESTED: `release-cuda-device`, `release-cuda-performance`, `release-nf-gpu`,
`release-capability-coverage-474`. See `gate-issue-474-994fa8fd.md` and updated
`gate-summary.json`. #474 must remain OPEN until those checks pass on main with exact-revision
CUDA device/performance receipts and full network-free corpus coverage (Metal plus CUDA).
