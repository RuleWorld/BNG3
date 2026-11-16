# Python API/CLI compatibility matrix (pinned PyBioNetGen 28bf351 vs BNG3)

- PyBioNetGen: `RuleWorld/PyBioNetGen@28bf351a9bbfc197e19487c26dedda683716bb64` (`/tmp/pybionetgen-ref`)
- BNG3: `/tmp/bng3-python-api-compat` branch `codex/python-api-compat` (static source comparison; generated during active work)
- Status legend: `present` = corresponding module/symbol names exist in BNG3 source (static); `missing` = not found by static scan; `behavior parity` = requires differential/installed-workflow tests (not fully completed).

## CLI commands (static)
- PyBioNetGen (Cement, `bionetgen.main`): `atomize`, `graphdiff`, `info`, `notebook`, `plot`, `run`, `visualize`
- BNG3 (Click, `bionetgen.cli`): `atomize`, `check`, `execute`, `export`, `graphdiff`, `info`, `notebook`, `plot`, `run`, `scan`, `sensitivity`, `visualize`

### BNG3 command option/argument counts (static parse)
- `atomize`: 5 declared click options/args
- `check`: 1 declared click options/args
- `execute`: 2 declared click options/args
- `export`: 3 declared click options/args
- `graphdiff`: 6 declared click options/args
- `info`: 1 declared click options/args
- `notebook`: 3 declared click options/args
- `plot`: 10 declared click options/args
- `run`: 18 declared click options/args
- `scan`: 18 declared click options/args
- `sensitivity`: 16 declared click options/args
- `visualize`: 4 declared click options/args

## Module/API surface comparison (static, name-level)
### `bionetgen/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Missing from `__all__` (name-level): `defaults`, `BNGSIM_AVAILABLE`, `BNGSIM_VERSION`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/main.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Missing top-level function names: `get_conf`, `get_default_app`, `get_default_bng_path`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/defaults.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/exc.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/main.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/notebook.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/version.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/bngsim_backend_helper.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/bngsim_bridge.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/bngsim_parameter_scan.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/cli.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/gdiff.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/info.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/plot.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/result.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/tools/visualize.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/utils/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/utils/logging.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/core/utils/utils.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `ActionList` missing method names (static): `validate_action`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/blocks.py` — BNG3 module present
- Missing top-level class names: `ProtocolBlock`
- Top-level function names: no PyBioNetGen names missing (static)
- `ParameterBlock` missing method names (static): `add_item`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/bngfile.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/bngparser.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/model.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `bngmodel` missing method names (static): `add_protocol_block`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/pattern.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/pattern_reader.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/rulemod.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `RuleMod` missing method names (static): `add_modifier`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/runner.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/structs.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/sympy_odes.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/modelapi/xmlparsers.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `Operation` missing method names (static): `__init__`, `__repr__`, `__str__`
- `XMLObj` missing method names (static): `resolve_ratelaw`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/network/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/network/blocks.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `NetworkParameterBlock` missing method names (static): `add_item`
- `NetworkSpeciesBlock` missing method names (static): `__getitem__`, `__setitem__`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/network/network.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/network/networkparser.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/network/structs.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/simulator/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/simulator/bngsimulator.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/simulator/csimulator.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- `CSimulator` missing method names (static): `__repr__`, `__str__`
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/simulator/librrsimulator.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/simulator/simulators.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/atomizer/__init__.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)

### `bionetgen/atomizer/atomizeTool.py` — BNG3 module present
- Top-level class names: no PyBioNetGen names missing (static)
- Top-level function names: no PyBioNetGen names missing (static)
- Behavior parity: **not fully verified** (differential + installed wheel/sdist workflow tests still required)
