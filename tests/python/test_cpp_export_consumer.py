"""The writeCPPfile export must compile against the pinned SUNDIALS and run.

Regression: the generated header used SUNDIALS v2 includes (``cvode_dense.h``,
``CVDense``, two-argument ``CVodeCreate``) and left ``return_status``
uninitialized, so it could not be built with BNG3's pinned SUNDIALS v7 and
reported a garbage status even when built with shims.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import pytest
from _extdep import require_extension

require_extension()
import bionetgen

ROOT = Path(__file__).resolve().parents[2]
MODEL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeCPPfile({overwrite=>1})
"""

HARNESS = """#include "m_cvode.h"
#include <future>
#include <iostream>
int main() {
    vector<double> tp; tp.push_back(0.0); tp.push_back(0.5); tp.push_back(1.0);
    vector<double> si; si.push_back(10.0);
    vector<double> pa; pa.push_back(0.1);
    auto first = std::async(std::launch::async, simulate, tp, si, pa);
    auto second = std::async(std::launch::async, simulate, tp, si, pa);
    const Result r = first.get();
    const Result other = second.get();
    if (r.status != 0 || other.status != 0 || r.observables != other.observables) {
        return 2;
    }
    std::cout.precision(12);
    std::cout << r.observables[0][2] << "\\n";
    return 0;
}
"""


@pytest.mark.parametrize(
    "options", ["stiff=>1,sparse=>0", "stiff=>1,sparse=>1", "stiff=>0"]
)
def test_exported_cpp_compiles_and_matches_analytic_law(tmp_path, options):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL.replace("writeCPPfile({", f"writeCPPfile({{{options},"))
    bionetgen.load(str(source)).execute()

    header = tmp_path / "m_cvode.h"
    assert header.is_file()
    build = ROOT / "build" / "_deps" / "sundials-build"
    include = ROOT / "build" / "_deps" / "sundials-src" / "include"
    gpp = shutil.which("g++")
    libs = [
        build / "src/cvode/libsundials_cvode.a",
        build / "src/nvector/serial/libsundials_nvecserial.a",
        build / "src/sunnonlinsol/fixedpoint/libsundials_sunnonlinsolfixedpoint.a",
        build / "src/sunlinsol/dense/libsundials_sunlinsoldense.a",
        build / "src/sunlinsol/spgmr/libsundials_sunlinsolspgmr.a",
        build / "src/sunmatrix/dense/libsundials_sunmatrixdense.a",
        build / "src/sundials/libsundials_core.a",
    ]
    if (
        gpp is None
        or not (build / "include").is_dir()
        or not all(lib.is_file() for lib in libs)
    ):
        pytest.skip("g++ or pinned SUNDIALS build tree is unavailable")

    (tmp_path / "harness.cpp").write_text(HARNESS)
    binary = tmp_path / "harness"
    compile_result = subprocess.run(
        [
            gpp,
            "-std=c++17",
            "-pthread",
            "-I.",
            f"-I{include}",
            f"-I{build / 'include'}",
            "harness.cpp",
            *[str(lib) for lib in libs],
            "-lm",
            "-o",
            str(binary),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        [str(binary)], cwd=tmp_path, capture_output=True, text=True
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert float(run_result.stdout.strip()) == pytest.approx(
        10 * math.exp(-0.1), rel=1e-5
    )
