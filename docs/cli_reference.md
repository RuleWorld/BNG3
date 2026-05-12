# CLI Reference

The `bionetgen` command-line tool exposes the same in-process backend used by the Python API.

## `bionetgen run`

Run a BNGL model simulation.

```bash
bionetgen run MODEL [OPTIONS]
```

Options:

- `-m, --method [ode|ssa|nf|pla|psa]` simulation method.
- `-t, --t-end FLOAT` end time.
- `-n, --n-steps INT` number of output steps.
- `-o, --output PATH` write tabular output to a file.
- `-v, --verbose` show progress.

Examples:

```bash
bionetgen run model.bngl --method ode --t-end 1000 --n-steps 500
bionetgen run model.bngl -m ssa -o results.tsv
bionetgen run model.bngl -m nf -t 50 -v
```

## `bionetgen scan`

Run a one-dimensional parameter scan.

```bash
bionetgen scan MODEL [OPTIONS]
```

Options:

- `--parameter NAME` parameter to scan.
- `--min FLOAT` minimum value.
- `--max FLOAT` maximum value.
- `--n-points INT` number of scan points.
- `--log-scale` use logarithmic spacing.
- `--method [ode|ssa|nf|pla|psa]` simulation method.
- `--t-end FLOAT` end time.
- `--n-steps INT` number of output steps.
- `--parallel INT` worker process count.
- `-o, --output PATH` write a CSV file.

Examples:

```bash
bionetgen scan model.bngl --parameter k_on --min 0.01 --max 100 --n-points 50
bionetgen scan model.bngl --parameter k_on --log-scale --output scan.csv
```

## `bionetgen sensitivity`

Compute local normalized sensitivities.

```bash
bionetgen sensitivity MODEL [OPTIONS]
```

Options:

- `--parameter NAME` repeatable; if omitted, all parameters are used.
- `--observable NAME` repeatable; if omitted, all observables are used.
- `--method [ode|ssa|nf|pla|psa]` simulation method.
- `--t-end FLOAT` end time.
- `--n-steps INT` number of output steps.
- `--delta FLOAT` relative perturbation size.
- `--parallel INT` worker process count.
- `-o, --output PATH` write a CSV file.

Example:

```bash
bionetgen sensitivity model.bngl --parameter k_on --observable AB
```

## `bionetgen visualize`

Export a visualization graph.

```bash
bionetgen visualize MODEL [OPTIONS]
```

Options:

- `--type [contact_map|regulatory_graph|rule_influence_graph|reaction_network_graph|ruleviz_pattern|ruleviz_operation|process_graph|sbml_multi]` graph type.
- `-o, --output PATH` write the serialized graph to disk.

Examples:

```bash
bionetgen visualize model.bngl --type contact_map -o contact_map.graphml
bionetgen visualize model.bngl --type sbml_multi -o model_multi.xml
```

## `bionetgen execute`

Execute all actions defined in a BNGL model file.

```bash
bionetgen execute MODEL [OPTIONS]
```

Option:

- `-v, --verbose` show progress.

## `bionetgen check`

Parse a BNGL file and report model statistics or syntax errors.

```bash
bionetgen check MODEL
```

Example output:

```bash
OK: /path/to/model.bngl
  Parameters:      12
  Molecule types:  4
  Seed species:    6
  Reaction rules:  8
  Observables:     5
  Actions:         2
```

## `bionetgen export`

Export a model to another format.

```bash
bionetgen export MODEL -f FORMAT -o OUTPUT
```

Formats:

- `xml`
- `net`
- `bngl`
- `sbml`
- `matlab`
- `latex`

Examples:

```bash
bionetgen export model.bngl -f sbml -o model.xml
bionetgen export model.bngl -f matlab -o model.m
bionetgen export model.bngl -f net -o model.net
bionetgen export model.bngl -f latex -o model.tex
```

## Environment Variables

| Variable | Description |
| --- | --- |
| `BIONETGEN_USE_PERL` | Set to `1` to use the legacy Perl BNG2.pl path |
| `BNGPATH` | Path to a legacy BNG2.pl installation for compatibility mode |
