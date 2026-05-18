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
@click.argument("model", type=click.Path(exists=True))
@click.option(
    "--method",
    "-m",
    default="ode",
    type=click.Choice(["ode", "ssa", "nf"]),
    help="Simulation method.",
)
@click.option("--t-end", "-t", default=100.0, type=float, help="End time.")
@click.option("--n-steps", "-n", default=100, type=int, help="Number of output steps.")
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Output file path."
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def run(model, method, t_end, n_steps, output, verbose):
    """Run a BNGL model simulation."""
    from bionetgen import _bionetgen_cpp as _cpp

    path = str(Path(model).resolve())
    cpp_model = _cpp.parse_file(path)

    if method == "nf":
        result = _cpp.simulate_nf(
            cpp_model, t_end=t_end, n_steps=n_steps, verbose=verbose
        )
    else:
        network = _cpp.generate_network(cpp_model)
        if method == "ode":
            result = _cpp.simulate_ode(cpp_model, network, t_end=t_end, n_steps=n_steps)
        else:
            result = _cpp.simulate_ssa(cpp_model, network, t_end=t_end, n_steps=n_steps)

    if output:
        import numpy as np

        time = result["time"]
        obs = result.get("observables", {})
        header = "time\t" + "\t".join(obs.keys()) if obs else "time"
        data = [time] + list(obs.values())
        np.savetxt(
            output, np.column_stack(data), header=header, delimiter="\t", comments="#"
        )
        if verbose:
            click.echo(f"Results written to {output}")
    else:
        click.echo(f"Simulation complete: {len(result['time'])} time points")


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
    "--parallel", default=0, type=int, show_default=True, help="Worker process count."
)
@click.option(
    "--output", "-o", default=None, type=click.Path(), help="Optional CSV output path."
)
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
    parallel,
    output,
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
        t_end=t_end,
        n_steps=n_steps,
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
def sensitivity(
    model,
    parameter_names,
    observable_names,
    method,
    t_end,
    n_steps,
    delta,
    parallel,
    output,
):
    """Run local sensitivity analysis."""

    from bionetgen import load

    bng_model = load(model)
    result = bng_model.sensitivity_analysis(
        parameters=list(parameter_names) or None,
        observables=list(observable_names) or None,
        method=method,
        t_end=t_end,
        n_steps=n_steps,
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
