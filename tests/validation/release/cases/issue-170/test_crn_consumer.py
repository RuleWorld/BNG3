"""Independent CRNT consumer test for release-crn-consumer (#170).

This module contains an independent consumer modeling downstream tools like
crnt-lean. It consumes only the public serialized JSON artifact produced by
model.write_crn() and verifies fundamental CRNT algebraic and graph-theoretic
theorems with zero reliance on BNG3 internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

import numpy as np
import pytest

import bionetgen


class IndependentCRNConsumer:
    """Independent consumer of public CRN JSON artifacts with zero BNG3 internals."""

    def __init__(self, data: dict):
        self.version = data["version"]
        self.name = data.get("name", "")
        self.species = [s["name"] for s in data["species"]]
        self.complexes = [tuple(c["species"]) for c in data["complexes"]]
        self.reactions = data["reactions"]
        self.stoichiometric_matrix = np.array(
            data["stoichiometric_matrix"], dtype=np.int64
        )

    @classmethod
    def from_file(cls, path: Path) -> IndependentCRNConsumer:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @property
    def num_species(self) -> int:
        return len(self.species)

    @property
    def num_complexes(self) -> int:
        return len(self.complexes)

    @property
    def num_reactions(self) -> int:
        return len(self.reactions)

    def complex_species_matrix(self) -> np.ndarray:
        """Matrix Y (species x complexes) where Y[s, c] is the stoichiometric count."""
        Y = np.zeros((self.num_species, self.num_complexes), dtype=np.int64)
        for c_idx, sp_multiset in enumerate(self.complexes):
            for sp_idx in sp_multiset:
                Y[sp_idx, c_idx] += 1
        return Y

    def reaction_incidence_matrix(self) -> np.ndarray:
        """Matrix B (complexes x reactions) where B[c, r] is -1 for reactant, +1 for product."""
        B = np.zeros((self.num_complexes, self.num_reactions), dtype=np.int64)
        for r_idx, rxn in enumerate(self.reactions):
            r_c = rxn["reactant_complex"]
            p_c = rxn["product_complex"]
            B[r_c, r_idx] -= 1
            B[p_c, r_idx] += 1
        return B

    def linkage_classes(self) -> List[Set[int]]:
        """Connected components of the reaction graph on complexes."""
        adj: Dict[int, Set[int]] = {i: set() for i in range(self.num_complexes)}
        for rxn in self.reactions:
            r_c = rxn["reactant_complex"]
            p_c = rxn["product_complex"]
            adj[r_c].add(p_c)
            adj[p_c].add(r_c)

        visited: Set[int] = set()
        components: List[Set[int]] = []
        for i in range(self.num_complexes):
            if i not in visited:
                comp: Set[int] = set()
                queue = [i]
                visited.add(i)
                while queue:
                    curr = queue.pop()
                    comp.add(curr)
                    for nbr in adj[curr]:
                        if nbr not in visited:
                            visited.add(nbr)
                            queue.append(nbr)
                components.append(comp)
        return components

    def deficiency(self) -> int:
        """CRNT deficiency: delta = m - l - s."""
        m = self.num_complexes
        l = len(self.linkage_classes())
        s = int(np.linalg.matrix_rank(self.stoichiometric_matrix))
        delta = m - l - s
        assert delta >= 0, f"deficiency must be non-negative, got {delta}"
        return delta


def test_independent_consumer_verifies_crnt_theorems_on_binding(tmp_path):
    model_source = """
begin model
begin parameters
    kon 10.0
    koff 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 50
end seed species
begin reaction rules
    bind: A(b) + B(a) <-> A(b!1).B(a!1) kon, koff
end reaction rules
end model
"""
    model_path = tmp_path / "binding.bngl"
    model_path.write_text(model_source, encoding="utf-8")
    model = bionetgen.load(model_path)

    crn_file = tmp_path / "binding.crn.json"
    model.write_crn(crn_file)

    # Independent consumption: only loads JSON
    consumer = IndependentCRNConsumer.from_file(crn_file)
    assert consumer.num_species == 3
    assert consumer.num_complexes == 2
    assert consumer.num_reactions == 2

    # Theorem: N = Y * B
    Y = consumer.complex_species_matrix()
    B = consumer.reaction_incidence_matrix()
    N = consumer.stoichiometric_matrix
    np.testing.assert_array_equal(N, Y @ B)

    # Reversible binding is deficiency zero:
    # m = 2, l = 1, s = 1 -> delta = 0
    assert consumer.deficiency() == 0


def test_independent_consumer_verifies_crnt_theorems_on_multistep_cascade(tmp_path):
    model_source = """
begin model
begin parameters
    k1 1.0
    k2 2.0
    k3 3.0
end parameters
begin molecule types
    S0()
    S1()
    S2()
end molecule types
begin seed species
    S0() 100
end seed species
begin reaction rules
    r1: S0() -> S1() k1
    r2: S1() -> S2() k2
    r3: S2() -> S0() k3
end reaction rules
end model
"""
    model_path = tmp_path / "cascade.bngl"
    model_path.write_text(model_source, encoding="utf-8")
    model = bionetgen.load(model_path)

    crn_file = tmp_path / "cascade.crn.json"
    model.write_crn(crn_file)

    consumer = IndependentCRNConsumer.from_file(crn_file)
    assert consumer.num_species == 3
    assert consumer.num_complexes == 3
    assert consumer.num_reactions == 3

    # Theorem: N = Y * B
    Y = consumer.complex_species_matrix()
    B = consumer.reaction_incidence_matrix()
    N = consumer.stoichiometric_matrix
    np.testing.assert_array_equal(N, Y @ B)

    # Cycle S0 -> S1 -> S2 -> S0:
    # m = 3 complexes, l = 1 linkage class, s = rank(N) = 2 -> delta = 3 - 1 - 2 = 0
    assert consumer.deficiency() == 0
