"""Parameter scan helpers for BioNetGen models."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np

from bionetgen.model import BioNetGenModel, load
from bionetgen.result import SimResult


def _coerce_model(model_or_path) -> BioNetGenModel:
    if isinstance(model_or_path, BioNetGenModel):
        return model_or_path
    if isinstance(model_or_path, (str, Path)):
        return load(model_or_path)
    raise TypeError("Expected a BioNetGenModel or a BNGL file path")


def _scan_values(*, values=None, min=None, max=None, n_points=None, log_scale=False):
    if values is not None:
        resolved = np.asarray(values, dtype=float)
        if resolved.ndim != 1:
            raise ValueError("Scan values must be one-dimensional")
        return resolved

    if min is None or max is None or n_points is None:
        raise ValueError("Provide either values or min/max/n_points")

    if log_scale:
        return np.logspace(np.log10(float(min)), np.log10(float(max)), int(n_points))
    return np.linspace(float(min), float(max), int(n_points))


def _simulation_kwargs(
    *,
    method: str,
    t_end: float,
    n_steps: int,
    t_start: float,
    rtol: float,
    atol: float,
    seed: int,
    pla_config: str,
    psa_poplevel: float,
    verbose: bool,
) -> dict[str, Any]:
    return {
        "method": method,
        "t_end": t_end,
        "n_steps": n_steps,
        "t_start": t_start,
        "rtol": rtol,
        "atol": atol,
        "seed": seed,
        "pla_config": pla_config,
        "psa_poplevel": psa_poplevel,
        "verbose": verbose,
    }


def _worker_scan_single(payload):
    source_path, updates, sim_kwargs = payload
    model = load(source_path)
    for name, value in updates.items():
        model.set_parameter(name, float(value))
    model._network = None
    return model.simulate(**sim_kwargs)


def _simulate_serial(model: BioNetGenModel, updates: Mapping[str, float], sim_kwargs: dict[str, Any]) -> SimResult:
    original_network = getattr(model, "_network", None)
    original_values = {}
    for name in updates:
        original_values[name] = model.get_parameter(name).value
    try:
        for name, value in updates.items():
            model.set_parameter(name, float(value))
        model._network = None
        return model.simulate(**sim_kwargs)
    finally:
        for name, original_value in original_values.items():
            if original_value is not None:
                model.set_parameter(name, float(original_value))
        model._network = original_network


@dataclass
class ScanResult:
    parameter_name: str
    parameter_values: np.ndarray
    results: list[SimResult]
    simulation_kwargs: dict[str, Any]
    source_path: Optional[str] = None

    @property
    def time(self) -> np.ndarray:
        return self.results[0].time if self.results else np.array([])

    @property
    def observable_names(self) -> list[str]:
        return self.results[0].observable_names if self.results else []

    def final(self, observable: str) -> np.ndarray:
        return np.asarray([result.observables[observable][-1] for result in self.results], dtype=float)

    def at_time(self, t: float, observable: str) -> np.ndarray:
        return np.asarray(
            [np.interp(float(t), result.time, result.observables[observable]) for result in self.results],
            dtype=float,
        )

    def to_dataframe(self):
        import pandas as pd

        rows = []
        for value, result in zip(self.parameter_values, self.results):
            for time_index, time_value in enumerate(result.time):
                row = {self.parameter_name: float(value), "time": float(time_value)}
                for observable in self.observable_names:
                    row[observable] = float(np.asarray(result.observables[observable])[time_index])
                rows.append(row)
        return pd.DataFrame(rows)

    def plot(self, observable: str, show: bool = True, **kwargs):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot(self.parameter_values, self.final(observable), marker="o", **kwargs)
        ax.set_xlabel(self.parameter_name)
        ax.set_ylabel(observable)
        ax.set_title(f"Parameter scan: {observable}")
        if show:
            plt.show()
        return fig, ax

    def _repr_html_(self) -> str:
        from bionetgen.display import render_scan_result_html

        return render_scan_result_html(self)


@dataclass
class ScanResult2D:
    parameter1_name: str
    values1: np.ndarray
    parameter2_name: str
    values2: np.ndarray
    results: list[list[SimResult]]
    simulation_kwargs: dict[str, Any]
    source_path: Optional[str] = None

    @property
    def observable_names(self) -> list[str]:
        return self.results[0][0].observable_names if self.results and self.results[0] else []

    @property
    def time(self) -> np.ndarray:
        return self.results[0][0].time if self.results and self.results[0] else np.array([])

    def final(self, observable: str) -> np.ndarray:
        return np.asarray(
            [[result.observables[observable][-1] for result in row] for row in self.results],
            dtype=float,
        )

    def at_time(self, t: float, observable: str) -> np.ndarray:
        return np.asarray(
            [
                [np.interp(float(t), result.time, result.observables[observable]) for result in row]
                for row in self.results
            ],
            dtype=float,
        )

    def to_dataframe(self):
        import pandas as pd

        rows = []
        for value1, row in zip(self.values1, self.results):
            for value2, result in zip(self.values2, row):
                for time_index, time_value in enumerate(result.time):
                    record = {
                        self.parameter1_name: float(value1),
                        self.parameter2_name: float(value2),
                        "time": float(time_value),
                    }
                    for observable in self.observable_names:
                        record[observable] = float(np.asarray(result.observables[observable])[time_index])
                    rows.append(record)
        return pd.DataFrame(rows)

    def plot_heatmap(self, observable: str, show: bool = True, **kwargs):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        heatmap = self.final(observable)
        image = ax.imshow(
            heatmap,
            origin="lower",
            aspect="auto",
            **kwargs,
        )
        ax.set_xlabel(self.parameter2_name)
        ax.set_ylabel(self.parameter1_name)
        ax.set_title(f"Parameter scan: {observable}")
        fig.colorbar(image, ax=ax)
        ax.set_xticks(range(len(self.values2)))
        ax.set_xticklabels([f"{value:.3g}" for value in self.values2], rotation=45, ha="right")
        ax.set_yticks(range(len(self.values1)))
        ax.set_yticklabels([f"{value:.3g}" for value in self.values1])
        fig.tight_layout()
        if show:
            plt.show()
        return fig, ax

    def _repr_html_(self) -> str:
        from bionetgen.display import render_scan_grid_html

        return render_scan_grid_html(self)


def parameter_scan(
    model_or_path,
    parameter: str,
    *,
    values=None,
    min=None,
    max=None,
    n_points: Optional[int] = None,
    log_scale: bool = False,
    method: str = "ode",
    t_end: float = 100.0,
    n_steps: int = 100,
    t_start: float = 0.0,
    rtol: float = 1e-8,
    atol: float = 1e-8,
    seed: int = 0,
    pla_config: str = "",
    psa_poplevel: float = 100.0,
    verbose: bool = False,
    parallel: int = 0,
) -> ScanResult:
    model = _coerce_model(model_or_path)
    scan_values = _scan_values(values=values, min=min, max=max, n_points=n_points, log_scale=log_scale)
    sim_kwargs = _simulation_kwargs(
        method=method,
        t_end=t_end,
        n_steps=n_steps,
        t_start=t_start,
        rtol=rtol,
        atol=atol,
        seed=seed,
        pla_config=pla_config,
        psa_poplevel=psa_poplevel,
        verbose=verbose,
    )

    if parallel and parallel > 1:
        source_path = model.source_path
        if not source_path:
            raise ValueError("parallel scans require a model loaded from a BNGL file")
        payloads = [
            (source_path, {parameter: float(value)}, sim_kwargs)
            for value in scan_values
        ]
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            results = list(executor.map(_worker_scan_single, payloads))
    else:
        results = [
            _simulate_serial(model, {parameter: float(value)}, sim_kwargs)
            for value in scan_values
        ]

    return ScanResult(
        parameter_name=parameter,
        parameter_values=np.asarray(scan_values, dtype=float),
        results=results,
        simulation_kwargs=sim_kwargs,
        source_path=model.source_path,
    )


def parameter_scan_2d(
    model_or_path,
    parameter1: str,
    values1,
    parameter2: str,
    values2,
    *,
    method: str = "ode",
    t_end: float = 100.0,
    n_steps: int = 100,
    t_start: float = 0.0,
    rtol: float = 1e-8,
    atol: float = 1e-8,
    seed: int = 0,
    pla_config: str = "",
    psa_poplevel: float = 100.0,
    verbose: bool = False,
    parallel: int = 0,
) -> ScanResult2D:
    model = _coerce_model(model_or_path)
    values1 = np.asarray(values1, dtype=float)
    values2 = np.asarray(values2, dtype=float)
    if values1.ndim != 1 or values2.ndim != 1:
        raise ValueError("Scan grids must be one-dimensional")

    sim_kwargs = _simulation_kwargs(
        method=method,
        t_end=t_end,
        n_steps=n_steps,
        t_start=t_start,
        rtol=rtol,
        atol=atol,
        seed=seed,
        pla_config=pla_config,
        psa_poplevel=psa_poplevel,
        verbose=verbose,
    )

    if parallel and parallel > 1:
        source_path = model.source_path
        if not source_path:
            raise ValueError("parallel scans require a model loaded from a BNGL file")
        payloads = [
            (source_path, {parameter1: float(value1), parameter2: float(value2)}, sim_kwargs)
            for value1 in values1
            for value2 in values2
        ]
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            flat_results = list(executor.map(_worker_scan_single, payloads))
    else:
        flat_results = []
        for value1 in values1:
            row = []
            for value2 in values2:
                row.append(
                    _simulate_serial(
                        model,
                        {parameter1: float(value1), parameter2: float(value2)},
                        sim_kwargs,
                    )
                )
            flat_results.append(row)

    if parallel and parallel > 1:
        rows = []
        index = 0
        for _ in values1:
            row = []
            for _ in values2:
                row.append(flat_results[index])
                index += 1
            rows.append(row)
    else:
        rows = flat_results

    return ScanResult2D(
        parameter1_name=parameter1,
        values1=np.asarray(values1, dtype=float),
        parameter2_name=parameter2,
        values2=np.asarray(values2, dtype=float),
        results=rows,
        simulation_kwargs=sim_kwargs,
        source_path=model.source_path,
    )


__all__ = [
    "ScanResult",
    "ScanResult2D",
    "parameter_scan",
    "parameter_scan_2d",
]