"""Independent native count-law check for typed physical unimolecular rates."""

from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from tests.validation import compare, oracle_nfsim, runner
from tests.validation.strict import require_oracle

RUNS = 200
BASE_SEED = 1001
INITIAL_A = 100
RATE_PER_SECOND = 0.5
END_TIME = 1.0


def _physical_bng3_source() -> str:
    return """begin model
  setOption("units", "strict")
  begin units
    timeunits second
  end units
  begin parameters
    k = 0.5 [second^-1]
    Vc = 1 [fL]
  end parameters
  begin compartments
    cell 3 Vc [fL]
  end compartments
  begin molecule types
    A()
    B()
  end molecule types
  begin seed species
    A()@cell 100
    B()@cell 0
  end seed species
  begin observables
    Molecules A_count A()@cell
    Molecules B_count B()@cell
  end observables
  begin reaction rules
    convert: A()@cell -> B()@cell k
  end reaction rules
end model
"""


def _independent_bng2_source() -> str:
    # Same count-process law authored independently for BNG2. NFsim consumes
    # this BNG2-produced XML; no BNG3-generated XML is used as the oracle.
    return """begin model
begin parameters
    k 0.5
end parameters
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A()@cell 100
    B()@cell 0
end seed species
begin observables
    Molecules A_count A()@cell
    Molecules B_count B()@cell
end observables
begin reaction rules
    convert: A()@cell -> B()@cell k
end reaction rules
end model
generate_network({overwrite=>1})
writeXML()
"""


def _a_count(trajectory_data, columns):
    assert "A_count" in columns
    assert "B_count" in columns
    a = trajectory_data[-1, columns.index("A_count")]
    b = trajectory_data[-1, columns.index("B_count")]
    assert a + b == INITIAL_A
    return int(a)


def _assert_binomial_count_marginal(counts: list[int]) -> None:
    # At t=1, the source law is Binomial(100, exp(-k*t)). Compare its full
    # endpoint CDF with the 200 independent trajectories. DKW allocates
    # alpha=0.005 to each engine, so the two-engine family-wise false-rejection
    # bound is at most 0.01. Each replicate is treated as one bounded [0, 100]
    # observation; no independence between molecules within a trajectory is
    # assumed by the test.
    survival = math.exp(-RATE_PER_SECOND * END_TIME)
    probability = (1.0 - survival) ** INITIAL_A
    probabilities = [probability]
    for count in range(INITIAL_A):
        probability *= (INITIAL_A - count) / (count + 1) * survival / (1.0 - survival)
        probabilities.append(probability)
    expected_cdf = np.cumsum(probabilities)
    observed_cdf = np.cumsum(np.bincount(counts, minlength=INITIAL_A + 1) / RUNS)
    epsilon = math.sqrt(math.log(2.0 / 0.005) / (2.0 * RUNS))
    assert np.max(np.abs(observed_cdf - expected_cdf)) <= epsilon


@pytest.mark.nf
@pytest.mark.slow
def test_physical_unimolecular_rate_matches_independent_native_count_law(
    api, tmp_path, monkeypatch
):
    configured_bng2 = os.environ.get("BNG2_PERL")
    require_oracle(
        bool(configured_bng2) and Path(configured_bng2).is_file(),
        "independent BNG2 XML translation requires explicit BNG2_PERL",
    )
    require_oracle(oracle_nfsim.nfsim_available(), "set independent NFSIM_BIN")

    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    physical_source = tmp_path / "physical_unimolecular.bngl"
    physical_source.write_text(_physical_bng3_source(), encoding="utf-8")

    bng2_source = tmp_path / "independent_count_law.bngl"
    bng2_source.write_text(_independent_bng2_source(), encoding="utf-8")
    translated = subprocess.run(
        [os.environ.get("PERL", "perl"), configured_bng2, str(bng2_source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert translated.returncode == 0, translated.stdout + translated.stderr
    bng2_xml = tmp_path / "independent_count_law.xml"
    assert bng2_xml.is_file(), "independent BNG2 produced no XML"

    direct_counts = []
    native_counts = []
    for offset in range(RUNS):
        seed = BASE_SEED + offset
        result = api.load(str(physical_source)).simulate(
            method="nf", t_end=END_TIME, n_steps=1, seed=seed
        )
        trajectory = runner._result_to_trajectory(result)
        assert trajectory.construction_path == "direct"
        direct_counts.append(_a_count(trajectory.data, trajectory.columns))

        gdat, error = oracle_nfsim.run_nfsim(
            bng2_xml,
            tmp_path / f"native_{seed}",
            t_end=END_TIME,
            n_steps=1,
            seed=seed,
        )
        assert gdat is not None, error
        data, columns = compare.parse_gdat(gdat)
        assert data is not None and columns is not None
        native_counts.append(_a_count(data, columns))

    _assert_binomial_count_marginal(direct_counts)
    _assert_binomial_count_marginal(native_counts)
