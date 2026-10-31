"""High-level Python model interface wrapping the C++ BioNetGen engine."""

from __future__ import annotations

import math
import importlib
import operator
import os
from pathlib import Path
import re
import sys
from dataclasses import dataclass
from typing import Optional, Union

# Development builds: the native extension may live in build/cpp (the CMake
# binary directory for this checkout) rather than inside the installed
# package. When build/cpp/ contains the extension, re-point the
# scikit-build redirect finder to the build-tree .so so that stale
# site-packages copies are never used. This keeps the source checkout's
# compiled extension authoritative across all interpreter entry points
# (pytest, CLI, notebooks, subprocesses) without bypassing meta-path finders
# that callers (including tests) may have injected for error-propagation checks.
_build_cpp = Path(__file__).resolve().parents[2] / "build" / "cpp"
_build_cpp_so = next(iter(_build_cpp.glob("_bionetgen_cpp*.so")), None)
if _build_cpp_so is not None:
    for _finder in sys.meta_path:
        if type(_finder).__name__ == "ScikitBuildRedirectingFinder":
            for _key in list(getattr(_finder, "known_wheel_files", {})):
                if _key.endswith("._bionetgen_cpp"):
                    _finder.known_wheel_files[_key] = str(_build_cpp_so)
try:
    _cpp = importlib.import_module(f"{__package__}._bionetgen_cpp")
except ModuleNotFoundError as exc:
    if exc.name != f"{__package__}._bionetgen_cpp":
        raise
    try:
        _cpp = importlib.import_module("_bionetgen_cpp")
    except ModuleNotFoundError as exc:
        if exc.name != "_bionetgen_cpp":
            raise
        _cpp = None
    else:
        _module_name = f"{__package__}._bionetgen_cpp"
        sys.modules.setdefault(_module_name, _cpp)
        _package = sys.modules.get(__package__)
        if _package is not None:
            setattr(_package, "_bionetgen_cpp", _cpp)

from bionetgen.result import SimResult


@dataclass(frozen=True)
class CRNSpecies:
    """One species in a generated reaction network."""

    index: int
    name: str


@dataclass(frozen=True)
class CRNComplex:
    """One reaction complex (multiset of species) in a reaction network."""

    index: int
    species: tuple[int, ...]


@dataclass(frozen=True)
class CRNRateLaw:
    """Rate law and parameters for one generated reaction."""

    type: str
    expression: str
    factor: float = 1.0
    rule_name: str = ""
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class CRNReaction:
    """One generated reaction with participant species and complex indices."""

    index: int
    label: str
    reactants: tuple[int, ...]
    products: tuple[int, ...]
    reactant_complex: int = -1
    product_complex: int = -1
    rate_law: Optional[CRNRateLaw] = None


class BioNetGenModel:
    """A BNGL model backed by the C++ engine.

    Provides Pythonic access to model components (parameters, molecule types,
    reaction rules, observables, seed species) and simulation methods.
    """

    def __init__(
        self,
        cpp_model: _cpp.Model,
        source_path: Optional[str] = None,
        source_metadata: Optional[str] = None,
        algebraic_rules=None,
    ):
        self._model = cpp_model
        self._source_path = source_path
        self._source_metadata = source_metadata or ""
        self._algebraic_rules = list(algebraic_rules or [])
        self._network: Optional[_cpp.GeneratedNetwork] = None
        self._continuation_network: Optional[_cpp.GeneratedNetwork] = None
        self._network_from_continuation = False
        self._simulation_has_run = False
        # Parameter values set through set_parameter, in the order they were
        # set, so a topology edit can rebuild the model and keep them.
        self._parameter_overrides: dict = {}

    @property
    def parameters(self) -> list:
        return self._model.parameters

    @property
    def molecule_types(self) -> list:
        return self._model.molecule_types

    @property
    def seed_species(self) -> list:
        return self._model.seed_species

    def _get_crn_network(self):
        if self._network is None:
            self.generate_network()
        return self._network

    @property
    def species(self) -> tuple[CRNSpecies, ...]:
        """Generated network species in native network order."""
        network = self._get_crn_network()
        return tuple(
            CRNSpecies(index, name) for index, name in enumerate(network.species_names)
        )

    @property
    def complexes(self) -> tuple[CRNComplex, ...]:
        """Unique reaction complexes (multisets of species) in network order."""
        network = self._get_crn_network()
        complex_map: dict[tuple[int, ...], int] = {}
        complex_list: list[CRNComplex] = []
        for reactants, products in network.reaction_participants:
            for multiset in (tuple(sorted(reactants)), tuple(sorted(products))):
                if multiset not in complex_map:
                    idx = len(complex_list)
                    complex_map[multiset] = idx
                    complex_list.append(CRNComplex(idx, multiset))
        return tuple(complex_list)

    @property
    def reactions(self) -> tuple[CRNReaction, ...]:
        """Generated reactions in native network order."""
        network = self._get_crn_network()
        complexes = self.complexes
        complex_map = {c.species: c.index for c in complexes}

        rate_laws = getattr(network, "reaction_rate_laws", None)
        factors = getattr(network, "reaction_factors", None)
        rule_names = getattr(network, "reaction_rules", None)

        model_params = {p.name for p in self.parameters}

        result = []
        for index, (label, (reactants, products)) in enumerate(
            zip(network.reaction_strings, network.reaction_participants)
        ):
            r_c = complex_map[tuple(sorted(reactants))]
            p_c = complex_map[tuple(sorted(products))]
            expr = (
                rate_laws[index]
                if rate_laws is not None and index < len(rate_laws)
                else ""
            )
            factor = (
                factors[index] if factors is not None and index < len(factors) else 1.0
            )
            rname = (
                rule_names[index]
                if rule_names is not None and index < len(rule_names)
                else ""
            )

            words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
            referenced_params = tuple(sorted(words & model_params))
            rl_type = "mass_action"
            rate_law = CRNRateLaw(
                type=rl_type,
                expression=expr,
                factor=factor,
                rule_name=rname,
                parameters=referenced_params,
            )
            result.append(
                CRNReaction(
                    index=index,
                    label=label,
                    reactants=tuple(reactants),
                    products=tuple(products),
                    reactant_complex=r_c,
                    product_complex=p_c,
                    rate_law=rate_law,
                )
            )
        return tuple(result)

    @property
    def stoichiometric_matrix(self):
        """Dense integer N[species, reaction] matrix from the native network."""
        return self._get_crn_network().stoichiometric_matrix

    def to_crn(self) -> dict:
        """Export the chemical reaction network as a portable dictionary."""
        return {
            "version": "1.0",
            "name": self.name,
            "species": [{"index": s.index, "name": s.name} for s in self.species],
            "complexes": [
                {"index": c.index, "species": list(c.species)} for c in self.complexes
            ],
            "reactions": [
                {
                    "index": r.index,
                    "label": r.label,
                    "reactants": list(r.reactants),
                    "products": list(r.products),
                    "reactant_complex": r.reactant_complex,
                    "product_complex": r.product_complex,
                    "rate_law": (
                        {
                            "type": r.rate_law.type,
                            "expression": r.rate_law.expression,
                            "factor": r.rate_law.factor,
                            "rule_name": r.rate_law.rule_name,
                            "parameters": list(r.rate_law.parameters),
                        }
                        if r.rate_law is not None
                        else None
                    ),
                }
                for r in self.reactions
            ],
            "stoichiometric_matrix": self.stoichiometric_matrix.tolist(),
        }

    def write_crn(self, path: Union[str, Path]) -> None:
        """Write the generated CRN to a JSON file."""
        import json

        p = Path(path)
        p.write_text(json.dumps(self.to_crn(), indent=2), encoding="utf-8")

    @property
    def observables(self) -> list:
        return self._model.observables

    @property
    def reaction_rules(self) -> list:
        return self._model.reaction_rules

    @property
    def functions(self) -> list:
        return self._model.functions

    @property
    def compartments(self) -> list:
        return self._model.compartments

    @property
    def actions(self) -> list:
        return self._model.actions

    @property
    def name(self) -> str:
        return self._model.model_name

    def _require_export_supported(self, operation: str) -> None:
        if getattr(self, "_native_bngir_v02_only", False):
            raise NotImplementedError(
                f"{operation} is not supported for native BNGIR v0.2 imports; "
                "use to_bngir(version='0.2') to preserve the structural model"
            )

    @property
    def source_path(self) -> Optional[str]:
        return self._source_path

    def get_parameter(self, name: str):
        return self._model.get_parameter(name)

    def set_parameter(self, name: str, value: float) -> None:
        previous_network = self._network or self._continuation_network
        can_continue = self._simulation_has_run and previous_network is not None
        try:
            self._model.set_parameter(name, value)
            overrides = self.__dict__.setdefault("_parameter_overrides", {})
            overrides.pop(name, None)
            overrides[name] = value
        finally:
            # Generated networks contain evaluated seed amounts and other
            # parameter-dependent compile results. Also discard the cache if
            # parameter reevaluation raises after changing the model.
            self._continuation_network = previous_network if can_continue else None
            self._network = None
            self._network_from_continuation = False
            self._simulation_has_run = can_continue

    def reset_simulation(self) -> None:
        """Discard the current native trajectory and regenerate from model seeds."""
        if self._network is not None and _cpp is not None:
            _cpp.reset_simulation(self._network)
        self._network = None
        self._continuation_network = None
        self._network_from_continuation = False
        self._simulation_has_run = False

    def parameter_scan(self, *args, **kwargs):
        from bionetgen.scan import parameter_scan as _parameter_scan

        return _parameter_scan(self, *args, **kwargs)

    def parameter_scan_2d(self, *args, **kwargs):
        from bionetgen.scan import parameter_scan_2d as _parameter_scan_2d

        return _parameter_scan_2d(self, *args, **kwargs)

    def sensitivity_analysis(self, *args, **kwargs):
        from bionetgen.sensitivity import sensitivity_analysis as _sensitivity

        return _sensitivity(self, *args, **kwargs)

    def contact_map(self, path: Optional[str] = None):
        from bionetgen.viz import write_contact_map

        return write_contact_map(self, path)

    def regulatory_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_regulatory_graph

        return write_regulatory_graph(self, path)

    def rule_influence_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_rule_influence_graph

        return write_rule_influence_graph(self, path)

    def reaction_network_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_reaction_network_graph

        return write_reaction_network_graph(self, path)

    def ruleviz_pattern(self, path: Optional[str] = None):
        from bionetgen.viz import write_ruleviz_pattern

        return write_ruleviz_pattern(self, path)

    def ruleviz_operation(self, path: Optional[str] = None):
        from bionetgen.viz import write_ruleviz_operation

        return write_ruleviz_operation(self, path)

    def process_graph(self, path: Optional[str] = None):
        from bionetgen.viz import write_process_graph

        return write_process_graph(self, path)

    def sbml_multi(self, path: Optional[str] = None):
        from bionetgen.viz import write_sbml_multi

        return write_sbml_multi(self, path)

    # ------------------------------------------------------------------
    # Topology edits
    #
    # Each edit regenerates the model's BNGL, changes one block, and parses
    # the result again, so an edited model behaves exactly like a model
    # written with that change in BNGL. The edit is atomic: if the edited
    # model does not parse, the model is left unchanged. Parameter values set
    # with set_parameter are kept. An edit discards any generated network and
    # simulation continuation state, because the species set may change.
    # ------------------------------------------------------------------

    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _BLOCK_ORDER = (
        "parameters",
        "compartments",
        "molecule types",
        "seed species",
        "observables",
        "functions",
        "energy patterns",
        "barrier patterns",
        "reaction rules",
    )

    @staticmethod
    def _block_line(block: str, kind: str) -> re.Pattern:
        words = r"[ \t]+".join(re.escape(word) for word in block.split())
        return re.compile(rf"(?im)^[ \t]*{kind}[ \t]+{words}[ \t]*$")

    @classmethod
    def _insert_block_line(cls, text: str, block: str, line: str) -> str:
        end = cls._block_line(block, "end").search(text)
        if end is not None:
            return text[: end.start()] + "  " + line + "\n" + text[end.start() :]
        position = None
        for later in cls._BLOCK_ORDER[cls._BLOCK_ORDER.index(block) + 1 :]:
            begin = cls._block_line(later, "begin").search(text)
            if begin is not None:
                position = begin.start()
                break
        if position is None:
            end_model = cls._block_line("model", "end").search(text)
            if end_model is None:
                raise ValueError("model BNGL has no 'end model' line")
            position = end_model.start()
        return (
            text[:position]
            + f"begin {block}\n  {line}\nend {block}\n\n"
            + text[position:]
        )

    @classmethod
    def _block_body(cls, text: str, block: str):
        begin = cls._block_line(block, "begin").search(text)
        end = cls._block_line(block, "end").search(text)
        if begin is None or end is None or end.start() < begin.end():
            return None
        return begin.end(), end.start()

    @staticmethod
    def _split_seed_line(line: str):
        """Return (constant, compartment, pattern, rest) for one seed line."""
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            return None
        parts = stripped.split(None, 1)
        token = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        constant = token.startswith("$")
        token = token[1:] if constant else token
        compartment = None
        match = re.match(r"^@([A-Za-z_][A-Za-z0-9_]*)::?(.*)$", token)
        if match:
            compartment, token = match.group(1), match.group(2)
        return constant, compartment, token, rest

    def _seed_line_indices(self, text: str, pattern: str, compartment):
        span = self._block_body(text, "seed species")
        if span is None:
            return span, []
        wanted = re.sub(r"\s+", "", pattern)
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        for index, line in enumerate(lines):
            parsed = self._split_seed_line(line)
            if parsed is None:
                continue
            _constant, seed_compartment, seed_pattern, _rest = parsed
            if re.sub(r"\s+", "", seed_pattern) != wanted:
                continue
            if compartment is not None and seed_compartment != compartment:
                continue
            matches.append(index)
        return span, matches

    def _replace_seed_line(self, operation, pattern, compartment, replace):
        def edit(text: str) -> str:
            span, matches = self._seed_line_indices(text, pattern, compartment)
            where = f" in compartment {compartment!r}" if compartment else ""
            if not matches:
                raise ValueError(f"no seed species {pattern!r}{where}")
            if len(matches) > 1:
                raise ValueError(
                    f"seed species {pattern!r}{where} matches {len(matches)} "
                    "entries; pass compartment= to choose one"
                )
            lines = text[span[0] : span[1]].split("\n")
            replacement = replace(self._split_seed_line(lines[matches[0]]))
            if replacement is None:
                del lines[matches[0]]
            else:
                lines[matches[0]] = "  " + replacement
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology(operation, edit)

    @staticmethod
    def _format_amount(amount) -> str:
        if isinstance(amount, bool):
            raise TypeError("amount must be a number or a BNGL expression")
        if isinstance(amount, (int, float)):
            if not math.isfinite(float(amount)) or float(amount) < 0:
                raise ValueError("amount must be finite and nonnegative")
            return repr(float(amount)) if isinstance(amount, float) else str(amount)
        text = str(amount).strip()
        if not text or "\n" in text:
            raise ValueError("amount expression must be one nonempty line")
        return text

    @staticmethod
    def _format_parameter_value(value) -> str:
        if isinstance(value, bool):
            raise TypeError("parameter value must be a number or expression")
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise ValueError("parameter value must be finite")
            return repr(float(value)) if isinstance(value, float) else str(value)
        text = str(value).strip()
        if not text or "\n" in text:
            raise ValueError("parameter expression must be one nonempty line")
        return text

    def _parameter_line_indices(self, text: str, name: str):
        span = self._block_body(text, "parameters")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split()
            pname = parts[1] if parts[0].isdigit() and len(parts) > 1 else parts[0]
            if pname == name:
                matches.append(index)
        return span, matches

    def _rule_line_indices(self, text: str, name_or_label: str):
        span = self._block_body(text, "reaction rules")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        target = name_or_label.strip()
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            match = re.match(
                r"^(?:(\d+)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", stripped
            )
            if match:
                lbl = match.group(2)
                rule_body = match.group(3).strip()
                if lbl == target or stripped == target or rule_body == target:
                    matches.append(index)
                    continue
            parts = stripped.split(None, 1)
            body = parts[1] if parts[0].isdigit() and len(parts) > 1 else stripped
            if body == target or stripped == target:
                matches.append(index)
        return span, matches

    def _observable_line_indices(self, text: str, name: str):
        span = self._block_body(text, "observables")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split()
            idx = 1 if parts[0].isdigit() else 0
            if len(parts) > idx + 1 and parts[idx + 1] == name:
                matches.append(index)
        return span, matches

    def _compartment_line_indices(self, text: str, name: str):
        span = self._block_body(text, "compartments")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split()
            idx = 1 if parts[0].isdigit() else 0
            if len(parts) > idx and parts[idx] == name:
                matches.append(index)
        return span, matches

    def _molecule_type_line_indices(self, text: str, name_or_pattern: str):
        span = self._block_body(text, "molecule types")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        target = name_or_pattern.strip()
        target_name = target.split("(", 1)[0].strip()
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            mol_def = parts[1] if parts[0].isdigit() and len(parts) > 1 else stripped
            mol_name = mol_def.split("(", 1)[0].strip()
            if mol_name == target_name or mol_def == target:
                matches.append(index)
        return span, matches

    def _function_line_indices(self, text: str, name: str):
        span = self._block_body(text, "functions")
        if span is None:
            return span, []
        lines = text[span[0] : span[1]].split("\n")
        matches = []
        for index, line in enumerate(lines):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split()
            idx = 1 if parts[0].isdigit() else 0
            if len(parts) > idx:
                fn_token = parts[idx]
                fn_name = fn_token.split("(", 1)[0].strip()
                if fn_name == name:
                    matches.append(index)
        return span, matches

    def _edit_topology(self, operation: str, edit) -> None:
        self._require_export_supported(operation)
        if _cpp is None:
            raise RuntimeError("the BNG3 native extension is not available")
        edited = edit(_cpp.io.write_bngl_string(self._model))
        try:
            model = _cpp.parse_string(edited, source_path=self._source_path or "")
        except TypeError:
            # An extension built before parse_string accepted a source path.
            model = _cpp.parse_string(edited)
        except Exception as exc:
            raise ValueError(f"{operation} produced an invalid model: {exc}") from exc
        for name, value in self.__dict__.get("_parameter_overrides", {}).items():
            model.set_parameter(name, value)
        try:
            _cpp.generate_network(model, max_iter=0)
        except Exception as exc:
            raise ValueError(f"{operation} produced an invalid model: {exc}") from exc
        self._model = model
        self._network = None
        self._continuation_network = None
        self._network_from_continuation = False
        self._simulation_has_run = False

    def add_parameter(self, name: str, value) -> None:
        """Add a parameter, as a line in the BNGL parameters block."""
        if not self._IDENTIFIER.match(str(name)):
            raise ValueError(f"invalid parameter name {name!r}")
        val_str = self._format_parameter_value(value)
        line = f"{name} {val_str}"

        def edit(text: str) -> str:
            _span, matches = self._parameter_line_indices(text, name)
            if matches:
                raise ValueError(f"parameter {name!r} already exists")
            return self._insert_block_line(text, "parameters", line)

        self._edit_topology("add_parameter", edit)

    def remove_parameter(self, name: str) -> None:
        """Remove one parameter by name."""
        target = str(name).strip()
        if not target:
            raise ValueError("parameter name must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._parameter_line_indices(text, target)
            if not matches:
                raise ValueError(f"no parameter {target!r}")
            if len(matches) > 1:
                raise ValueError(f"parameter {target!r} matches {len(matches)} entries")
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_parameter", edit)

    def add_compartment(
        self,
        name: str,
        dimension: int,
        volume,
        parent: Optional[str] = None,
    ) -> None:
        """Add a compartment, as a line in the BNGL compartments block."""
        if not self._IDENTIFIER.match(str(name)):
            raise ValueError(f"invalid compartment name {name!r}")
        if isinstance(dimension, bool) or int(dimension) != dimension or dimension < 0:
            raise ValueError("dimension must be a nonnegative integer")
        if parent is not None and not self._IDENTIFIER.match(str(parent)):
            raise ValueError(f"invalid parent compartment name {parent!r}")
        line = f"{name} {int(dimension)} {self._format_amount(volume)}"
        if parent is not None:
            line += f" {parent}"
        self._edit_topology(
            "add_compartment",
            lambda text: self._insert_block_line(text, "compartments", line),
        )

    def remove_compartment(self, name: str) -> None:
        """Remove a compartment by name."""
        target = str(name).strip()
        if not target:
            raise ValueError("compartment name must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._compartment_line_indices(text, target)
            if not matches:
                raise ValueError(f"no compartment {target!r}")
            if len(matches) > 1:
                raise ValueError(
                    f"compartment {target!r} matches {len(matches)} entries"
                )
            pattern = rf"@\s*{re.escape(target)}\b"
            for block in (
                "seed species",
                "reaction rules",
                "observables",
                "compartments",
            ):
                bspan = self._block_body(text, block)
                if bspan is not None:
                    block_text = text[bspan[0] : bspan[1]]
                    if block == "compartments":
                        lines = [
                            l
                            for i, l in enumerate(block_text.split("\n"))
                            if i != matches[0]
                        ]
                        if any(
                            re.search(rf"\b{re.escape(target)}\b", l.split("#", 1)[0])
                            for l in lines
                        ):
                            raise ValueError(
                                f"compartment {target!r} is still referenced as parent in compartments"
                            )
                    elif re.search(pattern, block_text):
                        raise ValueError(
                            f"compartment {target!r} is still referenced in {block}"
                        )
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_compartment", edit)

    def add_molecule_type(self, definition: str) -> None:
        """Add a molecule type, for example ``"A(b,s~U~P)"``."""
        text = str(definition).strip()
        if not text or "\n" in text or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(", text):
            raise ValueError(f"invalid molecule type definition {definition!r}")
        self._edit_topology(
            "add_molecule_type",
            lambda model: self._insert_block_line(model, "molecule types", text),
        )

    def remove_molecule_type(self, name_or_definition: str) -> None:
        """Remove a molecule type by name or definition."""
        target = str(name_or_definition).strip()
        if not target:
            raise ValueError("molecule type name or definition must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._molecule_type_line_indices(text, target)
            if not matches:
                raise ValueError(f"no molecule type {target!r}")
            if len(matches) > 1:
                raise ValueError(
                    f"molecule type {target!r} matches {len(matches)} entries"
                )
            mol_name = target.split("(", 1)[0].strip()
            pattern = rf"\b{re.escape(mol_name)}\s*\("
            for block in ("seed species", "reaction rules", "observables"):
                bspan = self._block_body(text, block)
                if bspan is not None:
                    if re.search(pattern, text[bspan[0] : bspan[1]]):
                        raise ValueError(
                            f"molecule type {target!r} is still referenced in {block}"
                        )
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_molecule_type", edit)

    def add_seed_species(
        self,
        pattern: str,
        amount,
        compartment: Optional[str] = None,
        constant: bool = False,
    ) -> None:
        """Add a seed species with an initial amount (a number or expression)."""
        text = re.sub(r"\s+", "", str(pattern))
        if not text:
            raise ValueError("pattern must be nonempty")
        if compartment is not None and not self._IDENTIFIER.match(str(compartment)):
            raise ValueError(f"invalid compartment name {compartment!r}")
        line = ("$" if constant else "") + (
            f"@{compartment}:" if compartment is not None else ""
        )
        line += f"{text} {self._format_amount(amount)}"
        self._edit_topology(
            "add_seed_species",
            lambda model: self._insert_block_line(model, "seed species", line),
        )

    def remove_seed_species(
        self, pattern: str, compartment: Optional[str] = None
    ) -> None:
        """Remove one seed species, matched by pattern and compartment."""
        self._replace_seed_line(
            "remove_seed_species", pattern, compartment, lambda _parsed: None
        )

    def set_seed_species_amount(
        self, pattern: str, amount, compartment: Optional[str] = None
    ) -> None:
        """Set the initial amount of one seed species."""
        formatted = self._format_amount(amount)

        def replace(parsed):
            constant, seed_compartment, seed_pattern, rest = parsed
            unit = re.search(r"\[[^\]]*\]\s*$", rest)
            prefix = ("$" if constant else "") + (
                f"@{seed_compartment}:" if seed_compartment else ""
            )
            return f"{prefix}{seed_pattern} {formatted}" + (
                f" {unit.group(0).strip()}" if unit else ""
            )

        self._replace_seed_line(
            "set_seed_species_amount", pattern, compartment, replace
        )

    def move_species_to_compartment(
        self,
        pattern: str,
        compartment: str,
        from_compartment: Optional[str] = None,
    ) -> None:
        """Move one seed species to another compartment, keeping its amount."""
        if not self._IDENTIFIER.match(str(compartment)):
            raise ValueError(f"invalid compartment name {compartment!r}")

        def replace(parsed):
            constant, _old, seed_pattern, rest = parsed
            return ("$" if constant else "") + f"@{compartment}:{seed_pattern} {rest}"

        self._replace_seed_line(
            "move_species_to_compartment", pattern, from_compartment, replace
        )

    def add_observable(
        self, name: str, pattern: str, obs_type: str = "Molecules"
    ) -> None:
        """Add an observable to the observables block."""
        if not self._IDENTIFIER.match(str(name)):
            raise ValueError(f"invalid observable name {name!r}")
        if obs_type not in ("Molecules", "Species"):
            raise ValueError(
                f"observable type must be 'Molecules' or 'Species', got {obs_type!r}"
            )
        pat = str(pattern).strip()
        if not pat or "\n" in pat:
            raise ValueError("observable pattern must be a single non-empty expression")
        line = f"{obs_type} {name} {pat}"

        def edit(text: str) -> str:
            _span, matches = self._observable_line_indices(text, name)
            if matches:
                raise ValueError(f"observable {name!r} already exists")
            return self._insert_block_line(text, "observables", line)

        self._edit_topology("add_observable", edit)

    def remove_observable(self, name: str) -> None:
        """Remove an observable by name."""
        target = str(name).strip()
        if not target:
            raise ValueError("observable name must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._observable_line_indices(text, target)
            if not matches:
                raise ValueError(f"no observable {target!r}")
            if len(matches) > 1:
                raise ValueError(
                    f"observable {target!r} matches {len(matches)} entries"
                )
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_observable", edit)

    def add_reaction_rule(self, definition: str, name: Optional[str] = None) -> None:
        """Add a reaction rule to the reaction rules block."""
        text_def = str(definition).strip()
        if not text_def or "\n" in text_def:
            raise ValueError("reaction rule definition must be a single non-empty line")
        if name is not None:
            if not self._IDENTIFIER.match(str(name)):
                raise ValueError(f"invalid reaction rule name {name!r}")
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", text_def)
            line = f"{name}: {match.group(2)}" if match else f"{name}: {text_def}"
        else:
            line = text_def

        self._edit_topology(
            "add_reaction_rule",
            lambda text: self._insert_block_line(text, "reaction rules", line),
        )

    def remove_reaction_rule(self, name_or_label: str) -> None:
        """Remove a reaction rule by name/label or definition."""
        target = str(name_or_label).strip()
        if not target:
            raise ValueError("reaction rule name or definition must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._rule_line_indices(text, target)
            if not matches:
                raise ValueError(f"no reaction rule {target!r}")
            if len(matches) > 1:
                raise ValueError(
                    f"reaction rule {target!r} matches {len(matches)} entries"
                )
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_reaction_rule", edit)

    def add_function(self, definition: str, name: Optional[str] = None) -> None:
        """Add a function to the functions block."""
        text_def = str(definition).strip()
        if not text_def or "\n" in text_def:
            raise ValueError("function definition must be a single non-empty line")
        if name is not None:
            if not self._IDENTIFIER.match(str(name)):
                raise ValueError(f"invalid function name {name!r}")
            if not (
                text_def.startswith(f"{name}(")
                or text_def.startswith(f"{name} =")
                or text_def.startswith(f"{name} ")
            ):
                line = f"{name}() = {text_def}"
            else:
                line = text_def
        else:
            line = text_def

        self._edit_topology(
            "add_function",
            lambda text: self._insert_block_line(text, "functions", line),
        )

    def remove_function(self, name: str) -> None:
        """Remove a function by name."""
        target = str(name).strip()
        if not target:
            raise ValueError("function name must be non-empty")

        def edit(text: str) -> str:
            span, matches = self._function_line_indices(text, target)
            if not matches:
                raise ValueError(f"no function {target!r}")
            if len(matches) > 1:
                raise ValueError(f"function {target!r} matches {len(matches)} entries")
            lines = text[span[0] : span[1]].split("\n")
            del lines[matches[0]]
            return text[: span[0]] + "\n".join(lines) + text[span[1] :]

        self._edit_topology("remove_function", edit)

    def generate_network(self, max_iter: int = 100) -> _cpp.GeneratedNetwork:
        carrying_session = self._continuation_network is not None
        self._network = _cpp.generate_network(self._model, max_iter=max_iter)
        if carrying_session:
            _cpp.continue_simulation_from(self._continuation_network, self._network)
            self._continuation_network = None
        self._network_from_continuation = carrying_session
        return self._network

    def simulate(
        self,
        method: str = "ode",
        t_end: float = 100.0,
        n_steps: int = 100,
        t_start: float = 0.0,
        rtol: float = 1e-8,
        atol: float = 1e-12,
        seed: int = 0,
        pla_config: str = "",
        psa_poplevel: float = 100.0,
        verbose: bool = False,
        max_step: float = 0.0,
        steady_state: bool = False,
        steady_state_tol: Optional[float] = None,
        stop_if: str = "",
        sample_times=None,
        max_sim_steps: int = 0,
        output_step_interval: int = 0,
        sparse: bool = False,
        check_product_scale: float = 0.0,
        equilibrate: float = 0.0,
        traversal_limit: int = -1,
        backend: Optional[str] = None,
        continue_simulation: bool = False,
    ) -> SimResult:
        """Run a simulation using the specified method.

        Parameters
        ----------
        method : str
            One of "ode", "ssa", "nf" (network-free), "pla", or "psa".
        t_end : float
            End time for simulation.
        n_steps : int
            Number of output time steps.
        t_start : float
            Absolute start time for the simulation. NF uses this time for
            time-dependent functions and output coordinates.
        continue_simulation : bool
            Continue the last successful native ODE/SSA trajectory from
            ``t_start``. The default starts a fresh trajectory.
        rtol, atol : float
            Relative and absolute tolerances (ODE only).
        seed : int
            Random seed for SSA/NF and random SBML event assignments in ODE
            simulations (0 = system default). It has no effect on deterministic
            ODE trajectories without random event assignments.
        pla_config : str
            PLA configuration string (PLA only).
        psa_poplevel : float
            Population level threshold for PSA (PSA only).
        verbose : bool
            Print progress information.
        max_step : float
            Maximum internal CVODE step size (ODE only; 0 disables the limit).
        steady_state : bool
            Stop an ODE run when the derivative norm is below the tolerance.
        steady_state_tol : float, optional
            Derivative tolerance for steady-state stopping.
        stop_if : str
            Expression evaluated at output points/events; a nonzero value stops
            ODE/SSA simulation.
        sample_times : sequence of float, optional
            Strictly increasing ODE/SSA/NF output times between ``t_start``
            and ``t_end``. If the final time is omitted, ``t_end`` is appended.
        max_sim_steps : int
            Maximum internal SSA reaction events (0 = unlimited).
        output_step_interval : int
            Output every N internal SSA reaction events when ``sample_times``
            is not set.
        sparse : bool
            Request the sparse CVODE linear solver.
        check_product_scale : float
            Warn when an ODE species exceeds this positive threshold.
        traversal_limit : int
            NFsim bonded-neighborhood traversal depth. ``-1`` uses the
            adapter's model-derived recommendation; non-negative values mirror
            NFsim's ``-utl`` control. NF only.

        Returns
        -------
        SimResult
            Object containing time, observable, and concentration arrays.
        """
        if not isinstance(method, str):
            raise TypeError("method must be a string")
        if not isinstance(continue_simulation, bool):
            raise TypeError("continue_simulation must be a boolean")
        method = method.lower()
        if method not in {"ode", "ssa", "nf", "pla", "psa"}:
            raise ValueError(
                "Unknown simulation method: "
                f"{method!r}. Use 'ode', 'ssa', 'nf', 'pla', or 'psa'."
            )
        if self._algebraic_rules and method != "ode":
            raise ValueError("SBML algebraic rules require method='ode'")
        if continue_simulation and method not in {"ode", "ssa"}:
            raise ValueError(
                "continue_simulation is supported only for native ODE and SSA"
            )
        native_fresh_run = method in {"ode", "ssa"} and not continue_simulation
        if (
            not continue_simulation
            and self._simulation_has_run
            and not native_fresh_run
        ):
            self.reset_simulation()
        if not math.isfinite(float(t_start)) or not math.isfinite(float(t_end)):
            raise ValueError("t_start and t_end must be finite")
        if t_end < t_start:
            raise ValueError("t_end must be greater than or equal to t_start")
        if isinstance(n_steps, bool):
            raise TypeError("n_steps must be a positive integer")
        try:
            n_steps = operator.index(n_steps)
        except TypeError as exc:
            raise TypeError("n_steps must be a positive integer") from exc
        if n_steps < 0 or (n_steps == 0 and sample_times is None):
            raise ValueError("n_steps must be positive unless sample_times is set")
        if not math.isfinite(float(rtol)) or rtol <= 0.0:
            raise ValueError("rtol must be finite and positive")
        if not math.isfinite(float(atol)) or atol <= 0.0:
            raise ValueError("atol must be finite and positive")
        if not math.isfinite(float(psa_poplevel)):
            raise ValueError("psa_poplevel must be finite")
        if not math.isfinite(float(max_step)) or max_step < 0.0:
            raise ValueError("max_step must be finite and non-negative")
        if steady_state_tol is None:
            steady_state_tol = atol
        if not math.isfinite(float(steady_state_tol)) or steady_state_tol <= 0.0:
            raise ValueError("steady_state_tol must be finite and positive")
        if not isinstance(stop_if, str):
            raise TypeError("stop_if must be a string")
        if not math.isfinite(float(check_product_scale)) or check_product_scale < 0.0:
            raise ValueError("check_product_scale must be finite and non-negative")
        if not math.isfinite(float(equilibrate)) or equilibrate < 0.0:
            raise ValueError("equilibrate must be finite and non-negative")
        if isinstance(traversal_limit, bool):
            raise TypeError("traversal_limit must be -1 or a non-negative integer")
        try:
            traversal_limit = operator.index(traversal_limit)
        except TypeError as exc:
            raise TypeError(
                "traversal_limit must be -1 or a non-negative integer"
            ) from exc
        if traversal_limit < -1:
            raise ValueError("traversal_limit must be -1 or a non-negative integer")
        if method != "nf" and equilibrate != 0.0:
            raise ValueError("equilibrate is supported only for method='nf'")
        if method != "nf" and traversal_limit != -1:
            raise ValueError("traversal_limit is supported only for method='nf'")
        for option_name, option_value in {
            "max_sim_steps": max_sim_steps,
            "output_step_interval": output_step_interval,
        }.items():
            if isinstance(option_value, bool):
                raise TypeError(f"{option_name} must be a non-negative integer")
            try:
                option_value = operator.index(option_value)
            except TypeError as exc:
                raise TypeError(
                    f"{option_name} must be a non-negative integer"
                ) from exc
            if option_value < 0:
                raise ValueError(f"{option_name} must be a non-negative integer")
            if option_name == "max_sim_steps":
                max_sim_steps = option_value
            else:
                output_step_interval = option_value

        normalized_sample_times = []
        if sample_times is not None:
            try:
                normalized_sample_times = [float(value) for value in sample_times]
            except (TypeError, ValueError) as exc:
                raise TypeError("sample_times must be a sequence of numbers") from exc
            if not normalized_sample_times:
                raise ValueError("sample_times must not be empty")
            if any(not math.isfinite(value) for value in normalized_sample_times):
                raise ValueError("sample_times must contain only finite values")
            if any(
                later <= earlier
                for earlier, later in zip(
                    normalized_sample_times, normalized_sample_times[1:]
                )
            ):
                raise ValueError("sample_times must be strictly increasing")
            if (
                normalized_sample_times[0] < t_start
                or normalized_sample_times[-1] > t_end
            ):
                raise ValueError("sample_times must lie between t_start and t_end")
            if normalized_sample_times[-1] < t_end:
                normalized_sample_times.append(float(t_end))
        if n_steps == 0 and not normalized_sample_times:
            raise ValueError("n_steps must be positive unless sample_times is set")

        ode_only_options = (
            max_step > 0.0 or steady_state or sparse or check_product_scale > 0.0
        )
        if method != "ode" and ode_only_options:
            raise ValueError(
                "max_step, steady-state, sparse, and check_product_scale are "
                "supported only for method='ode'"
            )
        if method == "ode" and (max_sim_steps or output_step_interval):
            raise ValueError(
                "max_sim_steps and output_step_interval are supported only "
                "for method='ssa'"
            )
        if method not in {"ode", "ssa", "nf"} and (
            stop_if or max_sim_steps or output_step_interval
        ):
            raise ValueError(
                "stop_if, max_sim_steps, and output_step_interval are supported "
                "only for method='ode' or method='ssa'"
            )
        if method == "nf" and (stop_if or max_sim_steps or output_step_interval):
            raise ValueError(
                "stop_if, max_sim_steps, and output_step_interval are supported "
                "only for method='ode' or method='ssa'"
            )

        use_bngsim = False
        if method == "nf":
            # backend is not applicable to network-free; reject explicit bngsim
            if backend is not None and str(backend).lower() not in (
                "auto",
                "native",
                "nf",
                "nfsim",
            ):
                if str(backend).lower() == "bngsim":
                    raise ValueError("backend='bngsim' is not valid for method='nf'")
            raw = _cpp.simulate_nf(
                self._model,
                t_end=t_end,
                n_steps=n_steps,
                t_start=t_start,
                seed=seed,
                verbose=verbose,
                equilibrate=equilibrate,
                source_path=self._source_path or "",
                sample_times=normalized_sample_times,
                traversal_limit=traversal_limit,
                require_direct=getattr(self, "_native_bngir_v02_only", False),
            )
            # NFsim path remains independent; annotate backend for diagnostics.
            if isinstance(raw, dict) and "backend" not in raw:
                raw["backend"] = "nfsim"
        else:
            # Finite-network backend dispatch (ADR 0003).
            # Default is "auto" -> native during migration; explicit "bngsim"
            # opts into the canonical BNGsim backend where faithfully lowerable.
            # Env var BIONETGEN_FINITE_BACKEND provides CI/developer switch.
            effective_backend = backend
            if effective_backend is None:
                effective_backend = os.environ.get("BIONETGEN_FINITE_BACKEND", "auto")
            if not isinstance(effective_backend, str):
                raise TypeError("backend must be a string")
            eb = effective_backend.strip().lower()
            if eb in ("", "auto", "automatic"):
                eb = "auto"
            elif eb in ("native", "bng3", "default"):
                eb = "native"
            elif eb in ("bngsim", "bng_sim", "bng-sim"):
                eb = "bngsim"
            else:
                raise ValueError(
                    f"Unknown backend: {effective_backend!r}. Use 'auto', 'native', or 'bngsim'."
                )

            fresh_snapshot = None
            if native_fresh_run and eb != "bngsim":
                fresh_snapshot = (
                    self._network,
                    self._continuation_network,
                    self._network_from_continuation,
                    self._simulation_has_run,
                )

            def restore_failed_fresh_run():
                if fresh_snapshot is not None:
                    (
                        self._network,
                        self._continuation_network,
                        self._network_from_continuation,
                        self._simulation_has_run,
                    ) = fresh_snapshot

            if eb == "bngsim" and self._simulation_has_run and not continue_simulation:
                self.reset_simulation()

            if native_fresh_run:
                if self._network is None:
                    # A parameter change retains the previous network only
                    # for an explicit continuation. Fresh compilation uses
                    # current seeds.
                    self._continuation_network = None
                elif self._network_from_continuation:
                    self._network = None
                    self._network_from_continuation = False
                    self._continuation_network = None

            if self._network is None:
                try:
                    self.generate_network()
                except Exception:
                    restore_failed_fresh_run()
                    raise

            # For explicit bngsim we fail closed; for auto we keep native as
            # default (Phase A-C). Phase D will flip auto to prefer bngsim
            # when check_bngsim_lowering reports supported.
            use_bngsim = False
            bngsim_blockers = None
            if eb == "bngsim":
                use_bngsim = True
            elif eb == "auto":
                # Conservative: stay on native. Developers can set
                # BIONETGEN_FINITE_BACKEND=bngsim to exercise the BNGsim path
                # for supported models in CI.
                use_bngsim = False

            if use_bngsim:
                if self._algebraic_rules:
                    raise RuntimeError(
                        "SBML algebraic rules require the native IDA solver"
                    )
                if continue_simulation:
                    raise RuntimeError(
                        "continue_simulation requires the native ODE or SSA backend"
                    )
                # PLA/PSA not yet claimed for BNGsim — fail closed before any
                # lowering check so the message is precise even when the build
                # is unavailable.
                if method in ("pla", "psa"):
                    raise RuntimeError(
                        f"BNGsim backend does not yet support method='{method}'; native fallback required"
                    )
                # Solver availability and semantic lowerability are separate
                # capabilities; check each boundary before dispatch.
                if _cpp is None or not hasattr(_cpp, "check_bngsim_lowering"):
                    raise RuntimeError("BNGsim backend unavailable in this build")
                if not hasattr(_cpp, "bngsim_available") or not _cpp.bngsim_available():
                    raise RuntimeError(
                        "BNGsim backend unavailable: build without BUILD_BNGSIM_ADAPTER"
                    )
                try:
                    chk = _cpp.check_bngsim_lowering(self._model, self._network)
                    if not chk.get("supported", False):
                        blockers = chk.get("blockers", [])
                        bngsim_blockers = (
                            "; ".join(blockers) if blockers else "unsupported"
                        )
                        # Distinguish build vs semantic for the error prefix.
                        if any("unavailable" in b.lower() for b in blockers):
                            raise RuntimeError(
                                f"BNGsim backend unavailable: {bngsim_blockers}"
                            )
                        raise RuntimeError(
                            f"BioNetGen finite-network backend cannot represent model for BNGsim: {bngsim_blockers}"
                        )
                except RuntimeError:
                    raise
                except Exception as exc:
                    raise RuntimeError(f"BNGsim lowering check failed: {exc}") from exc

            if method == "ode":
                if use_bngsim:
                    raw = _cpp.simulate_ode_bngsim(
                        self._model,
                        self._network,
                        t_end=t_end,
                        n_steps=n_steps,
                        t_start=t_start,
                        rtol=rtol,
                        atol=atol,
                        method="cvode",
                        max_step=max_step,
                        steady_state=steady_state,
                        steady_state_tol=steady_state_tol,
                        stop_if=stop_if,
                        sample_times=normalized_sample_times,
                        max_sim_steps=max_sim_steps,
                        output_step_interval=output_step_interval,
                        sparse=sparse,
                        check_product_scale=check_product_scale,
                    )
                    if isinstance(raw, dict) and "backend" not in raw:
                        raw["backend"] = "bngsim"
                else:
                    try:
                        raw = _cpp.simulate_ode(
                            self._model,
                            self._network,
                            t_end=t_end,
                            n_steps=n_steps,
                            t_start=t_start,
                            rtol=rtol,
                            atol=atol,
                            method="cvode",
                            seed=seed,
                            max_step=max_step,
                            steady_state=steady_state,
                            steady_state_tol=steady_state_tol,
                            stop_if=stop_if,
                            sample_times=normalized_sample_times,
                            max_sim_steps=max_sim_steps,
                            output_step_interval=output_step_interval,
                            continue_simulation=continue_simulation,
                            fresh_from_initial_state=native_fresh_run,
                            sparse=sparse,
                            check_product_scale=check_product_scale,
                            algebraic_rules=self._algebraic_rules,
                        )
                    except Exception:
                        restore_failed_fresh_run()
                        raise
                    if isinstance(raw, dict) and "backend" not in raw:
                        raw["backend"] = "native"
            elif method == "ssa":
                if use_bngsim:
                    raw = _cpp.simulate_ssa_bngsim(
                        self._model,
                        self._network,
                        t_end=t_end,
                        n_steps=n_steps,
                        t_start=t_start,
                        seed=seed,
                        stop_if=stop_if,
                        sample_times=normalized_sample_times,
                        max_sim_steps=max_sim_steps,
                        output_step_interval=output_step_interval,
                        continue_simulation=continue_simulation,
                    )
                    if isinstance(raw, dict) and "backend" not in raw:
                        raw["backend"] = "bngsim"
                else:
                    try:
                        raw = _cpp.simulate_ssa(
                            self._model,
                            self._network,
                            t_end=t_end,
                            n_steps=n_steps,
                            t_start=t_start,
                            seed=seed,
                            stop_if=stop_if,
                            sample_times=normalized_sample_times,
                            max_sim_steps=max_sim_steps,
                            output_step_interval=output_step_interval,
                            continue_simulation=continue_simulation,
                            fresh_from_initial_state=native_fresh_run,
                        )
                    except Exception:
                        restore_failed_fresh_run()
                        raise
                    if isinstance(raw, dict) and "backend" not in raw:
                        raw["backend"] = "native"
            elif method == "pla":
                # PLA/PSA not yet routed through BNGsim in this phase; keep native
                # but surface a precise message if backend=bngsim was requested.
                if use_bngsim:
                    raise RuntimeError(
                        "BNGsim backend does not yet support method='pla'; native fallback required"
                    )
                raw = _cpp.simulate_pla(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    config_str=pla_config,
                    t_start=t_start,
                )
                if isinstance(raw, dict) and "backend" not in raw:
                    raw["backend"] = "native"
            elif method == "psa":
                if use_bngsim:
                    # PSA not claimed; fail closed rather than silently running native
                    raise RuntimeError(
                        "BNGsim backend does not yet support method='psa'; native fallback required"
                    )
                raw = _cpp.simulate_psa(
                    self._model,
                    self._network,
                    t_end=t_end,
                    n_steps=n_steps,
                    poplevel=psa_poplevel,
                    t_start=t_start,
                )
                if isinstance(raw, dict) and "backend" not in raw:
                    raw["backend"] = "native"
            else:
                raise AssertionError("validated method dispatch is incomplete")

        if method in {"ode", "ssa"} and not use_bngsim:
            self._simulation_has_run = True
        return SimResult(raw)

    def execute(self, verbose: bool = False) -> None:
        """Execute all actions defined in the model's action block."""
        self._require_export_supported("Action execution")
        source = self._source_path or "."
        _cpp.execute(self._model, source, verbose=verbose)

    def write_xml(self, path: str) -> None:
        self._require_export_supported("BNG-XML export")
        _cpp.io.write_xml(self._model, path)

    def to_xml(self) -> str:
        """Serialize the model to an in-memory BNG-XML string."""
        self._require_export_supported("BNG-XML export")
        return _cpp.io.write_xml_string(self._model)

    def write_bngl(self, path: str) -> None:
        self._require_export_supported("BNGL export")
        _cpp.io.write_bngl(self._model, path)

    def to_bngl(self) -> str:
        """Serialize the model to an in-memory BNGL string."""
        self._require_export_supported("BNGL export")
        return _cpp.io.write_bngl_string(self._model)

    def to_bngir(self, *, provenance=None, version="0.1") -> str:
        """Serialize semantic model entities as deterministic BNGIR JSON.

        Version ``0.1`` is the compatibility wire format. Version ``0.2`` is
        the structural semantic format backed by ``bng::compile::CompiledModel``.
        """
        from bionetgen.bngir import to_bngir

        return to_bngir(self, provenance=provenance, version=version)

    def write_net(self, path: str) -> None:
        self._require_export_supported("NET export")
        if self._network is None:
            self.generate_network()
        _cpp.io.write_net(self._model, self._network, path)

    def write_sbml(self, path: str) -> None:
        self._require_export_supported("SBML export")
        if self._network is None:
            self.generate_network()
        _cpp.io.write_sbml(
            self._model,
            self._network,
            path,
            source_metadata=self._source_metadata,
        )

    def write_matlab(self, path: str) -> None:
        self._require_export_supported("MATLAB export")
        if self._network is None:
            self.generate_network()
        _cpp.io.write_matlab(self._model, self._network, path)

    def write_latex(self, path: str) -> None:
        self._require_export_supported("LaTeX export")
        if self._network is None:
            self.generate_network()
        _cpp.io.write_latex(self._model, self._network, path)

    def __repr__(self) -> str:
        name = self.name or "(unnamed)"
        return (
            f"<BioNetGenModel '{name}' "
            f"rules={len(self.reaction_rules)} "
            f"species={len(self.seed_species)}>"
        )

    def _repr_html_(self) -> str:
        from bionetgen.display import render_model_html

        return render_model_html(self)


def load(path: Union[str, Path]) -> BioNetGenModel:
    """Load a BNGL model file.

    Parameters
    ----------
    path : str or Path
        Path to the .bngl file.

    Returns
    -------
    BioNetGenModel
        The loaded model.
    """
    path = str(Path(path).resolve())
    cpp_model = _cpp.parse_file(path)
    return BioNetGenModel(cpp_model, source_path=path)


def run(
    path: Union[str, Path],
    method: str = "ode",
    t_end: float = 100.0,
    n_steps: int = 100,
    **kwargs,
) -> SimResult:
    """Load a model and run its simulation in one call.

    Parameters
    ----------
    path : str or Path
        Path to the .bngl file.
    method : str
        Simulation method ("ode", "ssa", "nf", "pla", or "psa").
    t_end : float
        End time.
    n_steps : int
        Number of output steps.

    Returns
    -------
    SimResult
        Simulation results.
    """
    model = load(path)
    return model.simulate(method=method, t_end=t_end, n_steps=n_steps, **kwargs)
