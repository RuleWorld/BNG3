from __future__ import annotations

import glob
import os
from pathlib import Path
import re
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, cast

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr, standard_transformations


@dataclass
class SympyOdes:
    t: sp.Symbol
    species: List[sp.Symbol]
    params: List[sp.Symbol]
    odes: List[sp.Expr]
    species_names: List[str]
    param_names: List[str]
    source_path: str


_NAME_ARRAY_PATTERNS = [
    r"(?:const\s+char\s*\*|static\s+const\s+char\s*\*)\s*\w*species\w*\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;",
    r"(?:char\s*\*|static\s+char\s*\*)\s*\w*species\w*\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;",
]
_PARAM_ARRAY_PATTERNS = [
    r"(?:const\s+char\s*\*|static\s+const\s+char\s*\*)\s*\w*param\w*\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;",
    r"(?:char\s*\*|static\s+char\s*\*)\s*\w*param\w*\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;",
]


def _export_modern_sympy_odes(
    model_or_path,
    out_dir: Optional[str],
    mex_suffix: str,
    keep_files: bool,
) -> SympyOdes:
    """Generate MEX source from the canonical C++ model and parse it."""
    from bionetgen.model import BioNetGenModel, load

    if isinstance(model_or_path, BioNetGenModel):
        model = model_or_path
    else:
        model = load(model_or_path)

    try:
        from bionetgen import _bionetgen_cpp as cpp
    except ImportError as exc:  # pragma: no cover - guarded by package setup
        raise ImportError("The compiled _bionetgen_cpp extension is required") from exc

    network = model.generate_network()
    if model.source_path:
        model_stem = Path(model.source_path).stem
    else:
        model_stem = model.name or "model"
    output_root = (
        Path(out_dir)
        if out_dir is not None
        else Path(tempfile.mkdtemp(prefix="pybng_sympy_"))
    )
    cleanup = out_dir is None and not keep_files
    output_root.mkdir(parents=True, exist_ok=True)
    output_name = model_stem
    if mex_suffix:
        output_name += f"_{mex_suffix}"
    output_path = output_root / f"{output_name}_mex.c"

    try:
        output_path.write_text(
            cpp.io.write_mex_string(model._model, network), encoding="utf-8"
        )
        return extract_odes_from_mexfile(str(output_path))
    finally:
        if cleanup:
            _safe_rmtree(str(output_root))


def export_sympy_odes(
    model_or_path,
    out_dir: Optional[str] = None,
    mex_suffix: str = "mex",
    keep_files: bool = False,
    timeout: Optional[int] = None,
    suppress: bool = True,
) -> SympyOdes:
    """Generate a mex C file with BNG2.pl and parse ODEs into SymPy.

    Returns a SympyOdes object containing SymPy symbols and expressions.
    """
    from bionetgen.modelapi.model import bngmodel

    if not isinstance(model_or_path, bngmodel):
        return _export_modern_sympy_odes(
            model_or_path,
            out_dir=out_dir,
            mex_suffix=mex_suffix,
            keep_files=keep_files,
        )

    from bionetgen.modelapi.runner import run

    if isinstance(model_or_path, bngmodel):
        model = model_or_path
    else:
        model = bngmodel(model_or_path)

    orig_actions_items = None
    orig_actions_before = None
    if hasattr(model, "actions"):
        orig_actions_items = list(getattr(model.actions, "items", []))
        orig_actions_before = list(getattr(model.actions, "before_model", []))

        model.actions.clear_actions()
        model.actions.before_model.clear()

        model.add_action("generate_network", {"overwrite": 1})
        if mex_suffix:
            # Action printing doesn't automatically quote strings; BNGL expects
            # suffix to be a quoted string literal.
            model.add_action("writeMexfile", {"suffix": f'"{mex_suffix}"'})
        else:
            model.add_action("writeMexfile", {})

    cleanup = False
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="pybng_sympy_")
        cleanup = not keep_files
    else:
        os.makedirs(out_dir, exist_ok=True)

    try:
        run(model, out=out_dir, timeout=timeout, suppress=suppress)
        mex_path = _find_mex_c_file(out_dir, mex_suffix=mex_suffix)
        return extract_odes_from_mexfile(mex_path)
    finally:
        if orig_actions_items is not None:
            model.actions.items = orig_actions_items
        if orig_actions_before is not None:
            model.actions.before_model = orig_actions_before
        if cleanup:
            _safe_rmtree(out_dir)


def extract_odes_from_mexfile(mex_c_path: str) -> SympyOdes:
    """Parse a writeMexfile C output and return SymPy ODE expressions."""
    with open(mex_c_path, "r") as f:
        text = f.read()

    # Common BioNetGen mex outputs (e.g. *_mex_cvode.c) express ODEs as
    # NV_Ith_S(Dspecies,i)=... inside calc_species_deriv, referencing
    # intermediate vectors (ratelaws/observables/expressions). Handle this
    # format first.
    if "calc_species_deriv" in text and "NV_Ith_S(Dspecies" in text:
        return _extract_odes_from_cvode_mex(text, mex_c_path)
    if "calc_species_deriv" in text and re.search(r"\bdydt\s*\[", text):
        return _extract_odes_from_cpp_mex(text, mex_c_path)

    species_names = _extract_name_array(text, _NAME_ARRAY_PATTERNS)
    param_names = _extract_name_array(text, _PARAM_ARRAY_PATTERNS)

    eq_map = _extract_ode_assignments(text)
    if not eq_map:
        raise ValueError(
            "No ODE assignments found in mex output. "
            "Expected patterns like NV_Ith_S(ydot,i)=... or ydot[i]=..."
        )

    max_idx = max(eq_map.keys())
    species_symbol_names, species_names = _build_symbol_names(
        species_names, max_idx + 1, prefix="s"
    )
    max_param_idx = _max_indexed_param(eq_map.values())
    param_expected = None
    if max_param_idx is not None:
        param_expected = max(max_param_idx + 1, len(param_names))
    param_symbol_names, param_names = _build_symbol_names(
        param_names, param_expected, prefix="p"
    )

    species_symbols = [sp.Symbol(name) for name in species_symbol_names]
    param_symbols = [sp.Symbol(name) for name in param_symbol_names]
    t = sp.Symbol("t")

    local_dict: Dict[str, object] = {s.name: s for s in species_symbols}
    local_dict.update({p.name: p for p in param_symbols})
    local_dict.update(
        {
            "Pow": sp.Pow,
            "Abs": sp.Abs,
            "Max": sp.Max,
            "Min": sp.Min,
            "exp": sp.exp,
            "log": sp.log,
            "sqrt": sp.sqrt,
            "pi": sp.pi,
        }
    )

    odes: List[sp.Expr] = [sp.Integer(0) for _ in range(max_idx + 1)]
    for idx, expr in eq_map.items():
        cleaned = _normalize_expr(expr)
        cleaned = _replace_indexed_symbols(
            cleaned, species_symbol_names, param_symbol_names
        )
        odes[idx] = parse_expr(
            cleaned, local_dict=local_dict, transformations=standard_transformations
        )

    return SympyOdes(
        t=t,
        species=species_symbols,
        params=param_symbols,
        odes=odes,
        species_names=species_names,
        param_names=param_names,
        source_path=mex_c_path,
    )


def _extract_odes_from_cvode_mex(text: str, mex_c_path: str) -> SympyOdes:
    n_species = _extract_define_int(text, "__N_SPECIES__")
    n_params = _extract_define_int(text, "__N_PARAMETERS__")

    expr_map = _extract_nv_assignments(
        _extract_function_body(text, "calc_expressions"), "expressions"
    )
    obs_map = _extract_nv_assignments(
        _extract_function_body(text, "calc_observables"), "observables"
    )
    rate_map = _extract_nv_assignments(
        _extract_function_body(text, "calc_ratelaws"), "ratelaws"
    )
    deriv_map = _extract_nv_assignments(
        _extract_function_body(text, "calc_species_deriv"), "Dspecies"
    )
    if not deriv_map:
        raise ValueError(
            "No ODE assignments found in mex output. "
            "Expected NV_Ith_S(Dspecies,i)=... in calc_species_deriv."
        )

    max_deriv_idx = max(deriv_map.keys())
    if n_species is None:
        n_species = max_deriv_idx + 1
    if n_params is None:
        max_param_idx = _max_bracket_index(text, "parameters")
        n_params = (max_param_idx + 1) if max_param_idx is not None else 0

    # No name arrays are typically included in *_mex_cvode.c outputs.
    species_symbol_names, species_names = _build_symbol_names([], n_species, prefix="s")
    param_symbol_names, param_names = _build_symbol_names([], n_params, prefix="p")

    species_symbols = [sp.Symbol(name) for name in species_symbol_names]
    param_symbols = [sp.Symbol(name) for name in param_symbol_names]
    t = sp.Symbol("t")

    # Intermediate vectors
    n_expr = (max(expr_map.keys()) + 1) if expr_map else 0
    n_obs = (max(obs_map.keys()) + 1) if obs_map else 0
    n_rate = (max(rate_map.keys()) + 1) if rate_map else 0

    expr_syms = [sp.Symbol(f"e{i}") for i in range(n_expr)]
    obs_syms = [sp.Symbol(f"o{i}") for i in range(n_obs)]
    rate_syms = [sp.Symbol(f"r{i}") for i in range(n_rate)]

    local_dict: Dict[str, object] = {s.name: s for s in species_symbols}
    local_dict.update({p.name: p for p in param_symbols})
    local_dict.update({e.name: e for e in expr_syms})
    local_dict.update({o.name: o for o in obs_syms})
    local_dict.update({r.name: r for r in rate_syms})
    local_dict.update(
        {
            "Pow": sp.Pow,
            "Abs": sp.Abs,
            "Max": sp.Max,
            "Min": sp.Min,
            "exp": sp.exp,
            "log": sp.log,
            "sqrt": sp.sqrt,
            "pi": sp.pi,
        }
    )

    def _parse_rhs(rhs: str) -> sp.Expr:
        # BioNetGen's writeMexfile can emit placeholder non-code text for
        # unsupported rate law types (e.g. "Sat"). Surface this as a clear
        # Python error instead of letting SymPy raise a SyntaxError.
        if "not yet supported by writeMexfile" in rhs:
            raise NotImplementedError(rhs)
        cleaned = _normalize_expr(rhs)
        cleaned = _replace_parameters_brackets(cleaned, param_symbol_names)
        cleaned = _replace_nv_ith_s(
            cleaned, species_symbol_names, expr_syms, obs_syms, rate_syms
        )
        return cast(
            sp.Expr,
            parse_expr(
                cleaned,
                local_dict=local_dict,
                transformations=standard_transformations,
            ),
        )

    # Build expressions with intra-expression substitution (expressions can depend on earlier entries)
    expr_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_expr)]
    for idx in sorted(expr_map.keys()):
        val = _parse_rhs(expr_map[idx])
        if idx > 0:
            val = val.subs(
                {expr_syms[j]: expr_exprs[j] for j in range(min(idx, len(expr_exprs)))}
            )
        expr_exprs[idx] = cast(sp.Expr, val)

    obs_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_obs)]
    expr_sub = {expr_syms[i]: expr_exprs[i] for i in range(n_expr)}
    for idx in sorted(obs_map.keys()):
        obs_exprs[idx] = cast(sp.Expr, _parse_rhs(obs_map[idx]).subs(expr_sub))

    rate_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_rate)]
    obs_sub = {obs_syms[i]: obs_exprs[i] for i in range(n_obs)}
    for idx in sorted(rate_map.keys()):
        rate_exprs[idx] = cast(
            sp.Expr,
            _parse_rhs(rate_map[idx]).subs(expr_sub).subs(obs_sub),
        )

    rate_sub = {rate_syms[i]: rate_exprs[i] for i in range(n_rate)}
    odes: List[sp.Expr] = [sp.Integer(0) for _ in range(n_species)]
    for idx in range(n_species):
        if idx in deriv_map:
            odes[idx] = cast(sp.Expr, _parse_rhs(deriv_map[idx]).subs(rate_sub))
        else:
            odes[idx] = sp.Integer(0)

    return SympyOdes(
        t=t,
        species=species_symbols,
        params=param_symbols,
        odes=odes,
        species_names=species_names,
        param_names=param_names,
        source_path=mex_c_path,
    )


def _extract_odes_from_cpp_mex(text: str, mex_c_path: str) -> SympyOdes:
    """Parse the standalone C++ MEX format emitted by BNG3's MexWriter."""
    n_species = _extract_define_int_any(text, "N_SPECIES")
    n_params = _extract_define_int_any(text, "N_PARAMETERS")
    n_expr = _extract_define_int_any(text, "N_EXPRESSIONS")
    n_obs = _extract_define_int_any(text, "N_OBSERVABLES")
    n_rate = _extract_define_int_any(text, "N_RATELAWS")

    expr_map = _extract_array_assignments(
        _extract_function_body(text, "calc_expressions"), "expressions"
    )
    obs_map = _extract_array_assignments(
        _extract_function_body(text, "calc_observables"), "observables"
    )
    rate_map = _extract_array_assignments(
        _extract_function_body(text, "calc_ratelaws"), "ratelaws"
    )
    deriv_map = _extract_array_assignments(
        _extract_function_body(text, "calc_species_deriv"), "dydt"
    )
    if not deriv_map:
        raise ValueError(
            "No ODE assignments found in BNG3 MEX output. "
            "Expected dydt[index] assignments in calc_species_deriv."
        )

    n_species = n_species or (max(deriv_map) + 1)
    n_params = n_params or _max_cpp_reference_index(text, "parameters")
    n_expr = n_expr or (max(expr_map) + 1 if expr_map else n_params)
    n_obs = n_obs or (max(obs_map) + 1 if obs_map else 0)
    n_rate = n_rate or (max(rate_map) + 1 if rate_map else 0)

    species_symbol_names, species_names = _build_symbol_names([], n_species, prefix="s")
    param_symbol_names, param_names = _build_symbol_names([], n_params, prefix="p")
    species_symbols = [sp.Symbol(name) for name in species_symbol_names]
    param_symbols = [sp.Symbol(name) for name in param_symbol_names]
    expr_syms = [sp.Symbol(f"e{i}") for i in range(n_expr)]
    obs_syms = [sp.Symbol(f"o{i}") for i in range(n_obs)]
    rate_syms = [sp.Symbol(f"r{i}") for i in range(n_rate)]
    t = sp.Symbol("t")

    local_dict: Dict[str, object] = {s.name: s for s in species_symbols}
    local_dict.update({p.name: p for p in param_symbols})
    local_dict.update({e.name: e for e in expr_syms})
    local_dict.update({o.name: o for o in obs_syms})
    local_dict.update({r.name: r for r in rate_syms})
    local_dict.update(
        {
            "Pow": sp.Pow,
            "Abs": sp.Abs,
            "Max": sp.Max,
            "Min": sp.Min,
            "exp": sp.exp,
            "log": sp.log,
            "sqrt": sp.sqrt,
            "pi": sp.pi,
        }
    )

    def parse_rhs(rhs: str) -> sp.Expr:
        cleaned = _normalize_expr(rhs)
        cleaned = _replace_cpp_array_symbols(
            cleaned,
            species_symbol_names,
            param_symbol_names,
            expr_syms,
            obs_syms,
            rate_syms,
        )
        return cast(
            sp.Expr,
            parse_expr(
                cleaned,
                local_dict=local_dict,
                transformations=standard_transformations,
            ),
        )

    expr_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_expr)]
    for idx in sorted(expr_map):
        expr_exprs[idx] = cast(
            sp.Expr,
            parse_rhs(expr_map[idx]).subs(
                {expr_syms[j]: expr_exprs[j] for j in range(idx)}
            ),
        )

    expr_sub = {expr_syms[i]: expr_exprs[i] for i in range(n_expr)}
    obs_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_obs)]
    for idx in sorted(obs_map):
        obs_exprs[idx] = cast(sp.Expr, parse_rhs(obs_map[idx]).subs(expr_sub))
    obs_sub = {obs_syms[i]: obs_exprs[i] for i in range(n_obs)}

    rate_exprs: List[sp.Expr] = [sp.Integer(0) for _ in range(n_rate)]
    for idx in sorted(rate_map):
        rate_exprs[idx] = cast(
            sp.Expr, parse_rhs(rate_map[idx]).subs(expr_sub).subs(obs_sub)
        )
    rate_sub = {rate_syms[i]: rate_exprs[i] for i in range(n_rate)}

    odes: List[sp.Expr] = [sp.Integer(0) for _ in range(n_species)]
    for idx in range(n_species):
        if idx in deriv_map:
            odes[idx] = cast(sp.Expr, parse_rhs(deriv_map[idx]).subs(rate_sub))

    return SympyOdes(
        t=t,
        species=species_symbols,
        params=param_symbols,
        odes=odes,
        species_names=species_names,
        param_names=param_names,
        source_path=mex_c_path,
    )


def _extract_define_int(text: str, define_name: str) -> Optional[int]:
    m = re.search(
        rf"^\s*#define\s+{re.escape(define_name)}\s+(\d+)\s*$", text, flags=re.M
    )
    if not m:
        return None
    return int(m.group(1))


def _extract_function_body(text: str, func_name: str) -> str:
    # Best-effort extraction; BioNetGen-generated mex code uses simple, non-nested bodies.
    m = re.search(
        rf"\b{re.escape(func_name)}\b\s*\([^)]*\)\s*\{{(.*?)^\}}\s*$",
        text,
        flags=re.S | re.M,
    )
    if not m:
        return ""
    return m.group(1)


def _extract_nv_assignments(body: str, lhs_var: str) -> Dict[int, str]:
    if not body:
        return {}
    eq_map: Dict[int, str] = {}
    pattern = rf"NV_Ith_S\s*\(\s*{re.escape(lhs_var)}\s*,\s*(\d+)\s*\)\s*=\s*(.*?);"
    for match in re.finditer(pattern, body, flags=re.S):
        idx = int(match.group(1))
        eq_map[idx] = match.group(2).strip()
    return eq_map


def _extract_array_assignments(body: str, lhs_var: str) -> Dict[int, str]:
    if not body:
        return {}
    eq_map: Dict[int, str] = {}
    pattern = rf"\b{re.escape(lhs_var)}\s*\[\s*(\d+)\s*\]\s*=\s*(.*?);"
    for match in re.finditer(pattern, body, flags=re.S):
        eq_map[int(match.group(1))] = match.group(2).strip()
    return eq_map


def _extract_define_int_any(text: str, define_name: str) -> Optional[int]:
    match = re.search(
        rf"^\s*#define\s+{re.escape(define_name)}\s+(\d+)\s*$",
        text,
        flags=re.M,
    )
    return int(match.group(1)) if match else None


def _max_cpp_reference_index(text: str, array_name: str) -> int:
    indices = [
        int(match.group(1))
        for match in re.finditer(rf"\b{re.escape(array_name)}\s*\[\s*(\d+)\s*\]", text)
    ]
    return max(indices, default=-1) + 1


def _replace_cpp_array_symbols(
    expr: str,
    species_names: List[str],
    param_names: List[str],
    expr_syms: List[sp.Symbol],
    obs_syms: List[sp.Symbol],
    rate_syms: List[sp.Symbol],
) -> str:
    def replace(match: re.Match[str]) -> str:
        array_name = match.group(1)
        idx = int(match.group(2))
        if array_name == "species":
            return species_names[idx] if idx < len(species_names) else f"s{idx}"
        if array_name == "parameters":
            return param_names[idx] if idx < len(param_names) else f"p{idx}"
        if array_name == "expressions":
            return expr_syms[idx].name if idx < len(expr_syms) else f"e{idx}"
        if array_name == "observables":
            return obs_syms[idx].name if idx < len(obs_syms) else f"o{idx}"
        if array_name == "ratelaws":
            return rate_syms[idx].name if idx < len(rate_syms) else f"r{idx}"
        return match.group(0)

    return re.sub(
        r"\b(species|parameters|expressions|observables|ratelaws)\s*\[\s*(\d+)\s*\]",
        replace,
        expr,
    )


def _replace_parameters_brackets(expr: str, param_names: List[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx >= len(param_names):
            return f"p{idx}"
        return param_names[idx]

    return re.sub(r"\bparameters\s*\[\s*(\d+)\s*\]", repl, expr)


def _replace_nv_ith_s(
    expr: str,
    species_symbol_names: List[str],
    expr_syms: List[sp.Symbol],
    obs_syms: List[sp.Symbol],
    rate_syms: List[sp.Symbol],
) -> str:
    def repl(match: re.Match[str]) -> str:
        var = match.group(1)
        idx = int(match.group(2))
        if var == "species":
            return (
                species_symbol_names[idx]
                if idx < len(species_symbol_names)
                else f"s{idx}"
            )
        if var == "expressions":
            return expr_syms[idx].name if idx < len(expr_syms) else f"e{idx}"
        if var == "observables":
            return obs_syms[idx].name if idx < len(obs_syms) else f"o{idx}"
        if var == "ratelaws":
            return rate_syms[idx].name if idx < len(rate_syms) else f"r{idx}"
        if var == "Dspecies":
            return f"ds{idx}"
        # Unknown NV_Ith_S target; leave it as-is
        return match.group(0)

    return re.sub(r"NV_Ith_S\s*\(\s*(\w+)\s*,\s*(\d+)\s*\)", repl, expr)


def _max_bracket_index(text: str, array_name: str) -> Optional[int]:
    max_idx: Optional[int] = None
    for m in re.finditer(rf"\b{re.escape(array_name)}\s*\[\s*(\d+)\s*\]", text):
        idx = int(m.group(1))
        max_idx = idx if max_idx is None else max(max_idx, idx)
    return max_idx


def _extract_name_array(text: str, patterns: List[str]) -> List[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if match:
            return re.findall(r"\"([^\"]+)\"", match.group(1))
    return []


def _extract_ode_assignments(text: str) -> Dict[int, str]:
    eq_map: Dict[int, str] = {}
    patterns = [
        r"NV_Ith_S\s*\(\s*ydot\s*,\s*(\d+)\s*\)\s*=\s*(.*?);",
        r"\b(?:ydot|dydt)\s*\[\s*(\d+)\s*\]\s*=\s*(.*?);",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.S):
            idx = int(match.group(1))
            expr = match.group(2).strip()
            eq_map[idx] = expr
        if eq_map:
            break
    return eq_map


def _normalize_expr(expr: str) -> str:
    expr = re.sub(r"\(\s*(?:realtype|double|float|int)\s*\)", "", expr)
    expr = re.sub(r"\bpow\s*\(", "Pow(", expr)
    expr = re.sub(r"\bfabs\s*\(", "Abs(", expr)
    expr = re.sub(r"\bfmax\s*\(", "Max(", expr)
    expr = re.sub(r"\bfmin\s*\(", "Min(", expr)
    expr = expr.replace("M_PI", "pi")
    return expr


def _replace_indexed_symbols(
    expr: str, species_names: List[str], param_names: List[str]
) -> str:
    def repl_species(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx >= len(species_names):
            return f"s{idx}"
        return species_names[idx]

    def repl_param(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx >= len(param_names):
            return f"p{idx}"
        return param_names[idx]

    expr = re.sub(r"NV_Ith_S\s*\(\s*y\s*,\s*(\d+)\s*\)", repl_species, expr)
    expr = re.sub(r"\by\s*\[\s*(\d+)\s*\]", repl_species, expr)
    expr = re.sub(r"\bparams\s*\[\s*(\d+)\s*\]", repl_param, expr)
    expr = re.sub(r"\bparam\s*\[\s*(\d+)\s*\]", repl_param, expr)
    expr = re.sub(r"\bp\s*\[\s*(\d+)\s*\]", repl_param, expr)
    return expr


def _build_symbol_names(
    names: List[str], expected_len: Optional[int], prefix: str
) -> Tuple[List[str], List[str]]:
    if expected_len is None:
        expected_len = len(names)

    cleaned: List[str] = []
    final_names: List[str] = list(names)
    seen = set()

    for idx in range(expected_len):
        raw = names[idx] if idx < len(names) else ""
        base = re.sub(r"[^0-9a-zA-Z_]", "_", raw)
        if not base:
            base = f"{prefix}{idx}"
        if base[0].isdigit():
            base = f"{prefix}_{base}"
        if base in seen:
            base = f"{base}_{idx}"
        cleaned.append(base)
        seen.add(base)

    if expected_len > len(final_names):
        for idx in range(len(final_names), expected_len):
            final_names.append(f"{prefix}{idx}")

    return cleaned, final_names


def _max_indexed_param(expressions) -> Optional[int]:
    max_idx = None
    for expr in expressions:
        for match in re.finditer(r"\b(?:params|param|p)\s*\[\s*(\d+)\s*\]", expr):
            idx = int(match.group(1))
            if max_idx is None or idx > max_idx:
                max_idx = idx
    return max_idx


def _find_mex_c_file(out_dir: str, mex_suffix: str) -> str:
    patterns = []
    if mex_suffix:
        patterns.extend(
            [
                f"*{mex_suffix}*.c",
                f"*{mex_suffix}*.cpp",
                f"*{mex_suffix}*.C",
            ]
        )
    patterns.extend(["*mex*.c", "*mex*.cpp", "*.c", "*.cpp"])

    for pattern in patterns:
        matches = glob.glob(os.path.join(out_dir, pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"Could not locate mex C output in {out_dir}. "
        "Expected a file like *_mex.c or with the provided suffix."
    )


def _safe_rmtree(path: str) -> None:
    try:
        import shutil

        shutil.rmtree(path)
    except Exception:
        pass
