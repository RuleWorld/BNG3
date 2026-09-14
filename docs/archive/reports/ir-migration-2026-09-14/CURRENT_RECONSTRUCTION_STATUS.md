# Current reconstruction status

This source tree is the latest persisted cumulative BNG3 IR-migration state available in this execution environment.

It starts from the last persisted migration archive and reconstructs the later post-archive changes that were still recoverable from the implementation checkpoints, including:

- backend-neutral BioNetGen pattern matching in `cpp/core/PatternMatching.*`;
- isolation of the mature AST-backed network expansion path behind `LegacyNetworkRuleKernel`;
- exact molecule occurrence tracking for local-function scopes;
- stronger structural BNGIR v0.2 validation and local-scope serialization;
- population-map population-type/rate semantics in the AST, compile layer, BNGIR, and hybrid generation path;
- shared compiled `ObservableProjection`;
- compiled-model `RegulatoryGraphWriter` and structural `ContactMapWriter`;
- removal of unused AST-model dependencies from the process, reaction-network, and rule-influence graph writers;
- the architecture dependency ratchet updates corresponding to those migrations.

Validation available in the dependency-constrained environment at packaging time:

- direct C++17 syntax compilation of the reconstructed core/compile/network/observable/writer units;
- Python byte-code compilation for `python/bionetgen/bngir.py` and the architecture checker;
- architecture dependency checker passes;
- pure structural BNGIR v0.2 smoke test passes.

## Important persistence caveat

Some additional migrations had been implemented in an earlier ephemeral runtime after the last persisted ZIP (notably later Ruleviz/exporter/SBML/Bngsim cleanup), but that un-packaged working directory was lost when the runtime reset. Those source patches could not be recovered byte-for-byte from disk and are therefore **not falsely represented as present in this archive**. The repository here contains the changes actually reconstructed and validated in the current source tree.

Full upstream CMake/parity validation is still constrained by unavailable fetched dependencies such as the ANTLR/Catch2/ExprTk/pybind toolchain pieces. Existing compatibility/oracle paths are intentionally retained where independent parity has not been established.
