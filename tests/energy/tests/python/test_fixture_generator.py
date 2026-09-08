from __future__ import annotations
from pathlib import Path
import pytest

from scripts import generate_boolean_context_fixture as gen


def test_generated_model_has_requested_number_of_energy_patterns():
    text = gen.generate(8)
    block = text.split("begin energy patterns", 1)[1].split("end energy patterns", 1)[0]
    lines = [x for x in block.splitlines() if x.strip()]
    assert len(lines) == 8
    assert "c7" in text and "C7" in text


def test_generator_rejects_unreasonable_sizes():
    with pytest.raises(ValueError):
        gen.generate(0)
    with pytest.raises(ValueError):
        gen.generate(41)


def test_generated_context_sizes_cover_scaling_gate_points():
    for n in (1, 6, 8, 12):
        text = gen.generate(n)
        block = text.split("begin energy patterns", 1)[1].split(
            "end energy patterns", 1
        )[0]
        assert len([x for x in block.splitlines() if x.strip()]) == n
