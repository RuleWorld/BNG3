"""BioNetGen CLI using Click."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
@click.version_option(package_name="bionetgen")
def main():
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
    default="ode",
    type=click.Choice(["ode", "ssa", "nf", "pla", "psa"]),
    help="Simulation method.",
)
@click.option(
    "--t-start",
    default=0.0,
    type=float,
    help="Start time (ODE/SSA/PLA/PSA; NF requires zero).",
)
@click.option("--t-end", "-t", default=100.0, type=float, help="End time.")
@click.option("--n-steps", "-n", default=100, type=int, help="Number of output steps.")
@click.option("--rtol", default=1e-8, type=float, help="Relative ODE tolerance.")
@click.option("--atol", default=1e-8, type=float, help="Absolute ODE tolerance.")
@click.option("--seed", default=0, type=int, help="Random seed for stochastic methods.")
@click.option("--pla-config", default="", help="PLA configuration string.")
@click.option(
    "--psa-poplevel",
    default=100.0,
    type=float,
    help="Population threshold for PSA.",
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Output file path."
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
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
):
    """Run a BNGL model simulation."""
    if input_path is not None:
        if model is not None:
            raise click.UsageError("provide either MODEL or --input, not both")
        from bionetgen.compat.runner import run as compatibility_run

        try:
            result = compatibility_run(
                input_path,
                out=output or ".",
                suppress=not verbose,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Results written to {result.path}")
        return

    if model is None:
        raise click.UsageError("MODEL or --input is required")

    from bionetgen import load

    path = str(Path(model).resolve())
    try:
        result = load(path).simulate(
            method=method,
            t_start=t_start,
            t_end=t_end,
            n_steps=n_steps,
            rtol=rtol,
            atol=atol,
            seed=seed,
            pla_config=pla_config,
            psa_poplevel=psa_poplevel,
            verbose=verbose,
        )
    except (TypeError, ValueError) as exc:
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
    elif fmt == "latex":
        _cpp.io.write_latex(cpp_model, output)
    elif fmt in ("net", "sbml", "matlab"):
        network = _cpp.generate_network(cpp_model)
        if fmt == "net":
            _cpp.io.write_net(cpp_model, network, output)
        elif fmt == "sbml":
            _cpp.io.write_sbml(cpp_model, network, output)
        elif fmt == "matlab":
            _cpp.io.write_matlab(cpp_model, network, output)

    click.echo(f"Exported to {output}")


@main.command()
def info():
    """Show BioNetGen installation and runtime information."""
    import bionetgen

    click.echo(f"BioNetGen version: {bionetgen.__version__}")
    click.echo(f"Python package: {Path(bionetgen.__file__).resolve().parent}")
    click.echo(f"Python: {sys.executable}")


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
def plot(input_path, output_path):
    """Plot a BioNetGen data file."""
    from bionetgen.core.tools.plot import BNGPlotter

    output = Path(output_path) if output_path else Path(input_path).with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        BNGPlotter(input_path, str(output)).plot()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Plot written to {output}")


@main.command()
@click.option("--input", "-i", "input_path", default=None, type=click.Path(exists=True))
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option("--open", "open_notebook", is_flag=True, help="Report the notebook path.")
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
        content = content.replace("INPUT_ARG", str(Path(input_path).resolve()).replace("\\", "/"))
    output.write_text(content, encoding="utf-8")
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
@click.option("--colors", "-c", "colors_path", default=None, type=click.Path(exists=True))
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
    required=True,
    type=click.Path(exists=True, dir_okay=False),
)
@click.option("--output", "-o", "output_path", default=None, type=click.Path())
@click.option("--atomize", "-a", is_flag=True, help="Infer molecular structure.")
@click.option("--no-conversion", is_flag=True, help="Disable reaction conversion heuristics.")
@click.option("--no-pathwaycommons", is_flag=True, help="Do not query Pathway Commons.")
def atomize(input_path, output_path, atomize, no_conversion, no_pathwaycommons):
    """Translate an SBML file to BNGL through the Python atomizer."""
    from bionetgen import sbml_to_bngl

    try:
        text = sbml_to_bngl(
            input_path,
            atomize=atomize,
            no_conversion=no_conversion,
            pathwaycommons=not no_pathwaycommons,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

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
@click.option("--atol", default=1e-8, type=float, show_default=True)
@click.option("--seed", default=0, type=int, show_default=True)
@click.option("--pla-config", default="", show_default=False)
@click.option("--psa-poplevel", default=100.0, type=float, show_default=True)
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
    parallel,
    output,
    verbose,
):
    """Run a one-dimensional parameter scan."""

    from bionetgen import load

    bng_model = load(model)
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
        verbose=verbose,
        parallel=parallel,
    )

    frame = scan_result.to_dataframe()
    if output:
        frame.to_csv(output, index=False)
        click.echo(f"Scan results written to {output}")
    else:
        click.echo(frame.to_string(index=False))


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
@click.option("--atol", default=1e-8, type=float, show_default=True)
@click.option("--seed", default=0, type=int, show_default=True)
@click.option("--pla-config", default="", show_default=False)
@click.option("--psa-poplevel", default=100.0, type=float, show_default=True)
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
    delta,
    parallel,
    output,
    verbose,
):
    """Run local sensitivity analysis."""

    from bionetgen import load

    bng_model = load(model)
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
        verbose=verbose,
        delta=delta,
        parallel=parallel,
    )

    frame = result.to_dataframe()
    if output:
        frame.to_csv(output, index=False)
        click.echo(f"Sensitivity matrix written to {output}")
    else:
        click.echo(frame.to_string(index=False))


@main.command()
@click.argument("model", type=click.Path(exists=True))
@click.option(
    "--type",
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
        ]
    ),
    show_default=True,
    help="Visualization to export.",
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Output GraphML path."
)
def visualize(model, viz_type, output):
    """Generate a model visualization graph."""

    from bionetgen import load

    bng_model = load(model)
    graph_text = getattr(bng_model, viz_type)(output)
    if output is None:
        click.echo(graph_text)
    else:
        click.echo(f"Wrote {viz_type} to {output}")


if __name__ == "__main__":
    main()
