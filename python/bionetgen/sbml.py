"""SBML import helpers that bridge atomizer output to the C++ model API."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from bionetgen.core.exc import BNGError
from bionetgen.model import BioNetGenModel, _cpp


class BioNetGenError(BNGError):
    """Public SBML import error used by the new API."""


def _native_algebraic_rules(model) -> list[tuple[str, str]]:
    """Select native DAE state coordinates for the coupled algebraic system."""
    algebraic = [rule for rule in model.rules if rule.type == "algebraic"]
    if not algebraic:
        return []
    from bionetgen.atomizer.modern.writer import (
        algebraic_residual_name,
        native_algebraic_targets,
        standardize_name,
    )

    try:
        targets = native_algebraic_targets(model)
    except ValueError as exc:
        raise BioNetGenError(str(exc)) from exc
    return [
        (
            f"{standardize_name(target)}_amt"
            if target not in model.species
            else standardize_name(target),
            f"{algebraic_residual_name(index)}()",
        )
        for index, target in enumerate(targets)
    ]


def _require_libsbml() -> None:
    try:
        __import__("libsbml")
    except ImportError as exc:
        raise BioNetGenError(
            "SBML import requires the optional 'python-libsbml' dependency; "
            "install it with bionetgen[full]"
        ) from exc


def _translate_modern_with_model(
    sbml_path: str, atomize: bool, options: dict
) -> tuple[str, object]:
    """Translate through one Atomizer instance and retain its source model."""

    _require_libsbml()

    try:
        from bionetgen.atomizer.modern import Atomizer

        sbml_text = Path(sbml_path).read_text(encoding="utf-8-sig")
        atomizer = Atomizer(
            atomize=atomize,
            use_id=options.get("use_id", options.get("molecule_id", False)),
            annotation=options.get("annotation", False),
            quiet_mode=options.get("quiet_mode", True),
            actions=options.get("actions", ""),
            t_end=options.get("t_end", 10),
            n_steps=options.get("n_steps", 100),
            native_dae_runtime=options.get("native_dae_runtime", False),
        )
        result = atomizer.atomize(sbml_text)
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise BioNetGenError(f"Modern SBML atomizer is unavailable: {exc}") from exc
    if not result.success or not result.bngl:
        raise BioNetGenError(
            f"Modern SBML atomization failed for {sbml_path}: {result.error or 'no BNGL output'}"
        )
    return result.bngl, atomizer.get_model()


def _translate_sbml(sbml_path: str, atomize: bool = False, **options) -> str:
    backend = str(options.pop("atomizer_backend", "modern")).lower()
    if backend not in {"modern", "playground", "legacy", "native"}:
        raise BioNetGenError(
            f"Unknown SBML atomizer backend {backend!r}; use 'modern' or 'legacy'"
        )

    if backend in {"modern", "playground"}:
        bngl_text, _ = _translate_modern_with_model(sbml_path, atomize, options)
        return bngl_text

    _require_libsbml()

    try:
        from bionetgen.atomizer import libsbml2bngl as translator
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise BioNetGenError(f"SBML import is unavailable: {exc}") from exc

    sbml_path = str(Path(sbml_path).resolve())
    reaction_definitions, use_id, naming_conventions = (
        translator.selectReactionDefinitions(sbml_path)
    )

    with TemporaryDirectory() as temp_dir:
        output_path = str(Path(temp_dir) / (Path(sbml_path).stem + ".bngl"))
        result = translator.analyzeFile(
            sbml_path,
            reaction_definitions,
            use_id,
            naming_conventions,
            output_path,
            speciesEquivalence=options.get("species_equivalence"),
            atomize=atomize,
            bioGrid=options.get("bio_grid", False),
            pathwaycommons=options.get("pathwaycommons", False),
            ignore=options.get("ignore", False),
            noConversion=options.get("no_conversion", False),
            memoizedResolver=options.get("memoized_resolver", True),
            replaceLocParams=options.get("replace_local_parameters", True),
            quietMode=options.get("quiet_mode", True),
            logLevel=options.get("log_level", "WARNING"),
            obs_map_file=options.get("obs_map_file"),
        )

        if result is None:
            raise BioNetGenError(f"SBML translation failed for {sbml_path}")

        bngl_text = getattr(result, "finalString", None)
        if not bngl_text:
            with open(output_path, "r", encoding="utf-8") as handle:
                bngl_text = handle.read()

        if not bngl_text:
            raise BioNetGenError(
                f"SBML translation produced no BNGL output for {sbml_path}"
            )

        return bngl_text


def sbml_to_bngl(sbml_path: str, atomize: bool = False, **options) -> str:
    """Translate SBML to BNGL text."""

    return _translate_sbml(sbml_path, atomize=atomize, **options)


def from_sbml(sbml_path: str, atomize: bool = False, **options) -> BioNetGenModel:
    """Load SBML and return a BioNetGenModel."""

    if _cpp is None:
        raise ImportError(
            "The compiled _bionetgen_cpp extension is required to import SBML"
        )
    backend = str(options.get("atomizer_backend", "modern")).lower()
    if backend in {"modern", "playground"}:
        from bionetgen.atomizer.modern import source_metadata_payload

        bngl_text, parsed_model = _translate_modern_with_model(
            sbml_path, atomize, {**options, "native_dae_runtime": True}
        )
        algebraic_rules = _native_algebraic_rules(parsed_model)
        algebraic_rules.extend(
            (str(symbol), str(expression))
            for symbol, expression in getattr(
                parsed_model, "fast_equilibrium_rules", ()
            )
        )
        if (
            algebraic_rules
            and parsed_model.events
            and "begin bng3_events version 1" not in bngl_text
        ):
            raise BioNetGenError(
                "SBML algebraic-rule models with events require the native DAE "
                "event runtime; one or more events could not be represented"
            )
        return BioNetGenModel(
            _cpp.parse_string(bngl_text),
            source_path=str(sbml_path),
            source_metadata=source_metadata_payload(parsed_model),
            algebraic_rules=algebraic_rules,
        )
    return BioNetGenModel(
        _cpp.parse_string(sbml_to_bngl(sbml_path, atomize=atomize, **options)),
        source_path=str(sbml_path),
    )


__all__ = ["BioNetGenError", "from_sbml", "sbml_to_bngl"]
