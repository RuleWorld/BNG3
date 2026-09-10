# NFcore2 future-red specification tests

The live NFcore2/NFsim status is in
[`../../../docs/CURRENT_PROGRESS.md`](../../../docs/CURRENT_PROGRESS.md).
Some bounded contracts from this historical future-red inventory have since
been implemented and promoted; the convergence checklist records what remains.

These files encode the test-first contracts for architecture described in the NFcore2 rewrite plan but not yet implemented. They are intentionally excluded from the default standalone build. Each suite is guarded by a feature macro and should be enabled *before* implementing its subsystem, producing red tests first.

Covered future surfaces: snapshots/copy-on-write/fork, batch trajectories, expression/rate dependency DAG and continuous hazards, generic graph fallback and automorphisms, scaffold compiler/lowering and genome scaling, hybrid populations, memory-mapped compiled model images, reference-vs-optimized differential execution including Rasi/uORF gates, SIMD/JIT specialization, and optional GPU homogeneous kernels.
