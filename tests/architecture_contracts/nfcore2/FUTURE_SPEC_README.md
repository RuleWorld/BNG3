# NFcore2 future-red specification tests

These files encode the test-first contracts for architecture described in the NFcore2 rewrite plan but not yet implemented. They are intentionally excluded from the default standalone build. Each suite is guarded by a feature macro and should be enabled *before* implementing its subsystem, producing red tests first.

Covered future surfaces: snapshots/copy-on-write/fork, batch trajectories, expression/rate dependency DAG and continuous hazards, generic graph fallback and automorphisms, scaffold compiler/lowering and genome scaling, hybrid populations, memory-mapped compiled model images, reference-vs-optimized differential execution including Rasi/uORF gates, SIMD/JIT specialization, and optional GPU homogeneous kernels.
