from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_every_cpp_contract_is_referenced_by_cmake_or_is_standalone_fuzzer():
    cmake = (ROOT / "cmake" / "energy_tests.cmake").read_text()
    cpp = {p.name for p in (ROOT / "tests" / "cpp").glob("*.cpp")}
    exempt = {"standalone_energy_delta_plan_smoke.cpp"}
    missing = sorted(name for name in cpp - exempt if name not in cmake)
    assert not missing, missing


def test_cmake_does_not_reference_missing_cpp_files():
    cmake = (ROOT / "cmake" / "energy_tests.cmake").read_text()
    names = set(re.findall(r"\b(?:test|future|fuzz)_[A-Za-z0-9_]+\.cpp\b", cmake))
    missing = sorted(
        name for name in names if not (ROOT / "tests" / "cpp" / name).exists()
    )
    assert not missing, missing
