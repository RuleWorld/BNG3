# PyBioNetGen API audit against pinned PyBioNetGen 28bf351

Static comparison of every public module-level function, class and method in pinned PyBioNetGen (`bionetgen/`, excluding the Atomizer and assets) with the same dotted path in BNG3 `python/bionetgen/`. Of 422 upstream symbols, 287 are present with the same signature, 13 are present with a different signature, 1 is present under another path, and 121 are absent.

These counts were measured before the compatibility change that added `BNGFormatError`, `BNGSimError`, the `run` arguments, the `BNGCLI` BNGsim options and the `BNGResult` `ext` and `folder_path` arguments; docs/migration_guide.md describes the current differences. This checks presence and call signatures only, not behavior. A method listed as absent may be inherited from a base class in BNG3 (for example `ParameterBlock.add_item` from `ModelBlock`); the scan looks at each class body only. The differential tests in #171 still have to check behavior.

## Signature differences

| Symbol | Difference |
|---|---|
| `core.tools.cli.BNGCLI.__init__` | upstream-only [('bngsim_backend', 'False'), ('bngsim_backend_helper', 'None'), ('bngsim_backend_method', 'None')]; bng3-only [] |
| `core.tools.result.BNGResult.__init__` | upstream-only [('ext', 'None')]; bng3-only [] |
| `core.tools.result.BNGResult.find_dat_files` | upstream-only [('folder_path', 'None')]; bng3-only [] |
| `core.tools.result.BNGResult.load_results` | upstream-only [('folder_path', 'None')]; bng3-only [] |
| `modelapi.bngfile.BNGFile.__init__` | upstream-only [('BNGPATH', 'None')]; bng3-only [('BNGPATH', 'def_bng_path')] |
| `modelapi.bngparser.BNGParser.__init__` | upstream-only [('BNGPATH', 'None'), ('verbose', 'False')]; bng3-only [('BNGPATH', 'def_bng_path')] |
| `modelapi.model.bngmodel.__init__` | upstream-only [('BNGPATH', 'None'), ('verbose', 'False')]; bng3-only [('BNGPATH', 'def_bng_path')] |
| `modelapi.pattern.Pattern.__init__` | upstream-only [('molecules', 'None')]; bng3-only [('molecules', '[]')] |
| `modelapi.pattern.Molecule.__init__` | upstream-only [('components', 'None')]; bng3-only [('components', '[]')] |
| `modelapi.pattern.Molecule.add_component` | upstream-only [('states', 'None')]; bng3-only [('states', '[]')] |
| `modelapi.rulemod.RuleMod.__init__` | upstream-only [('modifiers', 'None')]; bng3-only [] |
| `modelapi.runner.run` | upstream-only [('simulator', "'auto'"), ('format', 'None'), ('method', 'None'), ('t_span', 'None'), ('n_points', 'None')]; bng3-only [] |
| `modelapi.structs.Action.__init__` | upstream-only [('action_args', 'None')]; bng3-only [('action_args', '{}')] |

Most of these are BNG3 keeping mutable default arguments (`[]`, `{}`) where PyBioNetGen moved to `None`, and `BNGPATH` defaulting to `def_bng_path` instead of `None`. Three change what callers can pass:

- `modelapi.runner.run` lacks PyBioNetGen's `simulator`, `format`, `method`, `t_span` and `n_points` arguments, so a PyBioNetGen call that passes them raises TypeError.
- `core.tools.cli.BNGCLI.__init__` lacks `bngsim_backend`, `bngsim_backend_helper` and `bngsim_backend_method`.
- `core.tools.result.BNGResult` lacks the `ext` argument, and `find_dat_files` and `load_results` lack `folder_path`.

## Absent symbols

| Group | Symbols | BNG3 route |
|---|---|---|
| `core.exc` | `BNGFormatError`, `BNGFormatError.__init__`, `BNGSimError`, `BNGSimError.__init__` | No equivalent found. Decide whether to add it or document the replacement. |
| `core.tools.bngsim_backend_helper` | `BackendHelperJob`, `load_backend_job`, `direct_job_from_backend_job`, `execute_backend_payload`, `serve` | BNGsim is a native backend in BNG3: `BioNetGenModel.simulate(..., backend="bngsim")`. The PyBioNetGen helper-process protocol has no BNG3 equivalent. |
| `core.tools.bngsim_bridge` | `is_bngsim_available`, `get_bngsim_unavailable_reason`, `BngsimRouteDecision`, `BngsimDirectJob`, `detect_input_format`, `execute_bngsim_direct_job`, `run_nfsim`, `run_with_bngsim`, `classify_bngsim_route`, `run_bngl_with_bngsim_backend_hook`, `run_bngl_with_bngsim` | Use `backend="bngsim"` on `BioNetGenModel.simulate`; an unavailable backend is reported as an error. |
| `core.tools.bngsim_parameter_scan` | `ScanRequest`, `detect_inprocess_scan`, `scan_values`, `run_inprocess_scan`, `run_parameter_scan_with_bngsim`, `run_bifurcate_with_bngsim` | Use `BioNetGenModel.parameter_scan` (or `bionetgen.scan`) with the BNGsim backend. |
| `core.utils` | `utils.ActionList.validate_action` | No equivalent found. Decide whether to add it or document the replacement. |
| `main.get_default_app` | `main.get_default_app` | No equivalent found. Decide whether to add it or document the replacement. |
| `main.get_conf` | `main.get_conf` | No equivalent found. Decide whether to add it or document the replacement. |
| `main.get_default_bng_path` | `main.get_default_bng_path` | No equivalent found. Decide whether to add it or document the replacement. |
| `modelapi.blocks` | `ParameterBlock.add_item`, `ProtocolBlock`, `ProtocolBlock.__init__`, `ProtocolBlock.add_item`, `ProtocolBlock.gen_string` | No equivalent found. Decide whether to add it or document the replacement. |
| `modelapi.model` | `bngmodel.add_protocol_block` | No equivalent found. Decide whether to add it or document the replacement. |
| `modelapi.rulemod` | `RuleMod.add_modifier` | No equivalent found. Decide whether to add it or document the replacement. |
| `modelapi.xmlparsers` | `XMLObj.resolve_ratelaw`, `Operation.__init__` | No equivalent found. Decide whether to add it or document the replacement. |
| `network` | `blocks.NetworkBlock`, `blocks.NetworkBlock.__init__`, `blocks.NetworkBlock.gen_string`, `blocks.NetworkBlock.add_item`, `blocks.NetworkBlock.add_items`, `blocks.NetworkParameterBlock`, `blocks.NetworkParameterBlock.__init__`, `blocks.NetworkParameterBlock.add_item`, `blocks.NetworkParameterBlock.add_parameter`, `blocks.NetworkCompartmentBlock`, `blocks.NetworkCompartmentBlock.__init__`, `blocks.NetworkCompartmentBlock.add_compartment`, `blocks.NetworkGroupBlock`, `blocks.NetworkGroupBlock.__init__`, `blocks.NetworkGroupBlock.add_group`, `blocks.NetworkSpeciesBlock`, `blocks.NetworkSpeciesBlock.__init__`, `blocks.NetworkSpeciesBlock.add_species`, `blocks.NetworkFunctionBlock`, `blocks.NetworkFunctionBlock.__init__`, `blocks.NetworkFunctionBlock.add_function`, `blocks.NetworkReactionBlock`, `blocks.NetworkReactionBlock.__init__`, `blocks.NetworkReactionBlock.add_reaction`, `blocks.NetworkEnergyPatternBlock`, `blocks.NetworkEnergyPatternBlock.__init__`, `blocks.NetworkEnergyPatternBlock.add_energy_pattern`, `blocks.NetworkPopulationMapBlock`, `blocks.NetworkPopulationMapBlock.__init__`, `blocks.NetworkPopulationMapBlock.add_population_map`, `network.Network`, `network.Network.__init__`, `network.Network.add_block`, `network.Network.add_empty_block`, `network.Network.add_parameters_block`, `network.Network.add_species_block`, `network.Network.add_groups_block`, `network.Network.add_reactions_block`, `network.Network.write_model`, `networkparser.BNGNetworkParser`, `networkparser.BNGNetworkParser.__init__`, `networkparser.BNGNetworkParser.parse_network`, `structs.NetworkObj`, `structs.NetworkObj.__init__`, `structs.NetworkObj.comment`, `structs.NetworkObj.line_label`, `structs.NetworkObj.print_line`, `structs.NetworkParameter`, `structs.NetworkParameter.__init__`, `structs.NetworkParameter.gen_string`, `structs.NetworkCompartment`, `structs.NetworkCompartment.__init__`, `structs.NetworkCompartment.gen_string`, `structs.NetworkGroup`, `structs.NetworkGroup.__init__`, `structs.NetworkGroup.gen_string`, `structs.NetworkSpecies`, `structs.NetworkSpecies.__init__`, `structs.NetworkSpecies.gen_string`, `structs.NetworkFunction`, `structs.NetworkFunction.__init__`, `structs.NetworkFunction.gen_string`, `structs.NetworkReaction`, `structs.NetworkReaction.__init__`, `structs.NetworkReaction.gen_string`, `structs.NetworkEnergyPattern`, `structs.NetworkEnergyPattern.__init__`, `structs.NetworkEnergyPattern.gen_string`, `structs.NetworkPopulationMap`, `structs.NetworkPopulationMap.__init__`, `structs.NetworkPopulationMap.gen_string` | PyBioNetGen's pure-Python .net reader and network object model. BNG3 reads .net files natively, but has no Python `Network` object model. |
| `simulator.csimulator` | `RESULT`, `CSimWrapper`, `CSimWrapper.__init__`, `CSimWrapper.set_species_init`, `CSimWrapper.set_parameters`, `CSimWrapper.simulate`, `CSimulator`, `CSimulator.__init__`, `CSimulator.compile_shared_lib`, `CSimulator.simulator`, `CSimulator.simulate` | PyBioNetGen's compile-to-C simulator. BNG3 simulates natively, so execution needs no replacement, but these classes are gone. |

## Present under another path

| PyBioNetGen symbol | BNG3 location |
|---|---|
| `core.tools.bngsim_backend_helper.main` | `cli.main, main.main` |
