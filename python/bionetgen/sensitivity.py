"""Local sensitivity analysis for BioNetGen models."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from bionetgen.model import BioNetGenModel
from bionetgen.result import SimResult
from bionetgen.scan import (
    _coerce_model,
    _simulation_kwargs,
    _simulate_serial,
    _worker_scan_single,
)


def _default_parameter_names(model: BioNetGenModel) -> list[str]:
    return [parameter.name for parameter in model.parameters]


def _default_observable_names(model: BioNetGenModel) -> list[str]:
    return [observable.name for observable in model.observables]


def _final_values(result: SimResult, observable_names: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [result.observables[name][-1] for name in observable_names], dtype=float
    )


@dataclass
class SensitivityResult:
    parameter_names: list[str]
    observable_names: list[str]
    matrix: np.ndarray
    baseline: SimResult

    def rank(self, observable: str) -> list[tuple[str, float]]:
        if observable not in self.observable_names:
            raise KeyError(observable)
        column = self.observable_names.index(observable)
        values = self.matrix[:, column]
        pairs = list(zip(self.parameter_names, values.tolist()))
        return sorted(pairs, key=lambda item: abs(item[1]), reverse=True)

    def to_dataframe(self):
        import pandas as pd

        frame = pd.DataFrame(
            self.matrix, index=self.parameter_names, columns=self.observable_names
        )
        frame.index.name = "parameter"
        return frame.reset_index()

    def plot(self, show: bool = True, **kwargs):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        image = ax.imshow(self.matrix, aspect="auto", origin="lower", **kwargs)
        ax.set_xticks(range(len(self.observable_names)))
        ax.set_xticklabels(self.observable_names, rotation=45, ha="right")
        ax.set_yticks(range(len(self.parameter_names)))
        ax.set_yticklabels(self.parameter_names)
        ax.set_xlabel("Observable")
        ax.set_ylabel("Parameter")
        ax.set_title("Sensitivity matrix")
        fig.colorbar(image, ax=ax)
        fig.tight_layout()
        if show:
            plt.show()
        return fig, ax


def _worker_sensitivity_single(payload):
    source_path, updates, sim_kwargs = payload
    return _worker_scan_single((source_path, updates, sim_kwargs))


def sensitivity_analysis(
    model_or_path,
    parameters: Optional[Sequence[str]] = None,
    observables: Optional[Sequence[str]] = None,
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
    delta: float = 0.01,
    parallel: int = 0,
) -> SensitivityResult:
    model = _coerce_model(model_or_path)
    parameter_names = list(parameters or _default_parameter_names(model))
    observable_names = list(observables or _default_observable_names(model))
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
            raise ValueError(
                "parallel sensitivity analysis requires a model loaded from a BNGL file"
            )
    else:
        source_path = None

    baseline = model.simulate(**sim_kwargs)
    baseline_values = _final_values(baseline, observable_names)
    matrix = np.zeros((len(parameter_names), len(observable_names)), dtype=float)

    if parallel and parallel > 1:
        payloads = []
        for parameter_name in parameter_names:
            nominal = model.get_parameter(parameter_name).value
            if nominal is None:
                raise ValueError(
                    f"Parameter {parameter_name!r} does not have a numeric value"
                )
            plus_value = float(nominal) * (1.0 + delta)
            minus_value = float(nominal) * (1.0 - delta)
            payloads.append((source_path, {parameter_name: plus_value}, sim_kwargs))
            payloads.append((source_path, {parameter_name: minus_value}, sim_kwargs))

        with ProcessPoolExecutor(max_workers=parallel) as executor:
            perturbed_results = list(executor.map(_worker_sensitivity_single, payloads))

        for parameter_index, parameter_name in enumerate(parameter_names):
            nominal = model.get_parameter(parameter_name).value
            if nominal is None:
                raise ValueError(
                    f"Parameter {parameter_name!r} does not have a numeric value"
                )
            plus_result = perturbed_results[2 * parameter_index]
            minus_result = perturbed_results[2 * parameter_index + 1]
            plus_values = _final_values(plus_result, observable_names)
            minus_values = _final_values(minus_result, observable_names)
            for observable_index, nominal_value in enumerate(baseline_values):
                if nominal_value == 0.0 or nominal == 0.0:
                    matrix[parameter_index, observable_index] = np.nan
                else:
                    matrix[parameter_index, observable_index] = (
                        (plus_values[observable_index] - minus_values[observable_index])
                        / (2.0 * delta * float(nominal))
                        * (float(nominal) / float(nominal_value))
                    )
        return SensitivityResult(parameter_names, observable_names, matrix, baseline)

    for parameter_index, parameter_name in enumerate(parameter_names):
        nominal = model.get_parameter(parameter_name).value
        if nominal is None:
            raise ValueError(
                f"Parameter {parameter_name!r} does not have a numeric value"
            )
        plus_result = _simulate_serial(
            model, {parameter_name: float(nominal) * (1.0 + delta)}, sim_kwargs
        )
        minus_result = _simulate_serial(
            model, {parameter_name: float(nominal) * (1.0 - delta)}, sim_kwargs
        )
        plus_values = _final_values(plus_result, observable_names)
        minus_values = _final_values(minus_result, observable_names)
        for observable_index, nominal_value in enumerate(baseline_values):
            if nominal_value == 0.0 or nominal == 0.0:
                matrix[parameter_index, observable_index] = np.nan
            else:
                matrix[parameter_index, observable_index] = (
                    (plus_values[observable_index] - minus_values[observable_index])
                    / (2.0 * delta * float(nominal))
                    * (float(nominal) / float(nominal_value))
                )

    return SensitivityResult(parameter_names, observable_names, matrix, baseline)


__all__ = ["SensitivityResult", "sensitivity_analysis"]
