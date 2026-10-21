"""The engine and the network it exports carry the same rate factors.

The engine and the network writer compute the same two factors for a
reaction: the *statistical factor* of identical reactants and the
*compartment-volume conversion*.  Canonical Perl BNG2 2.9.3 writes both as a
numeric prefix on the rate law, for every rate law type
(``RateLaw::toString`` in ``RateLaw.pm``), so its own network for
``@cell:A() + @cell:A() -> @cell:D() Sat(kcat,K)`` in a 100-unit volume
reads::

    1 1,1 2 0.005*Sat kcat K #_R1 unit_conversion=1/100.0

0.5 is the statistical factor of the two identical reactants and 0.01 is the
volume conversion.  This engine's own network writer emits the same prefix,
so the engine has to apply the same two factors; otherwise it disagrees
with the network it exports.

The check below evaluates the *exported network's own rate string* with
canonical BioNetGen's semantics and compares it with the engine's compiled
rate coefficient.  The built-in semantics are canonical BioNetGen's
standalone network runner (``bng2/Network3/src/network.cpp``, the
``SATURATION``, ``HILL`` and ``MICHAELIS_MENTEN`` cases and
``Util::mm_free_substrate``), so the comparison is with the oracle's
reading of the network rather than with this engine's own.

A ``TotalRate`` rule is the one rate law that takes neither factor in this
engine: it states the macroscopic total rate of the reaction, canonical
BioNetGen forces the statistical factor to one for it (``Rxn.pm``), and this
engine's network writer leaves both prefixes off for one.  Canonical
BioNetGen does write the volume conversion on a ``TotalRate`` rule, which
this engine deliberately does not: its Atomizer emits ``TotalRate`` rules
whose rate law is already the complete flux in the model's own units (it
divides by the compartment volume itself), so a second conversion would
halve the flux of every compartmented SBML model.  That difference from
canonical BioNetGen is recorded, not repaired here.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

bionetgen = pytest.importorskip("bionetgen")

COMPARTMENT = """begin compartments
  cell 3 100.0
end compartments
"""

#: The compartment size used for the conversion-active cases.
CELL_SIZE = 100.0

#: The volume conversion canonical BioNetGen writes for two reactants in one
#: volume: the anchor reactant is dropped and the remaining sizes are
#: multiplied into the denominator (Rxn.pm:100-197).
CELL_CONVERSION = 1.0 / CELL_SIZE


def _model_text(case, compartment: bool) -> str:
    prefix = "@cell:" if compartment else ""
    parameters = "\n".join(
        f"  {name} {value}" for name, value in case["parameters"].items()
    )
    molecule_types = "\n".join(f"  {name}" for name in case["molecules"])
    observables = "\n".join(
        f"  Molecules {name}_tot {prefix}{name}()" for name in case["molecules"]
    )
    seed = "\n".join(
        f"  {prefix}{name}() {amount}" for name, amount in case["seed"].items()
    )
    rule = case["rule"]
    if compartment:
        for name in case["molecules"]:
            rule = rule.replace(f"{name}()", f"@cell:{name}()")
    return f"""begin model
begin parameters
{parameters}
end parameters
{COMPARTMENT if compartment else ""}begin molecule types
{molecule_types}
end molecule types
begin observables
{observables}
end observables
begin seed species
{seed}
end seed species
begin reaction rules
  {rule}
end reaction rules
end model
"""


#: One entry per rate law type.  ``prefix`` is the numeric factor product
#: canonical BioNetGen writes in front of the rate law: the statistical
#: factor of identical reactants times the compartment-volume conversion.
RATE_LAW_CASES = [
    {
        "name": "elementary mass action",
        "rule": "A() + A() -> D() k",
        "parameters": {"k": 0.4},
        "molecules": ["A", "D"],
        "seed": {"A": 20.0, "D": 0.0},
        "prefix": {"none": 0.5, "cell": 0.5 * CELL_CONVERSION},
    },
    {
        "name": "saturation",
        "rule": "A() + A() -> D() Sat(kcat,K)",
        "parameters": {"kcat": 0.4, "K": 10.0},
        "molecules": ["A", "D"],
        "seed": {"A": 20.0, "D": 0.0},
        "prefix": {"none": 0.5, "cell": 0.5 * CELL_CONVERSION},
    },
    {
        "name": "hill",
        "rule": "A() + A() -> D() + E() Hill(Vmax,Kh,n)",
        "parameters": {"Vmax": 0.4, "Kh": 10.0, "n": 2.0},
        "molecules": ["A", "D", "E"],
        "seed": {"A": 20.0, "D": 0.0, "E": 0.0},
        "prefix": {"none": 0.5, "cell": 0.5 * CELL_CONVERSION},
    },
    {
        "name": "michaelis-menten",
        # Canonical BioNetGen refuses an MM law with identical reactants
        # (RateLaw.pm:1231-1249), so the distinct-reactant form is the one
        # with a canonical reading.
        "rule": "A() + B() -> D() + E() MM(kcat,Km)",
        "parameters": {"kcat": 0.4, "Km": 10.0},
        "molecules": ["A", "B", "D", "E"],
        "seed": {"A": 20.0, "B": 5.0, "D": 0.0, "E": 0.0},
        "prefix": {"none": 1.0, "cell": CELL_CONVERSION},
    },
    {
        "name": "total rate",
        "rule": "A() + A() -> D() k TotalRate",
        "parameters": {"k": 0.4},
        "molecules": ["A", "D"],
        "seed": {"A": 20.0, "D": 0.0},
        "prefix": {"none": 1.0, "cell": 1.0},
    },
]


def _build(case, compartment: bool):
    from bionetgen.model import _cpp

    model = bionetgen.BioNetGenModel(_cpp.parse_string(_model_text(case, compartment)))
    network = model.generate_network()
    return model, network


def _exported_reaction(model) -> tuple[list[int], str]:
    """The reactant species indices and the rate text of the exported network."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.net"
        model.write_net(str(path))
        body = path.read_text()
    reactions = body.split("begin reactions", 1)[1].split("end reactions", 1)[0]
    line = [entry for entry in reactions.splitlines() if entry.strip()][0].strip()
    fields = line.split(None, 3)
    reactants = [int(index) for index in fields[1].split(",") if index != "0"]
    rate_text = fields[3].split("#", 1)[0].strip()
    return reactants, rate_text


def _canonical_rate_coefficient(
    rate_text: str, parameters: dict[str, float], reactant_values: list[float]
) -> float:
    """Evaluate an exported network's rate string the way canonical BNG2 does.

    ``bng2/Network3/src/network.cpp`` reads the rate column of a .net file:
    a numeric prefix multiplies the rate law, and the built-in saturating
    laws carry the meaning of the ``SATURATION``, ``HILL`` and
    ``MICHAELIS_MENTEN`` cases of that file.  The continuous branch is the
    one a deterministic engine reads.
    """
    prefix = 1.0
    builtin = rate_text
    if "*" in rate_text:
        prefix_text, builtin = rate_text.split("*", 1)
        prefix = float(prefix_text)
        builtin = builtin.strip()
    tokens = builtin.split()
    name = tokens[0]
    args = tokens[1:]

    if name == "Sat":
        # rate = k0 * prod(R1..Rn) / prod(K1 + R1, ...), where the
        # denominator only covers the first len(args) - 1 reactants.
        rate = parameters[args[0]]
        denominator_count = len(args) - 1
        for index in range(denominator_count):
            value = reactant_values[index]
            rate *= value / (parameters[args[index + 1]] + value)
        for index in range(denominator_count, len(reactant_values)):
            rate *= reactant_values[index]
        return prefix * rate

    if name == "Hill":
        vmax, kh, exponent = (parameters[arg] for arg in args)
        substrate = reactant_values[0]
        power = substrate**exponent
        rate = vmax * power / (kh**exponent + power)
        for index in range(1, len(reactant_values)):
            rate *= reactant_values[index]
        return prefix * rate

    if name == "MM":
        kcat, km = (parameters[arg] for arg in args)
        substrate_total = reactant_values[0]
        enzyme_total = sum(reactant_values[1:])
        b = substrate_total - km - enzyme_total
        q = math.sqrt(b * b + 4.0 * substrate_total * km)
        free = 0.5 * (b + q) if b >= 0.0 else 2.0 * substrate_total * km / (q - b)
        return prefix * kcat * enzyme_total * free / (km + free)

    # An elementary rate law names a parameter; the engine multiplies the
    # reactant concentrations into the flux separately.
    return prefix * parameters[name]


def _engine_rate_coefficients(model, network, state):
    from bionetgen import _bionetgen_cpp as cpp

    return [
        float(value)
        for value in cpp._validation_ode_rate_coefficients(
            model._model, network, 0.0, state
        )
    ]


@pytest.mark.parametrize("compartment", [False, True], ids=["no_compartment", "cell"])
@pytest.mark.parametrize("case", RATE_LAW_CASES, ids=lambda case: case["name"])
def test_the_engine_agrees_with_the_exported_network(case, compartment):
    """The engine's rate coefficient must be the exported network's own rate."""
    model, network = _build(case, compartment)
    reactants, rate_text = _exported_reaction(model)

    prefix_text = rate_text.split("*", 1)[0] if "*" in rate_text else "1"
    assert float(prefix_text) == pytest.approx(
        case["prefix"]["cell" if compartment else "none"], rel=1e-9
    ), rate_text

    state = [
        float(case["seed"].get(name.split(":")[-1].rstrip("()"), 0.0))
        for name in network.species_names
    ]
    reactant_values = [state[index - 1] for index in reactants]
    expected = _canonical_rate_coefficient(
        rate_text, case["parameters"], reactant_values
    )
    coefficients = _engine_rate_coefficients(model, network, state)
    assert coefficients == pytest.approx([expected], rel=1e-12), (
        rate_text,
        coefficients,
        expected,
    )
