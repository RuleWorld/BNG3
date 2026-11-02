"""Compare public CRN topology, rates, and rule labels with pinned BNG2 .net output."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import bionetgen

from tests.validation.strict import require_oracle
from tests.validation.test_export_formats import _locked_bng2_script

_SOURCE = """\
begin model
begin parameters
    k1 1
    k2 2
    k3 3
end parameters
begin molecule types
    A()
    B()
    C()
end molecule types
begin seed species
    A() 10
end seed species
begin functions
    doubled() = 2*k2
end functions
begin reaction rules
    make: A() -> B() + B() k1
    convert: B() -> C() doubled()
    return: C() -> A() k3
end reaction rules
end model
"""


def _network_rows(path: Path):
    section = None
    species = []
    reactions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("begin "):
            section = stripped.removeprefix("begin ")
            continue
        if stripped.startswith("end "):
            section = None
            continue
        if section == "species" and stripped and not stripped.startswith("#"):
            fields = stripped.split()
            species.append(fields[1])
        elif section == "reactions" and stripped and not stripped.startswith("#"):
            body, _, comment = stripped.partition("#")
            fields = body.split()
            assert len(fields) >= 4, f"unexpected BNG2 .net reaction row: {line!r}"
            reactants = (
                ()
                if fields[1] == "0"
                else tuple(int(value) - 1 for value in fields[1].split(","))
            )
            products = (
                ()
                if fields[2] == "0"
                else tuple(int(value) - 1 for value in fields[2].split(","))
            )
            reactions.append(
                {
                    "reactants": reactants,
                    "products": products,
                    "rate": fields[3],
                    "rule": comment.strip(),
                }
            )
    return species, reactions


def test_installed_crn_fields_match_pinned_bng2_network(tmp_path):
    bng2 = _locked_bng2_script()
    require_oracle(
        bng2 is not None,
        "pinned BNG2 checkout is unavailable or does not match provenance lock",
    )
    assert bng2 is not None
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(perl is not None, "Perl is required to run pinned BNG2")
    assert perl is not None

    model_path = tmp_path / "functional_cycle.bngl"
    model_path.write_text(_SOURCE + "\ngenerate_network({overwrite=>1})\n")
    oracle_dir = tmp_path / "bng2"
    oracle_dir.mkdir()
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    run = subprocess.run(
        [
            perl,
            str(bng2),
            "--outdir",
            str(oracle_dir),
            "--check",
            "--netgen",
            str(model_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, f"pinned BNG2 failed:\n{run.stdout}\n{run.stderr}"
    bng2_species, bng2_reactions = _network_rows(oracle_dir / "functional_cycle.net")

    model = bionetgen.load(model_path)
    crn = model.to_crn()
    assert [item["name"] for item in crn["species"]] == bng2_species

    bng2_complexes = []
    for reaction in bng2_reactions:
        for side in (reaction["reactants"], reaction["products"]):
            if side not in bng2_complexes:
                bng2_complexes.append(side)
    assert [tuple(item["species"]) for item in crn["complexes"]] == bng2_complexes

    bng2_matrix = [[0] * len(bng2_reactions) for _ in bng2_species]
    for column, reaction in enumerate(bng2_reactions):
        for species in reaction["reactants"]:
            bng2_matrix[species][column] -= 1
        for species in reaction["products"]:
            bng2_matrix[species][column] += 1
    assert crn["stoichiometric_matrix"] == bng2_matrix

    bng3_reactions = crn["reactions"]
    assert len(bng3_reactions) == len(bng2_reactions)
    for bng3_reaction, bng2_reaction in zip(bng3_reactions, bng2_reactions):
        assert tuple(bng3_reaction["reactants"]) == bng2_reaction["reactants"]
        assert tuple(bng3_reaction["products"]) == bng2_reaction["products"]
        assert bng3_reaction["rate_law"]["rule_name"] == bng2_reaction["rule"]
        bng3_rate = re.sub(r"\s+", "", bng3_reaction["rate_law"]["expression"])
        bng2_rate = re.sub(r"\s+", "", bng2_reaction["rate"])
        assert bng3_rate.replace("()", "") == bng2_rate
