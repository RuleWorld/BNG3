"""BioNetGen CLI using Click."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import click


def _emit_table(headers, rows, output, written_message):
    """Write a table to CSV or print an aligned text table without pandas."""
    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        click.echo(written_message)
        return

    str_headers = [str(header) for header in headers]
    str_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in str_headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(widths):
                widths[idx] = max(widths[idx], len(cell))
    header_line = "  ".join(
        header.rjust(widths[idx]) if idx > 0 else header.ljust(widths[idx])
        for idx, header in enumerate(str_headers)
    )
    lines = [header_line]
    for row in str_rows:
        lines.append(
            "  ".join(
                cell.rjust(widths[idx]) if idx > 0 else cell.ljust(widths[idx])
                for idx, cell in enumerate(row)
            )
        )
    click.echo("\n".join(lines))


def _require_callback(ctx, param, value):
    """Apply the pinned PyBioNetGen ``--require`` version guard."""
    if value is None:
        return None
    from packaging.version import parse

    from bionetgen.core.exc import BNGVersionError
    from bionetgen.core.version import get_version

    current = get_version()
    if parse(current) < parse(value):
        raise BNGVersionError(current, value)
    return value


@click.group()
@click.version_option(None, "--version", package_name="bionetgen")
@click.option(
    "--require",
    "-req",
    callback=_require_callback,
    is_eager=True,
    default=None,
    help="Require at least this BNG version before running a command.",
)
def main(require):
    """BioNetGen: Rule-based modeling of biochemical systems."""
    pass


@main.command()
@click.argument("model", required=False, type=click.Path(exists=True))
@click.option(
    "--input",
    "-i",
    "input_path",
    default=None,
    type=click.Path(exists=True),
    help="Legacy PyBioNetGen input path (use with an output directory).",
)
@click.option(
    "--method",
    "-m",
    default=None,
    type=click.Choice(["ode", "ssa", "nf", "pla", "psa", "cvode", "rm"]),
    help="Simulation method.",
)
@click.option(
    "--t-start",
    default=None,
    type=float,
    help="Absolute simulation start time.",
)
@click.option("--t-end", "-t", default=None, type=float, help="End time.")
@click.option("--n-steps", "-n", default=None, type=int, help="Number of output steps.")
@click.option("--rtol", default=None, type=float, help="Relative ODE tolerance.")
@click.option("--atol", default=None, type=float, help="Absolute ODE tolerance.")
@click.option(
    "--seed", default=None, type=int, help="Random seed for stochastic methods."
)
@click.option("--pla-config", default=None, help="PLA configuration string.")
@click.option(
    "--psa-poplevel",
    default=None,
    type=float,
    help="Population threshold for PSA.",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output file or directory path.",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
@click.option(
    "-l", "--log", "log_file", default=None, type=click.Path(), help="Log file path."
)
@click.option(
    "--traceback-depth", default=0, type=int, help="Traceback depth (legacy)."
)
@click.option(
    "--format",
    "format_hint",
    default=None,
    type=str,
    help="Input format (bngl).",
)
@click.option(
    "--backend",
    default=None,
    type=click.Choice(["auto", "native", "bngsim"], case_sensitive=False),
    help="Finite-network simulation backend (default: native via auto; bngsim is opt-in).",
)
@click.option(
    "--no-bngsim",
    is_flag=True,
    default=False,
    help="Run in a separate process using the native backend.",
)
@click.option(
    "--timeout", default=None, type=int, help="Wall-clock deadline in seconds."
)
def run(
    model,
    input_path,
    method,
    t_start,
    t_end,
    n_steps,
    rtol,
    atol,
    seed,
    pla_config,
    psa_poplevel,
    output,
    verbose,
    log_file,
    traceback_depth,
    format_hint,
    backend,
    no_bngsim,
    timeout,
):
    """Run a BNGL model simulation."""
    sys.tracebacklimit = traceback_depth
    selected_backend = backend.lower() if backend is not None else None
    if no_bngsim and selected_backend == "bngsim":
        raise click.UsageError("--no-bngsim cannot be combined with --backend bngsim")
    if format_hint is not None:
        if format_hint.lower() != "bngl":
            raise click.UsageError(
                "run accepts --format bngl; convert other formats first"
            )
        format_hint = "bngl"
        selected_input = input_path or model
        if selected_input and Path(selected_input).suffix.lower() != ".bngl":
            raise click.UsageError("--format bngl requires a .bngl input file")
    if input_path is not None:
        if model is not None:
            raise click.UsageError("provide either MODEL or --input, not both")
        from bionetgen.compat.runner import run as compatibility_run

        try:
            result = compatibility_run(
                input_path,
                out=output or ".",
                suppress=not verbose,
                method=method,
                t_start=t_start,
                t_end=t_end,
                n_steps=n_steps,
                rtol=rtol,
                atol=atol,
                seed=seed,
                pla_config=pla_config,
                psa_poplevel=psa_poplevel,
                backend="native" if no_bngsim else selected_backend,
                timeout=timeout,
                format=format_hint,
                log_file=log_file,
                simulator="subprocess" if no_bngsim else "auto",
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        result_path = getattr(result, "path", output or ".")
        click.echo(f"Results written to {result_path}")
        return

    if model is None:
        raise click.UsageError("MODEL or --input is required")
    from bionetgen import load

    path = str(Path(model).resolve())
    try:
        options = {
            "method": method or "ode",
            "t_start": 0.0 if t_start is None else t_start,
            "t_end": 100.0 if t_end is None else t_end,
            "n_steps": 100 if n_steps is None else n_steps,
            "rtol": 1e-8 if rtol is None else rtol,
            "atol": 1e-12 if atol is None else atol,
            "seed": 0 if seed is None else seed,
            "pla_config": "" if pla_config is None else pla_config,
            "psa_poplevel": 100.0 if psa_poplevel is None else psa_poplevel,
            "verbose": verbose or log_file is not None,
        }
        if no_bngsim:
            options["backend"] = "native"
        elif selected_backend is not None:
            options["backend"] = selected_backend
        if log_file is not None or timeout is not None or no_bngsim:
            from tempfile import TemporaryDirectory

            from bionetgen.compat._native_process import execute_native

            with TemporaryDirectory(prefix="bng3-cli-") as directory:
                result = execute_native(
                    path,
                    directory,
                    suppress=not verbose,
                    timeout=timeout,
                    log_file=log_file,
                    options=options,
                    result_file=Path(directory) / "simulation.npz",
                )
        else:
            result = load(path).simulate(**options)
    except Exception as exc:
        raise click.ClickException(str(exc).replace("t_start", "t-start")) from exc

    if output:
        import numpy as np

        time = result.time
        obs = result.observables
        header = "time\t" + "\t".join(obs.keys()) if obs else "time"
        data = [time] + list(obs.values())
        np.savetxt(
            output, np.column_stack(data), header=header, delimiter="\t", comments="#"
        )
        if verbose:
            click.echo(f"Results written to {output}")
    else:
        click.echo(f"Simulation complete: {len(result.time)} time points")


@main.command()
@click.argument("model", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def execute(model, verbose):
    """Execute all actions in a BNGL model file."""
    from bionetgen import _bionetgen_cpp as _cpp

    path = str(Path(model).resolve())
    cpp_model = _cpp.parse_file(path)
    _cpp.execute(cpp_model, path, verbose=verbose)
    click.echo("Done.")


@main.command()
@click.argument("model", type=click.Path(exists=True))
def check(model):
    """Parse a BNGL file and report any syntax errors."""
    from bionetgen import _bionetgen_cpp as _cpp

    path = str(Path(model).resolve())
    try:
        cpp_model = _cpp.parse_file(path)
        click.echo(f"OK: {path}")
        click.echo(f"  Parameters:      {len(cpp_model.parameters)}")
        click.echo(f"  Molecule types:  {len(cpp_model.molecule_types)}")
        click.echo(f"  Seed species:    {len(cpp_model.seed_species)}")
        click.echo(f"  Reaction rules:  {len(cpp_model.reaction_rules)}")
        click.echo(f"  Observables:     {len(cpp_model.observables)}")
        click.echo(f"  Actions:         {len(cpp_model.actions)}")
    except _cpp.ParseError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("model", type=click.Path(exists=True))
@click.option(
    "--format",
    "-f",
    "fmt",
    default="xml",
    type=click.Choice(["xml", "net", "bngl", "sbml", "matlab", "latex"]),
    help="Output format.",
)
@click.option(
    "--output", "-o", required=True, type=click.Path(), help="Output file path."
)
def export(model, fmt, output):
    """Export a model to another format."""
    from bionetgen import _bionetgen_cpp as _cpp

    path = str(Path(model).resolve())
    cpp_model = _cpp.parse_file(path)

    if fmt == "xml":
        _cpp.io.write_xml(cpp_model, output)
    elif fmt == "bngl":
        _cpp.io.write_bngl(cpp_model, output)
    elif fmt in ("net", "sbml", "matlab", "latex"):
        network = _cpp.generate_network(cpp_model)
        if fmt == "net":
            _cpp.io.write_net(cpp_model, network, output)
        elif fmt == "sbml":
            _cpp.io.write_sbml(cpp_model, network, output)
        elif fmt == "matlab":
            _cpp.io.write_matlab(cpp_model, network, output)
        elif fmt == "latex":
            _cpp.io.write_latex(cpp_model, network, output)

    click.echo(f"Exported to {output}")


@main.command()
@click.option(
    "-d", "--detail", is_flag=True, default=False, help="Show detailed information."
)
def info(detail):
    """Show BioNetGen installation and runtime information."""
    import bionetgen

    click.echo(f"BioNetGen version: {bionetgen.__version__}")
    click.echo(f"Python package: {Path(bionetgen.__file__).resolve().parent}")
    click.echo(f"Python: {sys.executable}")
    if detail:
        click.echo("Default finite backend: native")
        if hasattr(bionetgen, "bngsim_capabilities"):
            try:
                caps = bionetgen.bngsim_capabilities()
                if caps.get("available"):
                    click.echo(
                        f"Optional BNGsim backend: available "
                        f"(provider={caps.get('provider')}, version={caps.get('version')})"
                    )
                else:
                    click.echo("Optional BNGsim backend: unavailable")
            except Exception:
                pass
        try:
            from bionetgen.core.tools.info import BNGInfo

            info_obj = BNGInfo(config=getattr(bionetgen, "defaults", None))
            info_obj.gatherInfo()
            info_obj.messageGeneration()
            for line in getattr(info_obj, "info_message", "").splitlines():
                if line.strip():
                    click.echo(line)
        except Exception:
            pass


@main.command()
@click.option(
    "--input",
    "-i",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Input .gdat, .cdat, or .scan file.",
)
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option("--legend", is_flag=True, default=False, help="Show legend.")
@click.option("--xmin", default=None, type=float, help="x-axis minimum.")
@click.option("--xmax", default=None, type=float, help="x-axis maximum.")
@click.option("--ymin", default=None, type=float, help="y-axis minimum.")
@click.option("--ymax", default=None, type=float, help="y-axis maximum.")
@click.option("--xlabel", default=None, type=str, help="x-axis label.")
@click.option("--ylabel", default=None, type=str, help="y-axis label.")
@click.option("--title", default=None, type=str, help="Plot title.")
def plot(
    input_path,
    output_path,
    legend,
    xmin,
    xmax,
    ymin,
    ymax,
    xlabel,
    ylabel,
    title,
):
    """Plot a BioNetGen data file."""
    from bionetgen.core.tools.plot import BNGPlotter

    output = Path(output_path) if output_path else Path(input_path).with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        BNGPlotter(
            input_path,
            str(output),
            legend=legend,
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            xlabel=xlabel,
            ylabel=ylabel,
            title=title,
        ).plot()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Plot written to {output}")


@main.command()
@click.option("--input", "-i", "input_path", default=None, type=click.Path(exists=True))
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option(
    "--open",
    "-op",
    "open_notebook",
    is_flag=True,
    help="Report the notebook path.",
)
def notebook(input_path, output_path, open_notebook):
    """Create a Jupyter notebook from the bundled BioNetGen template."""
    assets = Path(__file__).resolve().parent / "assets"
    if input_path:
        template = assets / "bionetgen-temp.ipynb"
        default_output = Path(input_path).with_suffix(".ipynb")
    else:
        template = assets / "bionetgen.ipynb"
        default_output = Path.cwd() / "bionetgen.ipynb"
    output = Path(output_path) if output_path else default_output
    if output.exists() and output.is_dir():
        output = output / default_output.name
    output.parent.mkdir(parents=True, exist_ok=True)
    content = template.read_text(encoding="utf-8")
    if input_path:
        content = content.replace(
            "INPUT_ARG", str(Path(input_path).resolve()).replace("\\", "/")
        )
    notebook_data = json.loads(content)
    for cell in notebook_data.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
    output.write_text(json.dumps(notebook_data, indent=1) + "\n", encoding="utf-8")
    click.echo(f"Notebook written to {output}")
    if open_notebook:
        click.echo("Open the notebook with Jupyter or your preferred notebook viewer.")


@main.command()
@click.option(
    "--input",
    "-i",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--input2",
    "-i2",
    "input2_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option("--output2", "-o2", "output2_path", default=None, type=click.Path())
@click.option("--mode", "-m", default="matrix", type=click.Choice(["matrix", "union"]))
@click.option(
    "--colors", "-c", "colors_path", default=None, type=click.Path(exists=True)
)
def graphdiff(input_path, input2_path, output_path, output2_path, mode, colors_path):
    """Compare two GraphML visualization outputs."""
    from bionetgen.core.tools.gdiff import BNGGdiff

    for candidate in (output_path, output2_path):
        if candidate:
            Path(candidate).parent.mkdir(parents=True, exist_ok=True)
    try:
        BNGGdiff(
            input_path,
            input2_path,
            out=output_path,
            out2=output2_path,
            mode=mode,
            colors=colors_path,
        ).run()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Graph diff complete")


@main.command()
@click.option(
    "--input",
    "-i",
    "input_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option("--atomize", "-a", is_flag=True, help="Infer molecular structure.")
@click.option(
    "--no-conversion", is_flag=True, help="Disable reaction conversion heuristics."
)
@click.option("--no-pathwaycommons", is_flag=True, help="Do not query Pathway Commons.")
@click.option("--input-file", "input_file", type=click.Path(exists=True), default=None)
@click.option("--output-file", "output_file", type=click.Path(), default=None)
@click.option("--annotation", is_flag=True, default=False)
@click.option("--convention-file", type=click.Path(exists=True), default=None)
@click.option("--naming-conventions", default=None)
@click.option("--user-structures", default=None)
@click.option("--molecule-id", "molecule_id", is_flag=True, default=False)
@click.option("--isomorphism-check", is_flag=True, default=False)
@click.option("--ignore", "ignore_errors", is_flag=True, default=False)
@click.option("--memoized-resolver", is_flag=True, default=False)
@click.option("--keep-local-parameters", is_flag=True, default=False)
@click.option("--quiet-mode", is_flag=True, default=False)
@click.option("--obs-map-file", type=click.Path(), default=None)
@click.option(
    "--log-level",
    type=click.Choice(["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]),
    default=None,
)
@click.option("--bionetgen-analysis", type=click.Path(), default=None)
@click.option("--convert-units", is_flag=True, default=False)
@click.option("--pathwaycommons", "use_pathwaycommons", is_flag=True, default=False)
@click.option("--write-scts", is_flag=True, default=False)
@click.option("--write-sct-graphs", is_flag=True, default=False)
def atomize(
    input_path,
    output_path,
    atomize,
    no_conversion,
    no_pathwaycommons,
    input_file,
    output_file,
    annotation,
    convention_file,
    naming_conventions,
    user_structures,
    molecule_id,
    isomorphism_check,
    ignore_errors,
    memoized_resolver,
    keep_local_parameters,
    quiet_mode,
    obs_map_file,
    log_level,
    bionetgen_analysis,
    convert_units,
    use_pathwaycommons,
    write_scts,
    write_sct_graphs,
):
    """Translate an SBML file to BNGL through the Python atomizer."""
    from bionetgen import sbml_to_bngl

    source = input_path or input_file
    if source is None:
        raise click.UsageError("an input model is required (--input or --input-file)")

    options = {
        "annotation": annotation,
        "molecule_id": molecule_id,
        "use_id": molecule_id,
        "ignore": ignore_errors,
        "no_conversion": no_conversion or not convert_units,
        "pathwaycommons": not no_pathwaycommons and use_pathwaycommons,
        "memoized_resolver": memoized_resolver,
        "replace_local_parameters": not keep_local_parameters,
        "quiet_mode": quiet_mode,
    }
    if log_level is not None:
        options["log_level"] = log_level
    for key, value in (
        ("convention_file", convention_file),
        ("naming_conventions", naming_conventions),
        ("user_structures", user_structures),
        ("isomorphism_check", isomorphism_check),
        ("obs_map_file", obs_map_file),
        ("bionetgen_analysis", bionetgen_analysis),
    ):
        if value is not None:
            options[key] = value
    if any(
        key in options
        for key in (
            "convention_file",
            "naming_conventions",
            "user_structures",
            "isomorphism_check",
            "obs_map_file",
            "bionetgen_analysis",
            "log_level",
        )
    ):
        options["atomizer_backend"] = "legacy"

    try:
        if write_scts:
            from bionetgen.sbml import atomize_sbml_with_sct

            text, sct_tables = atomize_sbml_with_sct(
                source, atomize=atomize, annotation=annotation, quiet_mode=quiet_mode
            )
            stem = Path(input_path or input_file or source).stem
            sct_path = (
                Path(output_path or output_file or source).parent
            ) / f"{stem}_scts.json"
            sct_path.write_text(
                json.dumps(sct_tables, indent=2) + "\n", encoding="utf-8"
            )
            click.echo(f"SCT tables written to {sct_path}")
            if write_sct_graphs:
                try:
                    import networkx as nx
                except ImportError as exc:
                    raise click.ClickException(
                        "graphml SCT output requires the networkx extra"
                    ) from exc
                for graph_name, nodes in sct_tables.items():
                    graph = nx.Graph()
                    for node, neighbours in nodes.items():
                        graph.add_node(node)
                        for neighbour in neighbours:
                            graph.add_edge(node, neighbour)
                    graph_path = sct_path.with_name(f"{stem}_{graph_name}.graphml")
                    nx.write_graphml(graph, graph_path)
                    click.echo(f"SCT graph written to {graph_path}")
        else:
            text = sbml_to_bngl(source, atomize=atomize, **options)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path is None:
        output_path = output_file

    if output_path is None:
        output = Path(input_path).with_suffix(".bngl")
    else:
        output = Path(output_path)
        if output.exists() and output.is_dir():
            output = output / (Path(input_path).stem + ".bngl")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    click.echo(f"BNGL written to {output}")


@main.command()
@click.argument("model", type=click.Path(exists=True))
@click.option("--parameter", "parameter_name", required=True, help="Parameter to scan.")
@click.option(
    "--min", "min_value", required=True, type=float, help="Minimum parameter value."
)
@click.option(
    "--max", "max_value", required=True, type=float, help="Maximum parameter value."
)
@click.option(
    "--n-points", default=20, type=int, show_default=True, help="Number of scan points."
)
@click.option("--log-scale", is_flag=True, help="Use logarithmic spacing.")
@click.option(
    "--method",
    default="ode",
    type=click.Choice(["ode", "ssa", "nf", "pla", "psa"]),
    show_default=True,
    help="Simulation method.",
)
@click.option("--t-end", default=100.0, type=float, show_default=True, help="End time.")
@click.option(
    "--n-steps",
    default=100,
    type=int,
    show_default=True,
    help="Number of output steps.",
)
@click.option(
    "--t-start", default=0.0, type=float, show_default=True, help="Start time."
)
@click.option("--rtol", default=1e-8, type=float, show_default=True)
@click.option("--atol", default=1e-12, type=float, show_default=True)
@click.option("--seed", default=0, type=int, show_default=True)
@click.option("--pla-config", default="", show_default=False)
@click.option("--psa-poplevel", default=100.0, type=float, show_default=True)
@click.option(
    "--backend",
    default=None,
    type=click.Choice(["auto", "native", "bngsim"], case_sensitive=False),
    help="Finite-network simulation backend (default: native via auto; bngsim is opt-in).",
)
@click.option(
    "--parallel", default=0, type=int, show_default=True, help="Worker process count."
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Optional CSV output path."
)
@click.option("--verbose", "-v", is_flag=True, help="Show progress.")
def scan(
    model,
    parameter_name,
    min_value,
    max_value,
    n_points,
    log_scale,
    method,
    t_end,
    n_steps,
    t_start,
    rtol,
    atol,
    seed,
    pla_config,
    psa_poplevel,
    backend,
    parallel,
    output,
    verbose,
):
    """Run a one-dimensional parameter scan."""

    from bionetgen import load

    bng_model = load(model)
    try:
        scan_result = bng_model.parameter_scan(
            parameter=parameter_name,
            min=min_value,
            max=max_value,
            n_points=n_points,
            log_scale=log_scale,
            method=method,
            t_start=t_start,
            t_end=t_end,
            n_steps=n_steps,
            rtol=rtol,
            atol=atol,
            seed=seed,
            pla_config=pla_config,
            psa_poplevel=psa_poplevel,
            backend=backend.lower() if backend is not None else None,
            verbose=verbose,
            parallel=parallel,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not scan_result.results:
        headers = [scan_result.parameter_name, "time"]
        rows = []
    else:
        obs_names = list(scan_result.observable_names)
        headers = [scan_result.parameter_name, "time", *obs_names]
        rows = []
        for param_val, sim_res in zip(
            scan_result.parameter_values, scan_result.results
        ):
            times = sim_res.time
            obs_cols = [sim_res.observables[name] for name in obs_names]
            for idx in range(len(times)):
                rows.append(
                    [
                        float(param_val),
                        float(times[idx]),
                        *(float(col[idx]) for col in obs_cols),
                    ]
                )
    _emit_table(headers, rows, output, f"Scan results written to {output}")


@main.command()
@click.argument("model", type=click.Path(exists=True))
@click.option(
    "--parameter",
    "parameter_names",
    multiple=True,
    help="Parameter to include; repeat for multiple parameters.",
)
@click.option(
    "--observable",
    "observable_names",
    multiple=True,
    help="Observable to include; repeat for multiple observables.",
)
@click.option(
    "--method",
    default="ode",
    type=click.Choice(["ode", "ssa", "nf", "pla", "psa"]),
    show_default=True,
)
@click.option("--t-end", default=100.0, type=float, show_default=True)
@click.option("--n-steps", default=100, type=int, show_default=True)
@click.option("--t-start", default=0.0, type=float, show_default=True)
@click.option("--rtol", default=1e-8, type=float, show_default=True)
@click.option("--atol", default=1e-12, type=float, show_default=True)
@click.option("--seed", default=0, type=int, show_default=True)
@click.option("--pla-config", default="", show_default=False)
@click.option("--psa-poplevel", default=100.0, type=float, show_default=True)
@click.option(
    "--backend",
    default=None,
    type=click.Choice(["auto", "native", "bngsim"], case_sensitive=False),
    help="Finite-network simulation backend (default: native via auto; bngsim is opt-in).",
)
@click.option(
    "--delta",
    default=0.01,
    type=float,
    show_default=True,
    help="Relative perturbation size.",
)
@click.option(
    "--parallel", default=0, type=int, show_default=True, help="Worker process count."
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Optional CSV output path."
)
@click.option("--verbose", "-v", is_flag=True, help="Show progress.")
def sensitivity(
    model,
    parameter_names,
    observable_names,
    method,
    t_end,
    n_steps,
    t_start,
    rtol,
    atol,
    seed,
    pla_config,
    psa_poplevel,
    backend,
    delta,
    parallel,
    output,
    verbose,
):
    """Run local sensitivity analysis."""

    from bionetgen import load

    bng_model = load(model)
    try:
        result = bng_model.sensitivity_analysis(
            parameters=list(parameter_names) or None,
            observables=list(observable_names) or None,
            method=method,
            t_start=t_start,
            t_end=t_end,
            n_steps=n_steps,
            rtol=rtol,
            atol=atol,
            seed=seed,
            pla_config=pla_config,
            psa_poplevel=psa_poplevel,
            backend=backend.lower() if backend is not None else None,
            verbose=verbose,
            delta=delta,
            parallel=parallel,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    headers = ["parameter", *result.observable_names]
    rows = [
        [param_name, *(float(val) for val in row)]
        for param_name, row in zip(result.parameter_names, result.matrix)
    ]
    _emit_table(headers, rows, output, f"Sensitivity matrix written to {output}")


@main.command()
@click.argument("model", required=False, type=click.Path(exists=True))
@click.option(
    "--input",
    "-i",
    "input_path",
    default=None,
    type=click.Path(exists=True),
    help="Legacy input model path.",
)
@click.option(
    "--type",
    "-t",
    "viz_type",
    default="contact_map",
    type=click.Choice(
        [
            "contact_map",
            "regulatory_graph",
            "rule_influence_graph",
            "reaction_network_graph",
            "ruleviz_pattern",
            "ruleviz_operation",
            "process_graph",
            "sbml_multi",
            "contactmap",
            "regulatory",
            "atom_rule",
            "all",
        ]
    ),
    show_default=True,
    help="Visualization to export.",
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Output GraphML path."
)
def visualize(model, input_path, viz_type, output):
    """Generate a model visualization graph."""

    from bionetgen import load

    if input_path is not None:
        if model is not None:
            raise click.UsageError("provide either MODEL or --input, not both")
        model = input_path
    if model is None:
        raise click.UsageError("MODEL or --input is required")

    bng_model = load(model)
    aliases = {
        "contactmap": "contact_map",
        "regulatory": "regulatory_graph",
        "atom_rule": "regulatory_graph",
    }
    canonical = aliases.get(viz_type, viz_type)
    if canonical == "all":
        output_dir = Path(output) if output else Path.cwd()
        if output and output_dir.suffix:
            raise click.ClickException(
                "--output for visualize --type all must be a directory"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        methods = [
            "contact_map",
            "regulatory_graph",
            "ruleviz_pattern",
            "ruleviz_operation",
        ]
        for method in methods:
            destination = output_dir / f"{method}.graphml"
            getattr(bng_model, method)(str(destination))
        click.echo(f"Wrote {len(methods)} visualizations to {output_dir}")
        return

    destination = None
    if output:
        destination = Path(output)
        if destination.exists() and destination.is_dir():
            destination = destination / f"{canonical}.graphml"
        elif not destination.exists() and not destination.suffix:
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination / f"{canonical}.graphml"
    graph_text = getattr(bng_model, canonical)(
        None if destination is None else str(destination)
    )
    if destination is None:
        click.echo(graph_text)
    else:
        click.echo(f"Wrote {canonical} to {destination}")


if __name__ == "__main__":
    main()
