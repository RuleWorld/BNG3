"""Programmatic BNGL model builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from bionetgen.model import BioNetGenModel

try:
    from bionetgen import _bionetgen_cpp as _cpp
except ImportError:
    try:
        import _bionetgen_cpp as _cpp
    except ImportError:
        _cpp = None


def _normalize_line(value: object) -> str:
    return str(value).strip()


def _format_block(title: str, lines: Sequence[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(f"    {line}" for line in lines)
    return f"begin {title}\n{body}\nend {title}\n"


@dataclass
class ModelBuilder:
    """Build a BNGL model from Python data structures."""

    name: str = "Untitled"
    parameters: list[str] = field(default_factory=list)
    molecule_types: list[str] = field(default_factory=list)
    seed_species: list[str] = field(default_factory=list)
    observables: list[str] = field(default_factory=list)
    reaction_rules: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    compartments: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def add_parameter(self, name: str, value: object) -> "ModelBuilder":
        self.parameters.append(f"{name} {_normalize_line(value)}")
        return self

    def add_molecule_type(self, pattern: str) -> "ModelBuilder":
        self.molecule_types.append(_normalize_line(pattern))
        return self

    def add_seed_species(
        self,
        pattern: str,
        amount: object,
        compartment: Optional[str] = None,
    ) -> "ModelBuilder":
        prefix = f"@{compartment}:" if compartment else ""
        self.seed_species.append(f"{prefix}{_normalize_line(pattern)} {_normalize_line(amount)}")
        return self

    def add_observable(self, observable_type: str, name: str, pattern: str) -> "ModelBuilder":
        self.observables.append(
            f"{_normalize_line(observable_type)} {_normalize_line(name)} {_normalize_line(pattern)}"
        )
        return self

    def add_rule(self, reaction: str, rate: object, label: Optional[str] = None) -> "ModelBuilder":
        prefix = f"{_normalize_line(label)}: " if label else ""
        self.reaction_rules.append(f"{prefix}{_normalize_line(reaction)} {_normalize_line(rate)}")
        return self

    def add_function(self, name: str, expression: object, args: Optional[Sequence[str]] = None) -> "ModelBuilder":
        argument_text = ",".join(args or [])
        self.functions.append(f"{_normalize_line(name)}({argument_text}) = {_normalize_line(expression)}")
        return self

    def add_compartment(self, line: str) -> "ModelBuilder":
        self.compartments.append(_normalize_line(line))
        return self

    def add_action(self, action: str) -> "ModelBuilder":
        self.actions.append(_normalize_line(action))
        return self

    def to_bngl(self) -> str:
        parts = ["begin model", ""]
        if self.parameters:
            parts.append(_format_block("parameters", self.parameters))
        if self.molecule_types:
            parts.append(_format_block("molecule types", self.molecule_types))
        if self.compartments:
            parts.append(_format_block("compartments", self.compartments))
        if self.seed_species:
            parts.append(_format_block("seed species", self.seed_species))
        if self.observables:
            parts.append(_format_block("observables", self.observables))
        if self.functions:
            parts.append(_format_block("functions", self.functions))
        if self.reaction_rules:
            parts.append(_format_block("reaction rules", self.reaction_rules))
        if self.actions:
            parts.append(_format_block("actions", self.actions))
        parts.append("end model")
        return "\n".join(part for part in parts if part != "") + "\n"

    def build(self) -> BioNetGenModel:
        if _cpp is None:
            raise ImportError("The compiled _bionetgen_cpp extension is required to build models")
        return BioNetGenModel(_cpp.parse_string(self.to_bngl()))


__all__ = ["ModelBuilder"]