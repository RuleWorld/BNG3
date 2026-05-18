"""HTML display helpers for notebook and rich repr support."""

from __future__ import annotations

import base64
import html
from typing import Iterable, Optional, Sequence

import numpy as np


def _escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    head = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows) if body_rows else "<tr><td colspan=99>None</td></tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _details(title: str, headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    return (
        "<details open>"
        f"<summary>{_escape(title)}</summary>"
        f"{_table(headers, rows)}"
        "</details>"
    )


def _embed_svg(svg: str, alt: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img alt="{_escape(alt)}" src="data:image/svg+xml;base64,{encoded}" />'


def _line_chart_svg(
    x_values: Sequence[float],
    series: Sequence[Sequence[float]],
    labels: Sequence[str],
    *,
    title: str,
    x_label: str,
    y_label: str,
    width: int = 640,
    height: int = 320,
) -> str:
    x = np.asarray(x_values, dtype=float)
    y_series = [np.asarray(values, dtype=float) for values in series]
    if x.size == 0 or not y_series:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<text x="20" y="30">{_escape(title)}: no data</text></svg>'
        )

    x_min = float(np.min(x))
    x_max = float(np.max(x))
    y_min = float(min(np.min(values) for values in y_series))
    y_max = float(max(np.max(values) for values in y_series))
    if np.isclose(x_min, x_max):
        x_max = x_min + 1.0
    if np.isclose(y_min, y_max):
        y_max = y_min + 1.0

    margin_left = 60
    margin_right = 20
    margin_top = 30
    margin_bottom = 50
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    def x_map(value: float) -> float:
        return margin_left + (float(value) - x_min) / (x_max - x_min) * plot_width

    def y_map(value: float) -> float:
        return margin_top + plot_height - (float(value) - y_min) / (y_max - y_min) * plot_height

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin_left}" y="18" font-size="14" font-weight="bold">{_escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333" />',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333" />',
        f'<text x="{margin_left + plot_width / 2}" y="{height - 8}" text-anchor="middle" font-size="12">{_escape(x_label)}</text>',
        f'<text x="16" y="{margin_top + plot_height / 2}" transform="rotate(-90 16,{margin_top + plot_height / 2})" text-anchor="middle" font-size="12">{_escape(y_label)}</text>',
    ]

    tick_count = 4
    for idx in range(tick_count + 1):
        fraction = idx / tick_count
        x_tick = x_min + fraction * (x_max - x_min)
        x_pos = x_map(x_tick)
        parts.append(
            f'<line x1="{x_pos:.2f}" y1="{margin_top + plot_height}" x2="{x_pos:.2f}" y2="{margin_top + plot_height + 5}" stroke="#333" />'
        )
        parts.append(
            f'<text x="{x_pos:.2f}" y="{margin_top + plot_height + 18}" text-anchor="middle" font-size="10">{x_tick:.3g}</text>'
        )

    for idx in range(tick_count + 1):
        fraction = idx / tick_count
        y_tick = y_min + fraction * (y_max - y_min)
        y_pos = y_map(y_tick)
        parts.append(
            f'<line x1="{margin_left - 5}" y1="{y_pos:.2f}" x2="{margin_left}" y2="{y_pos:.2f}" stroke="#333" />'
        )
        parts.append(
            f'<text x="{margin_left - 8}" y="{y_pos + 3:.2f}" text-anchor="end" font-size="10">{y_tick:.3g}</text>'
        )

    legend_x = margin_left + plot_width - 10
    legend_y = margin_top + 10
    for index, (values, label) in enumerate(zip(y_series, labels)):
        color = colors[index % len(colors)]
        coords = " ".join(f"{x_map(xv):.2f},{y_map(yv):.2f}" for xv, yv in zip(x, values))
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coords}" />'
        )
        parts.append(
            f'<rect x="{legend_x - 12}" y="{legend_y + index * 18 - 9}" width="10" height="10" fill="{color}" />'
        )
        parts.append(
            f'<text x="{legend_x}" y="{legend_y + index * 18}" font-size="10">{_escape(label)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _heatmap_svg(
    matrix: Sequence[Sequence[float]],
    x_values: Sequence[float],
    y_values: Sequence[float],
    *,
    title: str,
    x_label: str,
    y_label: str,
    width: int = 640,
    height: int = 420,
) -> str:
    values = np.asarray(matrix, dtype=float)
    if values.size == 0:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<text x="20" y="30">{_escape(title)}: no data</text></svg>'
        )

    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    x_min = float(np.min(x))
    x_max = float(np.max(x))
    y_min = float(np.min(y))
    y_max = float(np.max(y))
    if np.isclose(x_min, x_max):
        x_max = x_min + 1.0
    if np.isclose(y_min, y_max):
        y_max = y_min + 1.0

    margin_left = 70
    margin_right = 20
    margin_top = 30
    margin_bottom = 60
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    def x_map(value: float) -> float:
        return margin_left + (float(value) - x_min) / (x_max - x_min) * plot_width

    def y_map(value: float) -> float:
        return margin_top + plot_height - (float(value) - y_min) / (y_max - y_min) * plot_height

    min_value = float(np.min(values))
    max_value = float(np.max(values))
    if np.isclose(min_value, max_value):
        max_value = min_value + 1.0

    def color(value: float) -> str:
        fraction = (float(value) - min_value) / (max_value - min_value)
        fraction = min(max(fraction, 0.0), 1.0)
        red = int(33 + fraction * 180)
        green = int(102 + (1.0 - fraction) * 120)
        blue = int(172 - fraction * 120)
        return f"rgb({red},{green},{blue})"

    rows, cols = values.shape
    cell_width = plot_width / max(cols, 1)
    cell_height = plot_height / max(rows, 1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin_left}" y="18" font-size="14" font-weight="bold">{_escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#333" />',
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#333" />',
        f'<text x="{margin_left + plot_width / 2}" y="{height - 10}" text-anchor="middle" font-size="12">{_escape(x_label)}</text>',
        f'<text x="18" y="{margin_top + plot_height / 2}" transform="rotate(-90 18,{margin_top + plot_height / 2})" text-anchor="middle" font-size="12">{_escape(y_label)}</text>',
    ]

    for row_index in range(rows):
        for col_index in range(cols):
            x_pos = margin_left + col_index * cell_width
            y_pos = margin_top + row_index * cell_height
            parts.append(
                f'<rect x="{x_pos:.2f}" y="{y_pos:.2f}" width="{cell_width + 0.5:.2f}" height="{cell_height + 0.5:.2f}" fill="{color(values[row_index, col_index])}" />'
            )

    for value in x:
        x_pos = x_map(value)
        parts.append(
            f'<text x="{x_pos:.2f}" y="{margin_top + plot_height + 18}" text-anchor="middle" font-size="10">{value:.3g}</text>'
        )

    for value in y:
        y_pos = y_map(value)
        parts.append(
            f'<text x="{margin_left - 8}" y="{y_pos + 3:.2f}" text-anchor="end" font-size="10">{value:.3g}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_model_html(model) -> str:
    name = getattr(model, "name", None) or "(unnamed)"
    source_path = getattr(model, "source_path", None)
    sections = []

    parameter_rows = []
    for parameter in getattr(model, "parameters", []):
        value = getattr(parameter, "value", None)
        expression = getattr(parameter, "expression", None)
        parameter_rows.append((parameter.name, value, expression))
    sections.append(_details("Parameters", ["Name", "Value", "Expression"], parameter_rows))

    molecule_rows = []
    for molecule in getattr(model, "molecule_types", []):
        components = ", ".join(
            f"{component.name}[{','.join(component.allowed_states)}]" if getattr(component, "allowed_states", []) else component.name
            for component in getattr(molecule, "components", [])
        )
        molecule_rows.append((molecule.name, components, getattr(molecule, "is_population", False)))
    sections.append(_details("Molecule Types", ["Name", "Components", "Population"], molecule_rows))

    seed_rows = []
    for seed in getattr(model, "seed_species", []):
        amount = getattr(seed, "amount", None)
        seed_rows.append((seed.pattern, amount, getattr(seed, "is_constant", False), getattr(seed, "compartment", "")))
    sections.append(_details("Seed Species", ["Pattern", "Amount", "Constant", "Compartment"], seed_rows))

    rule_rows = []
    for rule in getattr(model, "reaction_rules", []):
        reactants = " + ".join(getattr(rule, "reactant_patterns", []))
        products = " + ".join(getattr(rule, "product_patterns", []))
        rates = ", ".join(getattr(rule, "rates", []))
        modifiers = ", ".join(getattr(rule, "modifiers", []))
        rule_rows.append((getattr(rule, "label", ""), reactants, products, rates, modifiers))
    sections.append(_details("Reaction Rules", ["Label", "Reactants", "Products", "Rates", "Modifiers"], rule_rows))

    observable_rows = []
    for observable in getattr(model, "observables", []):
        observable_rows.append((observable.name, getattr(observable, "type", ""), ", ".join(getattr(observable, "patterns", []))))
    sections.append(_details("Observables", ["Name", "Type", "Patterns"], observable_rows))

    function_rows = []
    for function in getattr(model, "functions", []):
        function_rows.append((function.name, ", ".join(getattr(function, "args", [])), getattr(function, "expression", "")))
    sections.append(_details("Functions", ["Name", "Arguments", "Expression"], function_rows))

    compartment_rows = []
    for compartment in getattr(model, "compartments", []):
        compartment_rows.append((compartment.name, getattr(compartment, "dimension", "")))
    sections.append(_details("Compartments", ["Name", "Dimension"], compartment_rows))

    action_rows = []
    for action in getattr(model, "actions", []):
        action_rows.append((getattr(action, "name", ""), getattr(action, "arguments", {})))
    sections.append(_details("Actions", ["Name", "Arguments"], action_rows))

    meta = []
    if source_path:
        meta.append(f"<p><strong>Source:</strong> {_escape(source_path)}</p>")
    meta.append(
        f"<p><strong>Counts:</strong> parameters={len(getattr(model, 'parameters', []))}, "
        f"molecule_types={len(getattr(model, 'molecule_types', []))}, "
        f"species={len(getattr(model, 'seed_species', []))}, "
        f"rules={len(getattr(model, 'reaction_rules', []))}, "
        f"observables={len(getattr(model, 'observables', []))}</p>"
    )
    return (
        "<div class='bng-model'>"
        f"<h2>{_escape(name)}</h2>"
        + "".join(meta)
        + "".join(sections)
        + "</div>"
    )


def render_sim_result_html(result) -> str:
    observable_names = list(getattr(result, "observable_names", []))
    if not observable_names:
        return "<div class='bng-result'><p>No observable data available.</p></div>"

    series = [np.asarray(result.observables[name], dtype=float) for name in observable_names]
    svg = _line_chart_svg(
        getattr(result, "time", np.array([])),
        series,
        observable_names,
        title="Simulation Result",
        x_label="Time",
        y_label="Observable value",
    )
    return (
        "<div class='bng-result'>"
        f"<p>Observables: {_escape(', '.join(observable_names))}</p>"
        f"{_embed_svg(svg, 'Simulation result plot')}"
        "</div>"
    )


def render_scan_result_html(result) -> str:
    observable_names = list(getattr(result, "observable_names", []))
    if not observable_names:
        return "<div class='bng-scan'><p>No scan data available.</p></div>"

    series = [result.final(name) for name in observable_names]
    svg = _line_chart_svg(
        getattr(result, "parameter_values", np.array([])),
        series,
        observable_names,
        title="Parameter Scan",
        x_label=getattr(result, "parameter_name", "parameter"),
        y_label="Final observable value",
    )
    return (
        "<div class='bng-scan'>"
        f"<p>Parameter: {_escape(getattr(result, 'parameter_name', 'parameter'))}</p>"
        f"<p>Observables: {_escape(', '.join(observable_names))}</p>"
        f"{_embed_svg(svg, 'Parameter scan plot')}"
        "</div>"
    )


def render_scan_grid_html(result, observable: Optional[str] = None) -> str:
    observable_names = list(getattr(result, "observable_names", []))
    if not observable_names:
        return "<div class='bng-scan'><p>No scan data available.</p></div>"

    observable = observable or observable_names[0]
    matrix = result.final(observable)
    svg = _heatmap_svg(
        matrix,
        getattr(result, "values2", np.array([])),
        getattr(result, "values1", np.array([])),
        title=f"Parameter Scan: {observable}",
        x_label=getattr(result, "parameter2_name", "parameter2"),
        y_label=getattr(result, "parameter1_name", "parameter1"),
    )
    return _embed_svg(svg, f"Parameter scan heatmap for {observable}")