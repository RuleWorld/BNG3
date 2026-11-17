"""Compatibility shim for PyBioNetGen's bngsim_backend_helper API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from bionetgen.core.exc import BNGSimError
from bionetgen.core.tools.bngsim_bridge import (
    BngsimDirectJob,
    FORMAT_BNG_XML,
    FORMAT_NET,
    execute_bngsim_direct_job,
)

NETWORK_METHOD_ALIASES = {
    "cvode": "ode",
    "ode": "ode",
    "ssa": "ssa",
    "psa": "psa",
    "rm": "rm",
}
NF_METHOD_ALIASES = {"nf": "nf", "nfsim": "nf", "nf_reject": "nf"}
NETWORK_FREE_METHODS = frozenset({"nf", "rm"})
ARTIFACT_FORMAT_ALIASES = {
    "net": FORMAT_NET,
    ".net": FORMAT_NET,
    "bng-xml": FORMAT_BNG_XML,
    "bng_xml": FORMAT_BNG_XML,
    "xml": FORMAT_BNG_XML,
    ".xml": FORMAT_BNG_XML,
}


@dataclass(frozen=True)
class BackendHelperJob:
    artifact_path: str
    artifact_format: str
    method: str
    simulation_options: dict[str, Any]
    output_dir: str
    output_root: str
    backend_flags: dict[str, Any]


def _as_number(value: Any, default: float | None = None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int | None = None):
    number = _as_number(value)
    if number is None:
        return default
    return int(number)


def _parse_nf_param_flags(param: Any) -> dict[str, Any]:
    if not isinstance(param, str):
        return {}
    toks = param.strip().strip('"').strip("'").split()
    out: dict[str, Any] = {}
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok in ("-ogf", "--ogf"):
            out["print_functions"] = 1
        elif tok in ("-gml", "--gml", "-globalMoleculeLimit"):
            if i + 1 < len(toks):
                gml = _as_int(toks[i + 1])
                if gml is not None:
                    out["gml"] = gml
                i += 1
        i += 1
    return out


def _normalize_method(method: Any) -> str:
    method_name = str(method or "").strip().lower()
    if method_name in NETWORK_METHOD_ALIASES:
        return NETWORK_METHOD_ALIASES[method_name]
    if method_name in NF_METHOD_ALIASES:
        return NF_METHOD_ALIASES[method_name]
    raise BNGSimError(f"Unsupported BNGsim backend method: {method!r}")


def _normalize_artifact_format(raw_format: Any, artifact_path: str) -> str:
    if raw_format is not None:
        fmt = ARTIFACT_FORMAT_ALIASES.get(str(raw_format).strip().lower())
        if fmt is None:
            raise BNGSimError(
                f"Unsupported BNGsim backend artifact format: {raw_format!r}"
            )
        return fmt
    ext = os.path.splitext(artifact_path)[1].lower()
    fmt = ARTIFACT_FORMAT_ALIASES.get(ext)
    if fmt is None:
        raise BNGSimError(
            f"Could not infer BNGsim backend artifact format from {artifact_path!r}"
        )
    return fmt


def _output_dir_and_root(payload: dict[str, Any]) -> tuple[str, str]:
    output_prefix = payload.get("output_prefix") or payload.get("output_path_root")
    if output_prefix:
        output_prefix = os.path.abspath(str(output_prefix))
        output_dir = os.path.dirname(output_prefix) or os.getcwd()
        output_root = os.path.basename(output_prefix)
        return output_dir, output_root
    output_dir = os.path.abspath(str(payload.get("output_dir") or os.getcwd()))
    output_root = payload.get("output_root")
    if not output_root:
        artifact_path = str(
            payload.get("artifact_path") or payload.get("input_path") or ""
        )
        output_root = os.path.splitext(os.path.basename(artifact_path))[0]
    return output_dir, str(output_root)


def load_backend_job(payload: dict[str, Any]) -> BackendHelperJob:
    artifact_path = payload.get("artifact_path") or payload.get("input_path")
    if not artifact_path:
        raise BNGSimError("BNGsim backend job is missing artifact_path")
    artifact_path = os.path.abspath(str(artifact_path))
    method = _normalize_method(payload.get("method"))
    method_override = (
        os.environ.get("BIONETGEN_BNGSIM_BACKEND_METHOD", "").strip().lower()
    )
    if method_override == "rm" and method == "nf":
        method = "rm"
    artifact_format = _normalize_artifact_format(
        payload.get("artifact_format") or payload.get("input_format"), artifact_path
    )
    output_dir, output_root = _output_dir_and_root(payload)
    sim_options = dict(
        payload.get("simulation_options") or payload.get("options") or {}
    )
    backend_flags = dict(payload.get("backend_flags") or {})
    return BackendHelperJob(
        artifact_path=artifact_path,
        artifact_format=artifact_format,
        method=method,
        simulation_options=sim_options,
        output_dir=output_dir,
        output_root=output_root,
        backend_flags=backend_flags,
    )


def direct_job_from_backend_job(job: BackendHelperJob) -> BngsimDirectJob:
    opts = dict(job.simulation_options)
    t_start = _as_number(opts.pop("t_start", None), 0.0)
    t_end = _as_number(opts.pop("t_end", None), 100.0)
    if job.method in NETWORK_FREE_METHODS and t_start != 0.0:
        t_end = t_end - t_start
        t_start = 0.0
    sample_times = opts.pop("sample_times", None)
    n_points = _as_int(opts.pop("n_points", None))
    n_steps = _as_int(opts.pop("n_steps", opts.pop("n_output_steps", None)))
    if sample_times:
        sample_times = [float(t_start)] + [float(t) for t in sample_times]
        opts["sample_times"] = sample_times
        n_points = len(sample_times)
    elif n_points is None:
        n_points = (n_steps if n_steps is not None else 100) + 1
    return BngsimDirectJob(
        input_path=job.artifact_path,
        input_format=job.artifact_format,
        method=job.method,
        t_span=(float(t_start), float(t_end)),
        n_points=int(n_points),
        output_dir=job.output_dir,
        output_root=job.output_root,
        bngsim_options=opts,
    )


def execute_backend_payload(payload: dict[str, Any]):
    job = load_backend_job(payload)
    return execute_bngsim_direct_job(direct_job_from_backend_job(job))


def serve(*args, **kwargs):
    raise BNGSimError(
        "BNG3 does not provide the PyBioNetGen bngsim backend helper server"
    )


def main(argv=None):
    raise BNGSimError("BNG3 does not provide the PyBioNetGen bngsim backend helper CLI")
