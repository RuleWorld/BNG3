# PyBioNetGen 28bf351 API/CLI compatibility matrix (BNG3)

Pinned reference: `RuleWorld/PyBioNetGen` commit `28bf351a9bbfc197e19487c26dedda683716bb64` (`/tmp/pybionetgen-ref` source inspected for behavior contracts). In-process runtime differential comparison is limited by pinned-ref dependencies/Perl/BNG environment; use installed BNG3 workflows and independent analytic expectations where needed.

This is a **working behavior-level matrix** for #171/#172 on PR #695 (branch `codex/python-api-compat`). It is **not complete** and does not close #171/#172.

## Verified behavior-level evidence

- **Heads**: matrix/tests updated on working head; key installed evidence below collected on exact head `3bdc3db2613054b588d498d3d0fa1b2e1676c0b7` (PR #695). Latest pushed commits include `5071fb7` (SBML sniffing/CodeQL fix), `8f85e53` (BNGResult `.gdat/.cdat/.scan` convenience), and this matrix/test update.
- **Installed sdist core workflows** (`/tmp/bng3-sdisttest2`, `bionetgen.__file__=/tmp/bng3-sdisttest2/lib/python3.14/site-packages/bionetgen/__init__.py`, `/tmp/bng3-sdist-head-3bdc3db-install.log` RC=0), `/tmp/check_python_workflows.py` RC=0: `load_edit_save`, `generate_network`, `ode_simulation`, `ssa_simulation`, `continuation`, `parameter_scan`, `sensitivity_analysis`, `observable_access`, `cli_run_modern`, `cli_run_legacy_input`, `export_xml`, `export_bngl` all `true`.
- **Installed sdist minimal env** (`/tmp/bng3-minimal-test`, no `xmltodict`/`cement`/`pyparsing`, `bionetgen.__file__=/tmp/bng3-minimal-test/lib/python3.14/site-packages/bionetgen/__init__.py`, `/tmp/bng3-minimal-head-3bdc3db-install.log` RC=0): `bionetgen.bngmodel(...)` load/edit/save succeeded (`modelapi_load_edit_save True`, `has_parameters_block True`).
- **Installed runner/result spot check** (`/tmp/bng3-sdisttest2`): `bionetgen.modelapi.runner.run` on action-workflow BNGL returned `bionetgen.core.tools.result.BNGResult` with populated `gdats`; analytic ODE trajectory matched (`time=[0,0.5,1,1.5,2]`, `A_tot=10*exp(-0.5*t)`).
- **Added regression (analytic, PyBioNetGen-style contract):** `tests/python/test_pybionetgen_runner_result_compat.py::test_modelapi_runner_run_returns_bngresult_with_gdat_access` (passes in source env with built extension).
- **Modern/compat dispatch spot check** (`/tmp/bng3-sdisttest2`): `bionetgen.run(path, 'ode', 2.0, 4)` returned `SimResult` with observables; `bionetgen.modelapi.runner.run(path)` returned `BNGResult`.

## Behavior-level status by family

| Family | PyBioNetGen 28bf351 contract (source/expected) | BNG3 status | Evidence | Gaps / next |
| --- | --- | --- | --- | --- |
| Top-level `bionetgen.run` | `run` exposed as `modelapi.runner.run` (file-runner, BNGResult-oriented) | **partial** | `bionetgen.modelapi.runner.run` file-runner behavior verified (BNGResult+gdat/analytic). Top-level `bionetgen.run` supports modern + legacy/compat forms per existing BNG3 compat tests. | Reconcile PyBioNetGen-default top-level semantics without breaking BNG3 decisions/contracts; differential tests for all arg forms/options/errors/results. |
| `bionetgen.bngmodel` / `modelapi.model` | Legacy model API load/edit/save/actions/simulator/export surface | **partial** | Minimal installed env load/edit/save/write/reload works without `xmltodict`/`cement`/`pyparsing` (stdlib BNG-XML fallback, lazy action parser, lazy defaults/logger). | Action parsing with `pyparsing`, XML inputs, generate_network/simulate/setup_simulator/export_sympy_odes, block/method parity, diagnostics/defaults parity. |
| `bionetgen.core.tools.result.BNGResult` | Folder/file result loading, `gdats/cdats/scans`, dat/scan access, ext/folder_path handling | **partial** | Runner-produced BNGResult with `gdats` and `.gdat` convenience verified on analytic workflow. | `file_extension`/direct-file semantics, `.cdat/.scan/.net` parity, multi-file behavior, full API parity and negative cases. |
| `modelapi.runner.run` signature/options | `(inp,out,suppress,timeout,simulator,format,method,t_span,n_points)` with PyBioNetGen routing/output semantics | **partial** | Signature/validation subset covered by prior tests; action-workflow analytic run verified. | timeout/bngsim/direct-format routing, output layout, method/time-grid interactions, error parity, differential vs pinned ref. |
| Model load/edit/save/generate network/ODE/SSA/continuation/scan/sensitivity/observable/result/CLI/exports (installed workflows) | End-to-end PyBioNetGen workflows | **partial** | Installed sdist core workflow script all-true for listed families; CLI modern+legacy input checks passed in script. | Behavior-level parity vs pinned PyBioNetGen (not just script pass), exact-head wheel, optional extras independent, result/output contracts. |
| `bionetgen.network` | `.net` parse/model APIs | **present/importable, behavior pending** | Module import verified in installed env. | Differential parse/edit/write/net-workflow tests. |
| `bionetgen.simulator` / csimulator / libRR | Simulator APIs and wrappers | **present, behavior pending** | Symbols/modules present; csimulator decoupled from eager cement config. | Runtime/compilation/result/optional-dep parity and explicit diagnostics. |
| bngsim bridge/backend helper/parameter scan | PyBioNetGen bngsim integration APIs | **present/API partial** | Modules/symbols/route helpers present; SBML sniffing tightened; lazy availability exports. | Routing, availability/version behavior, scan/bifurcate/backend-helper parity, negative tests. |
| CLI (`run/plot/info/notebook/visualize/graphdiff/atomize`) & options | Cement CLI command/option behavior | **partial** | Click CLI expanded for legacy names/options; core script shows modern/legacy run entrypoints work. | Full option/output/exit-code parity, tool-specific behavior, optional deps, installed differential tests. |
| Optional extras (pandas/matplotlib/sympy/libsbml/roadrunner/notebook deps, etc.) | Optional-feature parity | **partial** | Prior wheel-env pandas `to_dataframe` evidence (earlier artifact); script-level scan/sensitivity ran. | Exact-head per-extra installed verification and missing-dep diagnostics parity. |

## Static/name-level gaps still relevant (not exhaustive)

- `bionetgen/__init__`: PyBioNetGen exports `defaults`, `BNGSIM_AVAILABLE`, `BNGSIM_VERSION` directly (BNG3 provides lazy access; `__all__`/behavior parity pending).
- `bionetgen.main`: `get_conf`, `get_default_app`, `get_default_bng_path` parity pending.
- `modelapi`: `ProtocolBlock`/`add_protocol_block`, `ParameterBlock.add_item`, `RuleMod.add_modifier`, `XMLObj.resolve_ratelaw`, `Operation` methods, and broader method/behavior parity pending.
- `network`: `NetworkParameterBlock.add_item`, `NetworkSpeciesBlock` item access parity pending.
- `simulator/csimulator`: `__repr__/__str__` and runtime parity pending.
- `core.utils.utils.ActionList.validate_action` parity pending.
- Full `py.*` inventory from #171 remains to be mapped with behavior-level pass/fail/unsupported evidence.

## CI / hosted evidence

- PR #695: latest pushed head `8f85e53`. Observed snapshots showed passes on some jobs (anti-gaming, Lint & Format, Analyze python, Lean/NFnext on earlier snapshots) and pending/running jobs (Analyze cpp/python, formatting patch, common evidence/selection contracts, Lint & Format, Issue 157/160/161/472, official SBML subset, parity/source-lock as shown; curated/SSTS skipped). Must monitor to completion and fix any failures.
- Exact-head wheel workflow and hosted cross-platform installed evidence: **incomplete**.

## Required next work for #171/#172

1. Expand this matrix to behavior-level coverage for every required PyBioNetGen public API/CLI family and key `py.*` surfaces with evidence.
2. Run differential tests vs pinned PyBioNetGen `28bf351` where feasible, else independent analytic expectations, plus negative regressions.
3. Fix uncovered/incorrect behavior in production code while preserving existing BNG3 compatibility contracts and explicit unsupported diagnostics.
4. Verify exact-head installed wheel/sdist workflows and optional extras independently with fresh extension provenance; complete hosted cross-platform CI.
5. Unify duplicate Python semantic paths only after equivalent installed-package behavior is demonstrated, preserving public entry points and explicit diagnostics.
