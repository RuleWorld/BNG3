"""Python wrappers for the C++ visualization writers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

try:
    from bionetgen import _bionetgen_cpp as _cpp
except ImportError:
    try:
        import _bionetgen_cpp as _cpp
    except ImportError:
        _cpp = None


def _unwrap_model(model):
    return getattr(model, "_model", model)


def _viz_module():
    if _cpp is None or not hasattr(_cpp, "viz"):
        raise ImportError("The compiled _bionetgen_cpp.viz bindings are not available")
    return _cpp.viz


def _write(name: str, model, path: Optional[Union[str, Path]] = None):
    writer = getattr(_viz_module(), name)
    cpp_model = _unwrap_model(model)
    if path is None:
        return writer(cpp_model)
    return writer(cpp_model, str(path))


def write_contact_map(model, path: Optional[Union[str, Path]] = None):
    return _write("write_contact_map", model, path)


def write_regulatory_graph(model, path: Optional[Union[str, Path]] = None):
    return _write("write_regulatory_graph", model, path)


def write_rule_influence_graph(model, path: Optional[Union[str, Path]] = None):
    return _write("write_rule_influence_graph", model, path)


def write_reaction_network_graph(model, path: Optional[Union[str, Path]] = None):
    return _write("write_reaction_network_graph", model, path)


def write_ruleviz_pattern(model, path: Optional[Union[str, Path]] = None):
    return _write("write_ruleviz_pattern", model, path)


def write_ruleviz_operation(model, path: Optional[Union[str, Path]] = None):
    return _write("write_ruleviz_operation", model, path)


def write_process_graph(model, path: Optional[Union[str, Path]] = None):
    return _write("write_process_graph", model, path)


def write_sbml_multi(model, path: Optional[Union[str, Path]] = None):
    return _write("write_sbml_multi", model, path)


__all__ = [
    "write_contact_map",
    "write_regulatory_graph",
    "write_rule_influence_graph",
    "write_reaction_network_graph",
    "write_ruleviz_pattern",
    "write_ruleviz_operation",
    "write_process_graph",
    "write_sbml_multi",
]