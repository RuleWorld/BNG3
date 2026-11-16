"""Compatibility shim for PyBioNetGen's bngsim_bridge API.

BNG3 exposes BNGsim-backed simulation through native APIs; this module
preserves the historical import surface used by PyBioNetGen code.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from bionetgen.core.exc import BNGFormatError, BNGSimError

logger = logging.getLogger("bionetgen.bngsim_bridge")

MINIMUM_BNGSIM_VERSION = "0.9.10"
BNGSIM_UNAVAILABLE_REASON = "BNG3 does not ship the PyBioNetGen bngsim bridge runtime"
_VERSION_FALLBACK_WARNED = False

bngsim = None
BNGSIM_AVAILABLE = False
BNGSIM_VERSION = None
BNGSIM_HAS_NFSIM = False
BNGSIM_HAS_RULEMONKEY = False

FORMAT_BNGL = "bngl"
FORMAT_NET = "net"
FORMAT_SBML = "sbml"
FORMAT_BNG_XML = "bng-xml"
FORMAT_ANTIMONY = "antimony"
VALID_FORMATS = {FORMAT_BNGL, FORMAT_NET, FORMAT_SBML, FORMAT_BNG_XML, FORMAT_ANTIMONY}
BNGSIM_REQUIRED_FORMATS = {FORMAT_SBML, FORMAT_ANTIMONY}
FALLBACK_FORMATS = {FORMAT_BNGL, FORMAT_NET, FORMAT_BNG_XML}

ROUTE_DIRECT_BNGSIM = "direct-bngsim"
ROUTE_BNGL_BNGSIM = "bngl-bngsim"
ROUTE_SUBPROCESS = "subprocess"
ROUTE_ERROR = "error"


@dataclass(frozen=True)
class BngsimRouteDecision:
    route: str
    reason: str
    method: str | None = None


@dataclass(frozen=True)
class BngsimDirectJob:
    input_path: str
    input_format: str
    method: str
    t_span: tuple[float, float]
    n_points: int
    output_dir: str
    output_root: str
    bngsim_options: dict | None = None
    result_options: dict | None = None
    get_final_state: bool = False


def is_bngsim_available() -> bool:
    return False


def get_bngsim_unavailable_reason() -> str | None:
    return BNGSIM_UNAVAILABLE_REASON


def _warn_version_fallback_once() -> None:
    global _VERSION_FALLBACK_WARNED
    _VERSION_FALLBACK_WARNED = True


def _sniff_xml_format(file_path):
    try:
        with open(file_path, "r", errors="replace") as f:
            head = f.read(4096)
    except OSError as e:
        raise BNGFormatError(file_path, f"Could not read file for format detection: {e}") from e
    head_lower = head.lower()
    is_sbml = "<sbml" in head_lower or "www.sbml.org" in head_lower
    is_bng = (
        "<listofmoleculetypes" in head_lower
        or "<listofspeciestypes" in head_lower
        or "<listofobservables" in head_lower
        or "<listofreactionrules" in head_lower
    )
    if is_sbml and not is_bng:
        return FORMAT_SBML
    if is_bng and not is_sbml:
        return FORMAT_BNG_XML
    if is_bng and is_sbml:
        return FORMAT_BNG_XML
    return None


def detect_input_format(file_path, explicit_format=None):
    if explicit_format is not None:
        explicit_format = explicit_format.lower().strip()
        if explicit_format not in VALID_FORMATS:
            raise BNGFormatError(
                file_path,
                f"Unknown format '{explicit_format}'. Valid formats: {', '.join(sorted(VALID_FORMATS))}",
            )
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    if ext == ".bngl":
        detected = FORMAT_BNGL
    elif ext == ".net":
        detected = FORMAT_NET
    elif ext == ".ant":
        detected = FORMAT_ANTIMONY
    elif ext == ".xml":
        detected = _sniff_xml_format(file_path)
    else:
        detected = None
    if explicit_format is not None:
        if detected is not None and explicit_format != detected:
            raise BNGFormatError(
                file_path,
                f"Format conflict: you specified --format={explicit_format} but auto-detection suggests '{detected}'.",
            )
        return explicit_format
    if detected is None:
        if ext == ".xml":
            raise BNGFormatError(file_path, "Could not determine whether this XML file is SBML or BioNetGen XML.")
        raise BNGFormatError(file_path, f"Unrecognized file extension '{ext}'.")
    return detected


def classify_bngsim_route(inp, fmt, simulator="auto", method=None, **kwargs):
    if simulator == "subprocess":
        return BngsimRouteDecision(ROUTE_SUBPROCESS, "subprocess requested", method)
    if fmt in BNGSIM_REQUIRED_FORMATS:
        return BngsimRouteDecision(ROUTE_ERROR, BNGSIM_UNAVAILABLE_REASON, method)
    if fmt == FORMAT_BNGL:
        return BngsimRouteDecision(ROUTE_BNGL_BNGSIM, BNGSIM_UNAVAILABLE_REASON, method)
    return BngsimRouteDecision(ROUTE_DIRECT_BNGSIM, BNGSIM_UNAVAILABLE_REASON, method)


def execute_bngsim_direct_job(*args, **kwargs):
    raise BNGSimError(BNGSIM_UNAVAILABLE_REASON)


def run_nfsim(*args, **kwargs):
    raise BNGSimError(BNGSIM_UNAVAILABLE_REASON)


def run_with_bngsim(*args, **kwargs):
    raise BNGSimError(BNGSIM_UNAVAILABLE_REASON)


def run_bngl_with_bngsim_backend_hook(*args, **kwargs):
    raise BNGSimError(BNGSIM_UNAVAILABLE_REASON)


def run_bngl_with_bngsim(*args, **kwargs):
    raise BNGSimError(BNGSIM_UNAVAILABLE_REASON)
