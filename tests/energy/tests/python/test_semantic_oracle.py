from __future__ import annotations
import math
from pathlib import Path
import pytest

from scripts import energy_semantic_oracle as oracle


def test_conjunctive_literal_delta_g():
    terms = [
        {"energy": 1.0, "mask": 1},
        {"energy": 2.0, "mask": 2},
        {"energy": 4.0, "mask": 3},
    ]
    assert oracle.delta_g(0.5, 0, terms) == 0.5
    assert oracle.delta_g(0.5, 1, terms) == 1.5
    assert oracle.delta_g(0.5, 2, terms) == 2.5
    assert oracle.delta_g(0.5, 3, terms) == 7.5


def test_arrhenius_ratio_is_boltzmann_factor():
    dg = 3.2
    phi = 0.37
    rt = 2.478
    f = oracle.arrhenius(dg, phi, rt, True)
    r = oracle.arrhenius(dg, phi, rt, False)
    assert f / r == pytest.approx(math.exp(-dg / rt), rel=1e-12)


def test_zero_term_mask_is_invalid():
    with pytest.raises(ValueError):
        oracle.delta_g(0, 0, [{"energy": 1, "mask": 0}])


def test_enumeration_size_is_power_of_two():
    case = {
        "condition_count": 5,
        "base": 0,
        "terms": [{"energy": 1, "mask": 1}],
        "phi": 0.5,
        "RT": 1,
    }
    assert len(oracle.enumerate_plan(case)) == 32


def test_random_literal_enumeration_satisfies_forward_reverse_ratio():
    import random

    random.seed(123)
    for _ in range(2000):
        n = random.randint(1, 8)
        valid = (1 << n) - 1
        terms = [
            {"energy": random.uniform(-5, 5), "mask": random.randint(1, valid)}
            for _ in range(random.randint(1, 20))
        ]
        case = {
            "condition_count": n,
            "base": random.uniform(-2, 2),
            "terms": terms,
            "phi": random.random(),
            "RT": random.uniform(0.2, 5),
        }
        for row in oracle.enumerate_plan(case):
            assert row["forward_factor"] / row["reverse_factor"] == pytest.approx(
                math.exp(-row["delta_g"] / case["RT"]), rel=1e-12
            )
