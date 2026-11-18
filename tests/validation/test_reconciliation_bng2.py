"""Differential checks for source changes in the accepted BNG2 range."""

import hashlib
import re
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from tests.validation import compare, oracle_perl, runner
from tests.validation.strict import require_oracle

ROOT = Path(__file__).resolve().parents[2]


def _pinned_model_text(name, record_property):
    upstream_perl = oracle_perl._bng2_path()
    require_oracle(upstream_perl is not None, "set BNG2_PERL to the pinned BNG2.pl")
    assert upstream_perl is not None
    relative_source = Path("bng2/Models2") / f"{name}.bngl"
    upstream_root = upstream_perl.parent.parent
    source_bytes = (upstream_root / relative_source).read_bytes()
    pinned_bytes = subprocess.check_output(
        ["git", "-C", str(upstream_root), "cat-file", "blob", f"HEAD:{relative_source}"]
    )
    assert source_bytes == pinned_bytes, relative_source
    record_property("upstream_fixture", str(relative_source))
    record_property("fixture_sha256", hashlib.sha256(source_bytes).hexdigest())
    model_text = source_bytes.decode("utf-8").replace("\r\n", "\n")
    model, end, _ = model_text.partition("end model")
    assert end
    # This check compares the generated network. The retained interpreter
    # does not carry upstream release metadata for the version() directive.
    if name == "energy_example1":
        assert model.count('version("2.2.4")\n') == 1
        model = model.replace('version("2.2.4")\n', "", 1)
    text = model + end + "\ngenerate_network({overwrite=>1})\n"
    return upstream_perl, text


def _run_perl_network(perl, name, text, work):
    work.mkdir()
    staged = work / f"{name}.bngl"
    staged.write_text(text, encoding="utf-8")
    result = subprocess.run(
        ["perl", str(perl), str(staged)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"{perl}: {result.stdout}\n{result.stderr}"
    return work / f"{name}.net"


@pytest.mark.parametrize(
    "name",
    ["Motivating_example_cBNGL", "energy_example1"],
    ids=["invalid-compartment-product", "shared-arrhenius-normalization"],
)
def test_retained_perl_network_matches_upstream_fix(name, tmp_path, record_property):
    """Reproduce upstream #339 and #340 through BNG3's retained Perl route."""
    upstream_perl, text = _pinned_model_text(name, record_property)
    ref = compare.parse_net(
        _run_perl_network(upstream_perl, name, text, tmp_path / "source")
    )
    retained = compare.parse_net(
        _run_perl_network(
            ROOT / "legacy/perl/BNG2.pl", name, text, tmp_path / "retained"
        )
    )
    assert ref is not None and retained is not None
    diff = compare.compare_net(ref, retained)
    assert diff.ok, diff.summary()


@pytest.mark.parametrize(
    ("product", "species_count", "reaction_count"),
    [("A(x).B(y)", 1, 0), ("A(x) + B(y)", 3, 1)],
    ids=["invalid-dotted-product", "valid-split-product"],
)
def test_native_bridge_bond_break_respects_product_patterns(
    bng_cpp, tmp_path, product, species_count, reaction_count
):
    """Pinned native BNG2 rejects a bridge break specified as one product."""
    model = tmp_path / "bridge.bngl"
    model.write_text(
        f"""begin model
begin molecule types
    A(x)
    B(y)
end molecule types
begin seed species
    A(x!1).B(y!1) 1
end seed species
begin reaction rules
    A(x!1).B(y!1) -> {product} 1
end reaction rules
end model
generate_network({{overwrite=>1}})
""",
        encoding="utf-8",
    )
    net, _, error = runner.run_cli_path(bng_cpp, model, tmp_path / "native")
    assert net is not None, error
    graph = compare.parse_net(net)
    assert graph is not None
    assert graph.n_species == species_count
    assert graph.n_reactions == reaction_count


def test_native_arrhenius_normalization_separates_net_rounding(
    bng_cpp, tmp_path, record_property
):
    name = "energy_example1"
    upstream_perl, text = _pinned_model_text(name, record_property)
    ref = _run_perl_network(upstream_perl, name, text, tmp_path / "source")
    model = tmp_path / f"{name}.bngl"
    model.write_text(text, encoding="utf-8")
    subject, _, error = runner.run_cli_path(bng_cpp, model, tmp_path / "native")
    assert subject is not None, error

    # The fixture gives vol_CP = 4/3 * PI * rad_cell^3. Test the two
    # documented NET spellings of its count-rate conversion independently.
    volume = Decimal(4) / 3 * Decimal("3.1415927") * Decimal("1e-4") ** 3
    factor = 1 / (Decimal("6.0221e23") * volume)
    line = re.compile(
        r"(?m)^(\s*\d+\s+\d+(?:,\d+)*\s+\d+(?:,\d+)*\s+)"
        r"([\d.]+e[+-]\d+)\*([A-Za-z_]\w*\s+#.*unit_conversion=.*)$"
    )
    normalized = []
    for path, significant in ((ref, 8), (subject, 9)):
        serialized = path.read_text(encoding="utf-8")
        coefficients = [Decimal(match[2]) for match in line.finditer(serialized)]
        assert len(coefficients) == 12
        assert coefficients == [Decimal(format(factor, f".{significant}g"))] * 12
        out = path.with_name("unscaled.net")
        out.write_text(line.sub(r"\1\3", serialized), encoding="utf-8")
        parsed = compare.parse_net(out)
        assert parsed is not None
        normalized.append(parsed)
    diff = compare.compare_net(*normalized)
    assert diff.ok, diff.summary()
    assert normalized[0].n_reactions == 24
