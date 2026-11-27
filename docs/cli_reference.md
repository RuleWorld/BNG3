# CLI Reference

BioNetGen 3 provides two command-line surfaces:

1. **The `bionetgen` Python CLI** (installed with the Python wheel/package; Click-based, exposing 12 subcommands over the in-process C++ engine).
2. **Standalone C++ binaries (`bng_cpp` and `NFsim`)** shipped in the platform CLI archives (`bionetgen-<platform>.tar.gz`) on [GitHub Releases](https://github.com/RuleWorld/BNG3/releases/tag/v3.0.0a1) with no Python or Perl dependency.

For support boundaries see the [Capability Guide](capabilities.md) (and [CAPABILITY_UNION_INVENTORY.md](CAPABILITY_UNION_INVENTORY.md)); final policy is in [DECISIONS.md](DECISIONS.md) and qualification evidence is in [CURRENT_PROGRESS.md](CURRENT_PROGRESS.md).

---

## Global Options (`bionetgen`)

```bash
bionetgen [--version] [--require VERSION | -req VERSION] COMMAND [ARGS]...
```

- `--version` — Print the installed `bionetgen` package version and exit.
- `--require, -req TEXT` — Fail with `BNGVersionError` if the installed BioNetGen version is older than `VERSION` (pinned PyBioNetGen compatibility guard).

---

## `bionetgen run`

Run a BNGL simulation or execute a model's declared action block.

```bash
bionetgen run [MODEL] [OPTIONS]
```

**Two invocation contracts:**

- **Positional `MODEL`** runs one modern simulation (default: `ode`, `t_start=0.0`, `t_end=100.0`, `n_steps=100`, `rtol=1e-8`, `atol=1e-12`, `seed=0`, `psa_poplevel=100.0`) and writes a tab-separated table to `--output` (or prints a completion summary if `--output` is omitted).
- **`--input/-i MODEL`** selects the PyBioNetGen compatibility file runner, which executes declared BNGL actions and treats `--output/-o` as an output directory (default `.`). Explicit `--t-start`, `--t-end`, and `--n-steps` apply to each direct simulation action while preserving action order. Passing `--method` with `--input` opts into one modern simulation; without `--method`, solver-specific options are rejected rather than silently ignored.

Options:

- `-i, --input PATH` — Compatibility file-runner input `.bngl` path (mutually exclusive with positional `MODEL`).
- `-m, --method [ode|ssa|nf|pla|psa|cvode|rm]` — Simulation method (`nf` uses NFnext in positional mode).
- `--t-start FLOAT` — Absolute simulation start time.
- `-t, --t-end FLOAT` — End time.
- `-n, --n-steps INT` — Number of output steps.
- `--rtol FLOAT`, `--atol FLOAT` — ODE relative and absolute tolerances.
- `--seed INT` — Random seed for stochastic methods (`0` = non-reproducible system default).
- `--pla-config TEXT` — PLA configuration string.
- `--psa-poplevel FLOAT` — Population threshold for PSA.
- `-o, --output PATH` — Output `.tsv` file (positional `MODEL`) or output directory (`--input`).
- `-v, --verbose` — Show progress output.
- `-l, --log PATH` — Write worker stdout/stderr diagnostics to a log file (runs in a bounded native subprocess).
- `--timeout INT` — Wall-clock deadline in seconds (runs in a bounded native subprocess).
- `--no-bngsim` — Force native execution in a separate subprocess.
- `--format TEXT` — Input format hint (only `bngl` is accepted; convert other formats first).
- `--traceback-depth INT` — Python traceback depth (default `0`, legacy option).

Examples:

```bash
bionetgen run binding.bngl --method ode --t-end 10 --n-steps 20 --output binding.tsv
bionetgen run binding.bngl -m ssa --seed 42 -o ssa.tsv
bionetgen run binding.bngl -m nf --seed 42 -t 10 -v
bionetgen run --input model_with_actions.bngl --output results_dir
```

---

## `bionetgen execute`

Execute all actions defined in a BNGL model's `begin actions ... end actions` block in process.

```bash
bionetgen execute MODEL [-v|--verbose]
```

Note: In `v3.0.0a1`, BNGL action blocks calling `simulate_nf()` or `simulate({method=>"nf"})` execute embedded NFcore. On **(post-`v3.0.0a1` `main`)**, BNGL actions also accept explicit `method=>"nfnext"` / `method=>"nfcore"` (and `simulate_nf({engine=>"nfnext"|"nfcore"})` / `backend=>...`), while unqualified `simulate({method=>"nf"})` routes to NFnext when no NFcore-only control is present and the model lowers cleanly; see [Network-Free Simulation](network_free_simulation.md).

---

## `bionetgen check`

Parse a BNGL file and report block counts or syntax errors (exits nonzero on `ParseError`).

```bash
bionetgen check MODEL
```

---

## `bionetgen export`

Export a BNGL model to another format.

```bash
bionetgen export MODEL [-f|--format xml|net|bngl|sbml|matlab|latex] -o|--output PATH
```

Default format: `xml`. Formats `net`, `sbml`, and `matlab` automatically generate the reaction network first. Kinetics exporters (`sbml`, `matlab`, `latex`) fail closed on models using energy/barrier patterns, `driven_by()`, or `Arrhenius` rates.

---

## `bionetgen scan`

Run a one-dimensional parameter scan and print an aligned table or save a CSV file (`-o`, using Python's standard `csv` module with no `pandas` dependency; in Python, `ScanResult.to_dataframe()` still requires `bionetgen[plotting]`).

```bash
bionetgen scan MODEL --parameter NAME --min FLOAT --max FLOAT [OPTIONS]
```

Options & defaults:

- `--parameter NAME` (required), `--min FLOAT` (required), `--max FLOAT` (required)
- `--n-points INT` (default `20`), `--log-scale`
- `--method [ode|ssa|nf|pla|psa]` (default `ode`)
- `--t-start FLOAT` (default `0.0`), `--t-end FLOAT` (default `100.0`), `--n-steps INT` (default `100`)
- `--rtol FLOAT` (default `1e-8`), `--atol FLOAT` (default `1e-12`), `--seed INT` (default `0`)
- `--pla-config TEXT`, `--psa-poplevel FLOAT` (default `100.0`)
- `--parallel INT` (default `0`, worker process count)
- `-o, --output PATH` — Optional CSV output path
- `-v, --verbose`

---

## `bionetgen sensitivity`

Compute local normalized finite-difference sensitivities and print an aligned table or save a CSV file (`-o`, using Python's standard `csv` module with no `pandas` dependency; in Python, `SensitivityResult.to_dataframe()` still requires `bionetgen[plotting]`).

```bash
bionetgen sensitivity MODEL [OPTIONS]
```

Options & defaults:

- `--parameter NAME` (repeatable; defaults to all parameters)
- `--observable NAME` (repeatable; defaults to all observables)
- `--method [ode|ssa|nf|pla|psa]` (default `ode`)
- `--t-start FLOAT` (default `0.0`), `--t-end FLOAT` (default `100.0`), `--n-steps INT` (default `100`)
- `--rtol FLOAT` (default `1e-8`), `--atol FLOAT` (default `1e-12`), `--seed INT` (default `0`)
- `--pla-config TEXT`, `--psa-poplevel FLOAT` (default `100.0`)
- `--delta FLOAT` (default `0.01`, relative perturbation size)
- `--parallel INT` (default `0`)
- `-o, --output PATH` — Optional CSV output path
- `-v, --verbose`

---

## `bionetgen visualize`

Export a model visualization graph or SBML Multi file.

```bash
bionetgen visualize [MODEL | -i|--input MODEL] [-t|--type TYPE] [-o|--output PATH]
```

- `-t, --type` (default `contact_map`): `contact_map` (alias `contactmap`), `regulatory_graph` (aliases `regulatory`, `atom_rule`), `rule_influence_graph`, `reaction_network_graph`, `ruleviz_pattern`, `ruleviz_operation`, `process_graph`, `sbml_multi`, or `all` (writes `contact_map`, `regulatory_graph`, `ruleviz_pattern`, and `ruleviz_operation` into an output directory).
- `-o, --output PATH`: file path or directory (prints serialized text to stdout if omitted).

---

## `bionetgen atomize`

Translate an SBML file to BNGL through the Python Atomizer (requires `bionetgen[full]` / `python-libsbml`).

```bash
bionetgen atomize -i|--input MODEL.xml [-o|--output MODEL.bngl] [-a|--atomize] [OPTIONS]
```

Key options:

- `-i, --input PATH` or `--input-file PATH` — Source SBML XML file.
- `-o, --output PATH` or `--output-file PATH` — Destination `.bngl` file or directory.
- `-a, --atomize` — Infer rule-based molecular structure (omit for flat translation).
- `--annotation`, `--molecule-id`, `--ignore`, `--no-conversion`, `--convert-units`, `--no-pathwaycommons`, `--pathwaycommons`, `--memoized-resolver`, `--keep-local-parameters`, `--quiet-mode`.
- `--write-scts`, `--write-sct-graphs` (GraphML output requires `networkx`).
- Legacy Atomizer flags (`--convention-file`, `--naming-conventions`, `--user-structures`, `--isomorphism-check`, `--obs-map-file`, `--bionetgen-analysis`, `--log-level`) automatically select `atomizer_backend="legacy"`.

---

## `bionetgen plot`

Plot a `.gdat`, `.cdat`, or `.scan` data file to an image (requires `bionetgen[plotting]`).

```bash
bionetgen plot -i|--input DATA.gdat [-o|--output PLOT.png] [--legend] \
  [--xmin FLOAT] [--xmax FLOAT] [--ymin FLOAT] [--ymax FLOAT] \
  [--xlabel TEXT] [--ylabel TEXT] [--title TEXT]
```

---

## `bionetgen notebook`

Create a starter Jupyter notebook from the bundled template (outputs cleared; install `bionetgen[notebook]` for an IPython kernel and Matplotlib).

```bash
bionetgen notebook [-i|--input MODEL.bngl] [-o|--output NOTEBOOK.ipynb] [-op|--open]
```

---

## `bionetgen graphdiff`

Compare two GraphML visualization files.

```bash
bionetgen graphdiff -i|--input A.graphml -i2|--input2 B.graphml \
  [-o|--output OUT1] [-o2|--output2 OUT2] [-m|--mode matrix|union] [-c|--colors FILE]
```

---

## `bionetgen info`

Print installed BioNetGen version, package directory, Python executable, and optional detailed runtime info (`-d` / `--detail`). Useful when filing bug reports.

```bash
bionetgen info [--detail]
```

---

## Standalone C++ Binaries (`bng_cpp` and `NFsim`)

Shipped in the `bionetgen-<platform>.tar.gz` release archives (or built from source with `-DBUILD_CLI=ON -DBUILD_NFSIM_CLI=ON`).

### `bng_cpp`

```bash
bng_cpp [--check] [--verbose] [--version] [--outdir DIR] [--console|-i] \
        [--parallel JOBS] [--parallel-dir DIR] <model1.bngl> [model2.bngl ...]
```

- `--check` — Parse and validate without executing actions.
- `--verbose` — Print detailed execution logs.
- `--version` — Print binary version.
- `--outdir DIR` (alias `--output_dir DIR`) — Write output files into `DIR` **(post-`v3.0.0a1` `main` only; added in PR `#1056`)**.
- `--console, -i` — Interactive console mode (cannot combine with `--parallel`).
- `--parallel JOBS` (alias `--jobs`) / `--parallel-dir DIR` — Run multiple models concurrently in isolated child processes.

### `NFsim`

Classic NFsim command-line interface over embedded NFcore (`NFsim -help` prints all flags):

```bash
NFsim -xml MODEL.xml -sim DURATION -oSteps STEPS [-seed SEED] [-utl N] [-equil T] [-o OUT.gdat] [-v]
NFsim -rnf SCRIPT.rnf
```

- `-i TIME` — Set absolute simulation start time (default `0`) **(post-`v3.0.0a1` `main` only; added in PR `#1052`)**.

---

## Environment Variables

| Variable | Effect |
| --- | --- |
| `BIONETGEN_FINITE_BACKEND` | Override finite-network backend selection (`auto`, `native`, or `bngsim` when built with `BUILD_BNGSIM_ADAPTER=ON`). |
| `BNG_NFSIM_REQUIRE_DIRECT` | When set, forbids XML fallback in embedded NFcore (`construction_path="direct"` required). |
| `BNG_NFSIM_ALLOW_XML_FALLBACK` | When set, permits embedded NFcore to fall back to in-memory BNG-XML if direct construction declines a model. |
| `BNG_NFSIM_FORCE_XML` | When set, forces embedded NFcore through the in-memory XML initialization route. |
| `BNG_NFSIM_GENERAL_ENERGY` | Set to `1` to enable experimental `begin barrier patterns` and `driven_by()` reservoir work ([nonequilibrium_energy.md](nonequilibrium_energy.md)). |
| `BIONETGEN_USE_PERL` | Set to `1` to select the legacy Perl compatibility path in Python `bionetgen.run(path)` and `bionetgen.load(path).execute()`. `bionetgen run MODEL` CLI is unavailable in this mode. |
| `BNGPATH` | Path to a `BNG2.pl` installation used when `BIONETGEN_USE_PERL=1` or by legacy compatibility helpers. |
