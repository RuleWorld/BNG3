"""Base XMLObj.resolve_ratelaw parity with pinned PyBioNetGen 28bf351a.

Expected values are read from the pinned upstream implementation, not from
BNG3's subclass overrides.
"""

from bionetgen.modelapi.xmlparsers import XMLObj


def _rate(kind, **payload):
    node = {"@type": kind}
    node.update(payload)
    return node


def test_elementary_rate_law():
    node = _rate("Ele", ListOfRateConstants={"RateConstant": {"@value": "0.1"}})
    assert XMLObj.resolve_ratelaw(None, node) == "0.1"


def test_function_rate_law():
    assert XMLObj.resolve_ratelaw(None, _rate("Function", **{"@name": "f"})) == "f"


def test_named_rate_laws_use_comma_separated_arguments():
    args = [{"@value": "1"}, {"@value": "2"}]
    for kind in ("MM", "Sat", "Hill", "Arrhenius"):
        node = _rate(kind, ListOfRateConstants={"RateConstant": args})
        assert XMLObj.resolve_ratelaw(None, node) == f"{kind}(1,2)"
    single = _rate("MM", ListOfRateConstants={"RateConstant": {"@value": "3"}})
    assert XMLObj.resolve_ratelaw(None, single) == "MM(3)"


def test_unknown_rate_law_type_is_diagnostic_not_an_exception():
    assert XMLObj.resolve_ratelaw(None, _rate("Unknown")) == ""
