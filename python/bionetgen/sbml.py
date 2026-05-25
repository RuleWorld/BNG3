"""SBML import helpers that bridge atomizer output to the C++ model API."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from bionetgen.core.exc import BNGError
from bionetgen.model import BioNetGenModel

try:
    from bionetgen import _bionetgen_cpp as _cpp
except ImportError:
    try:
        import _bionetgen_cpp as _cpp
    except ImportError:
        _cpp = None


class BioNetGenError(BNGError):
    """Public SBML import error used by the new API."""


def _translate_sbml(sbml_path: str, atomize: bool = False, **options) -> str:
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
    return BioNetGenModel(
        _cpp.parse_string(sbml_to_bngl(sbml_path, atomize=atomize, **options))
    )


__all__ = ["BioNetGenError", "from_sbml", "sbml_to_bngl"]
