"""Comparators for differential validation.

One module, every comparison. Consolidates and corrects the logic that was
scattered across scripts/validate_*.py.

Key correctness fix over the old scripts: the .net comparator keys reactions by
their *species strings*, not by species indices. Two networks that are identical
up to species ordering must compare equal; an extra or unmerged reaction must
compare unequal. This is what detects the over-count (blbr +26, cBNGL +2):
the test network carries reaction tuples that the reference (Perl) merged.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip())


# --------------------------------------------------------------------------- #
# .net parsing
# --------------------------------------------------------------------------- #

@dataclass
class Network:
    """A parsed reaction network, comparison-ready."""

    # species index (as written) -> canonical species string
    species_by_index: dict[int, str]
    # multiset of (sorted reactant strings, sorted product strings, rate-key)
    reaction_multiset: Counter
    # parameters/functions blocks: generated-name -> defining expression string.
    # Used to resolve a reaction's rate reference to a value (rate_mode="value"),
    # so two networks that differ only in auto-generated rate-parameter NAMES
    # (rateLaw4 vs _rateLaw4 vs __R1_local1) still compare equal — while a real
    # difference in the rate VALUE/expression is still caught.
    rate_defs: dict[str, str] = field(default_factory=dict)
    # The reaction list before rate resolution, so we can re-key under a
    # different rate_mode without re-reading the file.
    _raw: list = field(default_factory=list)

    @property
    def n_species(self) -> int:
        return len(self.species_by_index)

    @property
    def n_reactions(self) -> int:
        return sum(self.reaction_multiset.values())


# --------------------------------------------------------------------------- #
# Rate resolution: make auto-generated rate-parameter NAMES irrelevant while
# still comparing rate VALUES/expressions. See _resolve_rate.
# --------------------------------------------------------------------------- #
import math

_SAFE_NAMES = {
    "ln": math.log,
    "log": math.log10,
    "log10": math.log10,
    "exp": math.exp,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "pi": math.pi,
    "e": math.e,
}


def _resolve_rate(token: str, rate_defs: dict[str, str], rate_mode: str) -> str:
    """Turn a reaction's 4th-field rate token into a comparison key.

    rate_mode="string"  -> the token verbatim (old behavior; byte-identical names).
    rate_mode="value"   -> resolve the token through the parameters/functions
                           table. If it constant-folds to a number, the key is
                           that number (so 0.5, k_synthC*2, and 1.0 all compare
                           equal when they evaluate equally). If it depends on
                           observables/time (a true function rate), the key is the
                           canonical expression with parameter names substituted —
                           a structural compare that still catches a different
                           expression but ignores the generated parameter name.
    """
    tok = _norm(token)
    if rate_mode == "string":
        return tok

    # Resolve complex top-level expressions (e.g. "2*rateLaw4" or "rateLaw1*2")
    # by evaluating them as expressions directly rather than just single symbol names.
    val, expr = _eval_expr(tok, rate_defs, set())
    if val is not None:
        return repr(round(val, 12))
    # Non-constant (references observables/time): compare the substituted,
    # canonicalized expression rather than the generated name.
    return f"expr:{_canon_expr(expr)}"


# Tokenizer for simple rate arithmetic: numbers, identifiers, operators, parens.
_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*(?:[eE][+-]?\d+)?|[()+\-*/^,]|\S")


def _eval_symbol(name: str, defs: dict[str, str], seen: set[str]):
    """Resolve a symbol to (value|None, substituted_expression_string).

    Returns a float value when the symbol constant-folds; otherwise None and the
    fully name-substituted expression string (for structural comparison).
    """
    if name in seen:  # cycle guard
        return None, name
    if name not in defs:
        # A bare number, a built-in (Sat/MM/Hill...), or an observable/time:
        try:
            return float(name), name
        except ValueError:
            return None, name
    seen = seen | {name}
    return _eval_expr(defs[name], defs, seen)


def _eval_expr(expr: str, defs: dict[str, str], seen: set[str]):
    """Evaluate a rate expression. (value|None, substituted_expr_string)."""
    toks = _TOKEN.findall(expr)
    # Substitute identifiers (that are defined parameters) for the structural form.
    sub_parts = []
    constant = True
    for t in toks:
        if re.match(r"^[A-Za-z_]\w*$", t):
            if t in _SAFE_NAMES:
                sub_parts.append(t)
            else:
                v, sub = _eval_symbol(t, defs, seen)
                if v is None:
                    constant = False
                    sub_parts.append(sub)
                else:
                    sub_parts.append(repr(v))
        else:
            sub_parts.append(t)
    sub_expr = "".join(sub_parts)

    if not constant:
        return None, sub_expr
    # All leaves are numeric or safe math functions — safely evaluate the arithmetic.
    try:
        val = _safe_arith(sub_expr)
        return val, sub_expr
    except Exception:
        return None, sub_expr


def _safe_arith(expr: str) -> float:
    """Evaluate a pure-numeric arithmetic expression with safe math functions."""
    e = expr.replace("^", "**")
    e = re.sub(r"\bln\b", "log", e)
    
    # Check that all alphabetical tokens are allowed math functions
    for word in re.findall(r"\b[A-Za-z_]\w*\b", e):
        if word not in _SAFE_NAMES and word not in ("log", "log10"):
            raise ValueError(f"unknown function or symbol {word!r}")
            
    ns = {
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "abs": abs,
        "pi": math.pi,
        "e": math.e,
    }
    # Only approved functions — safe to eval in an empty namespace.
    return float(eval(e, {"__builtins__": {}}, ns))


def _canon_expr(expr: str) -> str:
    """Whitespace/format-insensitive canonical form for a rate expression."""
    return re.sub(r"\s+", "", expr)


def split_species(s: str) -> list[str]:
    """Split a species string into a list of molecules separated by '.' (outside parens)."""
    parts = []
    curr = []
    depth = 0
    for char in s:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "." and depth == 0:
            parts.append("".join(curr))
            curr = []
            continue
        curr.append(char)
    if curr:
        parts.append("".join(curr))
    return parts


def renumber_bonds(s: str) -> str:
    """Renumber integer bond indices (!1, !2...) in order of left-to-right appearance."""
    bonds = re.findall(r"!(\d+)", s)
    if not bonds:
        return s
    mapping = {}
    next_id = 1
    for b in bonds:
        if b not in mapping:
            mapping[b] = str(next_id)
            next_id += 1
    return re.sub(r"!(\d+)", lambda m: "!" + mapping[m.group(1)], s)


def split_sites(mol: str) -> tuple[str, list[str]]:
    """Parse a molecule string 'Name(s1,s2,...)' into (name, [site_tokens]).

    Returns (mol, []) for molecules without parentheses.
    Each site token is a string like 'a', 'a~p', 'a!1', 'a~p!1', 'a!+'.
    """
    paren = mol.find("(")
    if paren == -1 or not mol.endswith(")"):
        return mol, []
    name = mol[:paren]
    inner = mol[paren + 1 : -1]
    # Split inner by commas (sites are flat — no nested parens in BNGL site lists)
    sites = [t.strip() for t in inner.split(",")] if inner else []
    return name, sites


def normalize_molecule(mol: str) -> str:
    """Return a form of mol with sites sorted lexicographically.

    Bond indices (!N) are first replaced with a placeholder (!) so that the
    sort key is topology-invariant. This is used only for grouping; the actual
    molecule string passed to permutation search retains original bond indices.
    """
    name, sites = split_sites(mol)
    if not sites:
        return mol
    # Replace bond indices with placeholder for stable sort key
    norm_sites = sorted(re.sub(r"!\d+", "!", st) for st in sites)
    return name + "(" + ",".join(norm_sites) + ")"


def _mol_site_orderings(mol: str) -> list[str]:
    """Generate all orderings of the site list within a single molecule string.

    Returns a list of molecule strings with every permutation of sites, each
    already using the original bond indices (renumbering happens later over the
    full species string).
    """
    import itertools
    name, sites = split_sites(mol)
    if len(sites) <= 1:
        return [mol]
    perms = list(itertools.permutations(sites))
    return [name + "(" + ",".join(p) + ")" for p in perms]


def canonicalize_species(s: str) -> str:
    """Canonicalize a BNGL species string to a graph-isomorphism-invariant form.

    Invariant to molecule order, bond index numbering, and site ordering within
    each molecule. Uses a BFS traversal from each possible root molecule to
    produce traversal-order bond renumbering, then picks the lex-min result.

    This correctly handles symmetric structures like blbr 5L+5R rings where
    WL coloring alone cannot distinguish molecule positions.
    """
    import itertools
    from collections import defaultdict, deque

    mols = split_species(s)
    n = len(mols)

    if n == 1:
        # Normalize site order for single-molecule species
        name, sites = split_sites(mols[0])
        if len(sites) <= 1:
            return mols[0]
        sorted_sites = sorted(sites, key=lambda st: (re.sub(r"!\d+", "", st), "!" in st))
        return name + "(" + ",".join(sorted_sites) + ")"

    # --- Parse each molecule ---
    parsed: list[tuple[str, list[tuple[str, int | None]]]] = []
    for mol in mols:
        name, sites = split_sites(mol)
        parsed_sites: list[tuple[str, int | None]] = []
        for st in sites:
            m = re.match(r"^([^!~]*)(?:~[^!]*)?(?:!(\d+|[+?]))?$", st)
            if m:
                site_name = m.group(1) or ""
                bond_raw = m.group(2)
                if bond_raw is None:
                    bond_idx: int | None = None
                elif bond_raw in ("+", "?"):
                    bond_idx = -1
                else:
                    bond_idx = int(bond_raw)
            else:
                site_name = re.sub(r"!.*", "", st)
                bond_idx = None
            parsed_sites.append((site_name, bond_idx))
        parsed.append((name, parsed_sites))

    # --- Build bond adjacency (molecule-level) ---
    bond_to_mols: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for mi, (_, psites) in enumerate(parsed):
        for si, (_, bidx) in enumerate(psites):
            if bidx is not None and bidx > 0:
                bond_to_mols[bidx].append((mi, si))

    # mol_bonds: mol_idx -> list of (neighbor_mol_idx, my_site_idx, their_site_idx, bond_idx)
    mol_bonds: list[list[tuple[int, int, int, int]]] = [[] for _ in range(n)]
    for bidx, eps in bond_to_mols.items():
        if len(eps) == 2:
            (mi1, si1), (mi2, si2) = eps
            mol_bonds[mi1].append((mi2, si1, si2, bidx))
            mol_bonds[mi2].append((mi1, si2, si1, bidx))

    # Pre-compute neighbor degree (connectivity) for canonical BFS ordering
    # This is bond-count independent: uses site names and free-site count
    def _mol_sig(mi: int) -> tuple:
        """Canonical signature of molecule mi for BFS ordering."""
        name, psites = parsed[mi]
        free_sites = sorted(sn for sn, bidx in psites if bidx is None)
        bonded_count = sum(1 for _, bidx in psites if bidx is not None and bidx > 0)
        return (name, bonded_count, tuple(free_sites))

    mol_sigs = [_mol_sig(i) for i in range(n)]

    # Sort each adjacency list by (neighbor_sig, my_site_name, their_site_name)
    # This is fully independent of original bond indices
    for mi, bl in enumerate(mol_bonds):
        bl.sort(key=lambda t: (mol_sigs[t[0]], parsed[mi][1][t[1]][0], parsed[t[0]][1][t[2]][0]))


    def _serialize_from_root(root: int) -> str:
        """BFS from `root`, serialize in BFS order with bond renumbering."""
        visited_order: list[int] = []
        queue: deque[int] = deque([root])
        visited: set[int] = {root}
        while queue:
            mi = queue.popleft()
            visited_order.append(mi)
            for (neighbor, _, _, _) in mol_bonds[mi]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        # Append disconnected molecules (safe for single-complex species)
        for mi in range(n):
            if mi not in visited:
                visited_order.append(mi)

        # Renumber bonds in BFS traversal order (left-to-right through the order list)
        bond_map: dict[int, int] = {}
        next_bond = [1]

        def _get_new_bond(old_bidx: int) -> str:
            if old_bidx <= 0:
                return "!+" if old_bidx == -1 else ""
            if old_bidx not in bond_map:
                bond_map[old_bidx] = next_bond[0]
                next_bond[0] += 1
            return f"!{bond_map[old_bidx]}"

        # Pass 1: assign new bond indices by scanning each molecule's sites
        # in original (parsed) order — this gives a stable numbering independent
        # of which molecule was encoded first in the source string.
        for mi in visited_order:
            _, psites = parsed[mi]
            for _, bidx in psites:
                if bidx is not None and bidx > 0 and bidx not in bond_map:
                    bond_map[bidx] = next_bond[0]
                    next_bond[0] += 1

        # Pass 2: serialize with sites sorted by (name, new_bond_idx or +inf if free)
        mol_strs = []
        for mi in visited_order:
            name, psites = parsed[mi]

            def _site_sort_key(item: tuple[str, int | None]) -> tuple:
                sn, bidx = item
                if bidx is None:
                    return (sn, False, float("inf"))
                elif bidx <= 0:
                    return (sn, True, float("inf"))
                else:
                    return (sn, True, bond_map[bidx])

            sorted_psites = sorted(psites, key=_site_sort_key)
            site_strs = []
            for sn, bidx in sorted_psites:
                if bidx is None:
                    site_strs.append(sn)
                elif bidx <= 0:
                    site_strs.append(sn + "!+")
                else:
                    site_strs.append(sn + f"!{bond_map[bidx]}")
            mol_strs.append(name + "(" + ",".join(site_strs) + ")")
        return ".".join(mol_strs)


    # Try BFS from every molecule as root; pick the lex-min serialization
    best: str | None = None
    for root in range(n):
        candidate = _serialize_from_root(root)
        if best is None or candidate < best:
            best = candidate
    return best



def parse_net(path: str | Path, *, rate_mode: str = "value") -> Network | None:
    """Parse a BNG .net file into a comparison-ready Network.

    Species block:     <idx> <species_string> <conc> [labels]
    Reaction block:    <idx> <r1,r2,...> <p1,p2,...> <rate> [annotations]
    Parameters block:  <idx> <name> <expression>   (or <name> <expression>)

    rate_mode (default "value") controls how the reaction rate field is keyed;
    see _resolve_rate. "value" makes auto-generated rate-parameter NAMES
    irrelevant while still comparing rate VALUES/expressions.
    """
    path = Path(path)
    if not path.exists():
        return None

    species: dict[int, str] = {}
    raw_reactions: list[tuple[list[int], list[int], str]] = []
    rate_defs: dict[str, str] = {}
    section = None

    for line in path.read_text().splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("begin "):
            section = stripped[len("begin "):].strip()
            continue
        if stripped.startswith("end "):
            section = None
            continue

        if section == "species":
            parts = _norm(stripped).split(" ")
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0])
            except ValueError:
                continue
            species[idx] = canonicalize_species(parts[1])

        elif section == "reactions":
            parts = _norm(stripped).split(" ")
            if len(parts) < 4:
                continue
            try:
                reactants = [int(x) for x in parts[1].split(",") if x and x != "0"]
                products = [int(x) for x in parts[2].split(",") if x and x != "0"]
            except ValueError:
                continue
            rate = parts[3]
            raw_reactions.append((reactants, products, rate))

        elif section in ("parameters", "functions"):
            parts = _norm(stripped).split(" ")
            # Forms seen across BNG2/BNG3: "<idx> <name> <expr...>" or
            # "<name> <expr...>" or "<name>=<expr>".
            if "=" in stripped and len(parts) >= 1 and "=" in parts[0]:
                name, _, expr = stripped.partition("=")
                rate_defs[_norm(name)] = _norm(expr)
                continue
            if len(parts) >= 3 and parts[0].isdigit():
                rate_defs[parts[1]] = " ".join(parts[2:])
            elif len(parts) >= 2:
                rate_defs[parts[0]] = " ".join(parts[1:])

    if not species and not raw_reactions:
        return None

    net = Network(
        species_by_index=species,
        reaction_multiset=Counter(),
        rate_defs=rate_defs,
        _raw=raw_reactions,
    )
    _rekey(net, rate_mode)
    return net


def _rekey(net: Network, rate_mode: str) -> None:
    """(Re)build reaction_multiset from net._raw under the given rate_mode."""
    multiset: Counter = Counter()
    for reactants, products, rate in net._raw:
        try:
            r_strs = tuple(sorted(net.species_by_index[i] for i in reactants))
            p_strs = tuple(sorted(net.species_by_index[i] for i in products))
        except KeyError:
            r_strs = tuple(f"?{i}" for i in sorted(reactants))
            p_strs = tuple(f"?{i}" for i in sorted(products))
        rate_key = _resolve_rate(rate, net.rate_defs, rate_mode)
        multiset[(r_strs, p_strs, rate_key)] += 1
    net.reaction_multiset = multiset


@dataclass
class NetDiff:
    ok: bool
    n_species_ref: int
    n_species_test: int
    n_reactions_ref: int
    n_reactions_test: int
    species_only_ref: set[str]
    species_only_test: set[str]
    reactions_only_ref: list
    reactions_only_test: list

    def summary(self) -> str:
        lines = [
            f"species:   ref={self.n_species_ref} test={self.n_species_test}",
            f"reactions: ref={self.n_reactions_ref} test={self.n_reactions_test} "
            f"(delta={self.n_reactions_test - self.n_reactions_ref:+d})",
        ]
        if self.species_only_ref:
            lines.append(f"  species only in ref ({len(self.species_only_ref)}): "
                         + ", ".join(sorted(self.species_only_ref)[:5]))
        if self.species_only_test:
            lines.append(f"  species only in test ({len(self.species_only_test)}): "
                         + ", ".join(sorted(self.species_only_test)[:5]))
        if self.reactions_only_test:
            lines.append(f"  reactions only in test ({len(self.reactions_only_test)}) "
                         "— candidates for the over-count / failed merge:")
            for r, p, rate in self.reactions_only_test[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        if self.reactions_only_ref:
            lines.append(f"  reactions only in ref ({len(self.reactions_only_ref)}):")
            for r, p, rate in self.reactions_only_ref[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        return "\n".join(lines)


def set_rate_mode(net: Network, rate_mode: str) -> Network:
    """Re-key an already-parsed Network under a different rate_mode, in place."""
    _rekey(net, rate_mode)
    return net


def compare_net(ref: Network, test: Network, *, compare_rates: bool = True) -> NetDiff:
    """Set-compare two networks by species string and reaction tuple.

    Reactions are keyed by (reactant species strings, product species strings,
    rate-key). The rate-key was produced at parse time according to parse_net's
    rate_mode (default "value"): auto-generated rate-parameter NAMES are resolved
    to their VALUE/expression, so rateLaw4 vs _rateLaw4 vs __R1_local1 do not
    cause spurious mismatches, while a genuine difference in rate value/expression
    still does. To compare byte-identical names instead, parse with
    rate_mode="string".

    compare_rates=False additionally drops the rate-key entirely, comparing pure
    topology + stoichiometry. The over-count (blbr/cBNGL) is detectable even in
    this mode, since it is a difference in reaction COUNT, not rate.
    """
    species_ref = set(ref.species_by_index.values())
    species_test = set(test.species_by_index.values())

    if compare_rates:
        rxn_ref = ref.reaction_multiset
        rxn_test = test.reaction_multiset
    else:
        rxn_ref = Counter((r, p) for (r, p, _), n in ref.reaction_multiset.items()
                          for _ in range(n))
        rxn_test = Counter((r, p) for (r, p, _), n in test.reaction_multiset.items()
                           for _ in range(n))

    only_ref = rxn_ref - rxn_test
    only_test = rxn_test - rxn_ref

    def _explode(counter):
        out = []
        for key, n in counter.items():
            r, p = key[0], key[1]
            rate = key[2] if len(key) > 2 else ""
            out.extend([(list(r), list(p), rate)] * n)
        return out

    ok = (species_ref == species_test) and (not only_ref) and (not only_test)
    return NetDiff(
        ok=ok,
        n_species_ref=ref.n_species,
        n_species_test=test.n_species,
        n_reactions_ref=ref.n_reactions,
        n_reactions_test=test.n_reactions,
        species_only_ref=species_ref - species_test,
        species_only_test=species_test - species_ref,
        reactions_only_ref=_explode(only_ref),
        reactions_only_test=_explode(only_test),
    )


# --------------------------------------------------------------------------- #
# .gdat / trajectory parsing
# --------------------------------------------------------------------------- #

def parse_gdat(path: str | Path) -> tuple[np.ndarray, list[str]] | tuple[None, None]:
    """Parse a .gdat/.cdat file into (data, columns). First column is time."""
    path = Path(path)
    if not path.exists():
        return None, None
    lines = path.read_text().splitlines()
    if not lines:
        return None, None
    header = lines[0].strip().lstrip("#").strip()
    columns = header.split()
    rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([float(x) for x in line.split()])
    if not rows:
        return None, None
    return np.asarray(rows, dtype=float), columns


@dataclass
class TrajDiff:
    ok: bool
    max_rel_err: float
    max_rel_col: str
    l2_rel_err: float
    note: str = ""

    def summary(self) -> str:
        s = (f"max rel err = {self.max_rel_err:.3e} at '{self.max_rel_col}', "
             f"L2 rel err = {self.l2_rel_err:.3e}")
        return s if not self.note else f"{s} ({self.note})"


def compare_trajectories(
    ref: np.ndarray,
    ref_cols: list[str],
    test: np.ndarray,
    test_cols: list[str],
    *,
    rtol: float = 1e-6,
    atol: float = 1e-12,
) -> TrajDiff:
    """Compare two trajectories column-by-column on shared observables.

    Aligns on the common time grid (intersection of time points, exact match).
    Relative error uses max(|ref|, atol) in the denominator so near-zero
    observables don't blow up the metric.
    """
    common = [c for c in ref_cols if c in test_cols and c.lower() != "time"]
    if not common:
        return TrajDiff(False, np.inf, "", np.inf, "no shared observable columns")

    rt = ref[:, ref_cols.index("time")] if "time" in ref_cols else ref[:, 0]
    tt = test[:, test_cols.index("time")] if "time" in test_cols else test[:, 0]

    # Align on shared time points (tolerant match).
    ridx, tidx = _align_times(rt, tt)
    if len(ridx) < 2:
        return TrajDiff(False, np.inf, "", np.inf,
                        f"insufficient shared time points (ref={len(rt)}, test={len(tt)})")

    worst = 0.0
    worst_col = ""
    sq_sum = 0.0
    n = 0
    for c in common:
        rv = ref[ridx, ref_cols.index(c)]
        tv = test[tidx, test_cols.index(c)]
        denom = np.maximum(np.abs(rv), atol)
        rel = np.abs(tv - rv) / denom
        cmax = float(np.max(rel))
        if cmax > worst:
            worst, worst_col = cmax, c
        sq_sum += float(np.sum(rel ** 2))
        n += rel.size

    l2 = float(np.sqrt(sq_sum / max(n, 1)))
    ok = worst <= rtol
    return TrajDiff(ok=ok, max_rel_err=worst, max_rel_col=worst_col, l2_rel_err=l2)


def _align_times(a: np.ndarray, b: np.ndarray, tol: float = 1e-9):
    """Return index arrays into a and b for time points present in both."""
    ai, bi = [], []
    j = 0
    for i, ta in enumerate(a):
        while j < len(b) and b[j] < ta - tol:
            j += 1
        if j < len(b) and abs(b[j] - ta) <= tol + tol * abs(ta):
            ai.append(i)
            bi.append(j)
            j += 1
    return np.asarray(ai, dtype=int), np.asarray(bi, dtype=int)


# --------------------------------------------------------------------------- #
# Stochastic ensemble comparison (SSA / PLA / PSA / NF)
# --------------------------------------------------------------------------- #

@dataclass
class EnsembleDiff:
    ok: bool
    n_violations: int
    n_points_checked: int
    worst_z: float
    worst_col: str

    def summary(self) -> str:
        return (f"ensemble: {self.n_violations}/{self.n_points_checked} points outside "
                f"mean +/- 3 SE; worst |z|={self.worst_z:.2f} at '{self.worst_col}'")


def compare_stochastic(
    ref_runs: list[tuple[np.ndarray, list[str]]],
    test_runs: list[tuple[np.ndarray, list[str]]],
    *,
    n_sigma: float = 3.0,
    max_violation_frac: float = 0.02,
) -> EnsembleDiff:
    """Distributional comparison of two stochastic ensembles.

    For each shared observable at each shared time point, check that the test
    ensemble mean lies within ref_mean +/- n_sigma * SE(ref). Pass if the
    fraction of violating points is <= max_violation_frac (allows for the few
    tail points expected at 3 sigma over many checks).
    """
    rmean, rse, rcols, rt = _ensemble_stats(ref_runs)
    tmean, _, tcols, tt = _ensemble_stats(test_runs)
    if rmean is None or tmean is None:
        return EnsembleDiff(False, 0, 0, np.inf, "")

    common = [c for c in rcols if c in tcols and c.lower() != "time"]
    ridx, tidx = _align_times(rt, tt)
    if not common or len(ridx) < 2:
        return EnsembleDiff(False, 0, 0, np.inf, "")

    violations = 0
    checked = 0
    worst_z = 0.0
    worst_col = ""
    for c in common:
        rm = rmean[ridx, rcols.index(c)]
        rs = rse[ridx, rcols.index(c)]
        tm = tmean[tidx, tcols.index(c)]
        se = np.maximum(rs, 1e-12)
        z = np.abs(tm - rm) / se
        cz = float(np.max(z))
        if cz > worst_z:
            worst_z, worst_col = cz, c
        violations += int(np.sum(z > n_sigma))
        checked += z.size

    frac = violations / max(checked, 1)
    return EnsembleDiff(
        ok=frac <= max_violation_frac,
        n_violations=violations,
        n_points_checked=checked,
        worst_z=worst_z,
        worst_col=worst_col,
    )


def _ensemble_stats(runs: list[tuple[np.ndarray, list[str]]]):
    if not runs:
        return None, None, None, None
    cols = runs[0][1]
    time = runs[0][0][:, cols.index("time")] if "time" in cols else runs[0][0][:, 0]
    stack = np.stack([r[0] for r in runs], axis=0)  # (n_runs, n_t, n_col)
    mean = stack.mean(axis=0)
    se = stack.std(axis=0, ddof=1) / np.sqrt(stack.shape[0]) if stack.shape[0] > 1 else np.zeros_like(mean)
    return mean, se, cols, time


# --------------------------------------------------------------------------- #
# Export format checks
# --------------------------------------------------------------------------- #

def check_xml_wellformed(path: str | Path) -> tuple[bool, str]:
    import xml.etree.ElementTree as ET
    try:
        ET.parse(str(path))
        return True, "well-formed"
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"


def check_sbml(path: str | Path) -> tuple[bool, str]:
    """Validate SBML with libsbml if available, else fall back to well-formed."""
    try:
        import libsbml  # type: ignore
    except ImportError:
        ok, msg = check_xml_wellformed(path)
        return ok, f"{msg} (libsbml absent; well-formedness only)"
    doc = libsbml.readSBML(str(path))
    n_err = doc.getNumErrors()
    serious = sum(
        1 for i in range(n_err)
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    )
    if serious:
        return False, f"{serious} SBML error(s); first: {doc.getError(0).getMessage()}"
    return True, f"valid SBML ({n_err} non-fatal notices)"
