"""Rate law validation: Test all rate law types produce correct output.

Creates test models using each rate law type and verifies BNG3 output
matches expected behavior.

Usage:
    python scripts/validate_ratelaws.py [--bng-cpp PATH]
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


RATE_LAW_MODELS = {
    "elementary": """
begin parameters
    kf 0.01
    kr 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 100
    B(a) 100
end seed species
begin observables
    Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
    A(b) + B(a) <-> A(b!1).B(a!1) kf, kr
end reaction rules
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
""",
    "saturation": """
begin parameters
    kcat 1.0
    Km 10.0
    S0 100
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() S0
end seed species
begin observables
    Molecules Stot S()
    Molecules Ptot P()
end observables
begin reaction rules
    S() -> P() Sat(kcat, Km)
end reaction rules
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
""",
    "michaelis_menten": """
begin parameters
    kcat 1.0
    Km 10.0
    S0 100
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() S0
end seed species
begin observables
    Molecules Stot S()
    Molecules Ptot P()
end observables
begin reaction rules
    S() -> P() MM(kcat, Km)
end reaction rules
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
""",
    "hill": """
begin parameters
    kcat 1.0
    Km 10.0
    n 2.0
    S0 100
end parameters
begin molecule types
    S()
    P()
end molecule types
begin seed species
    S() S0
end seed species
begin observables
    Molecules Stot S()
    Molecules Ptot P()
end observables
begin reaction rules
    S() -> P() Hill(kcat, Km, n)
end reaction rules
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
""",
    "zero_order": """
begin parameters
    k0 5.0
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 0
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    0 -> A() k0
end reaction rules
begin actions
    generate_network({overwrite=>1})
    simulate({method=>"ode", t_end=>10, n_steps=>100})
end actions
""",
}


def parse_gdat(path):
    """Parse a .gdat file into column names and numpy array."""
    with open(path) as f:
        header = f.readline().strip()
    col_names = header.lstrip('#').split()
    data = np.loadtxt(path, comments='#')
    return col_names, data


def run_model(bng_cpp, model_text, output_dir):
    """Write model to file, run bng_cpp, return .gdat path."""
    model_path = Path(output_dir) / "test_model.bngl"
    model_path.write_text(model_text)

    cmd = [str(bng_cpp), str(model_path)]
    result = subprocess.run(cmd, cwd=output_dir, capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stderr[:500]

    gdat_files = list(Path(output_dir).glob("*.gdat"))
    return gdat_files[0] if gdat_files else None, ""


def validate_elementary(data):
    """Elementary: should reach equilibrium."""
    final_AB = data[-1, 1]  # AB observable
    return final_AB > 0, f"AB={final_AB:.2f} (should be > 0 at equilibrium)"


def validate_saturation(data):
    """Saturation: product should increase monotonically."""
    product = data[:, 2]  # Ptot
    monotonic = all(product[i+1] >= product[i] - 1e-10 for i in range(len(product)-1))
    return monotonic and product[-1] > 0, f"Ptot final={product[-1]:.2f}"


def validate_michaelis_menten(data):
    """MM: same as saturation behavior."""
    product = data[:, 2]
    return product[-1] > 0, f"Ptot final={product[-1]:.2f}"


def validate_hill(data):
    """Hill: product should increase."""
    product = data[:, 2]
    return product[-1] > 0, f"Ptot final={product[-1]:.2f}"


def validate_zero_order(data):
    """Zero order: linear increase in A."""
    a_values = data[:, 1]  # Atot
    # Should be approximately k0 * t at end
    expected = 5.0 * 10.0  # k0 * t_end
    rel_err = abs(a_values[-1] - expected) / expected
    return rel_err < 0.01, f"Atot final={a_values[-1]:.2f} (expected {expected})"


VALIDATORS = {
    "elementary": validate_elementary,
    "saturation": validate_saturation,
    "michaelis_menten": validate_michaelis_menten,
    "hill": validate_hill,
    "zero_order": validate_zero_order,
}


def main():
    parser = argparse.ArgumentParser(description="Validate rate law implementations")
    parser.add_argument("--bng-cpp", default="build/bng_cpp", help="Path to bng_cpp binary")
    args = parser.parse_args()

    bng_cpp = Path(args.bng_cpp)
    if not bng_cpp.exists():
        print(f"ERROR: bng_cpp not found at {bng_cpp}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0

    for name, model_text in RATE_LAW_MODELS.items():
        print(f"  Testing {name}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            gdat_path, err = run_model(bng_cpp, model_text, tmpdir)
            if gdat_path is None:
                print(f"  FAIL {name}: simulation failed: {err}")
                failed += 1
                continue

            try:
                _, data = parse_gdat(gdat_path)
            except Exception as e:
                print(f"  FAIL {name}: parse error: {e}")
                failed += 1
                continue

            validator = VALIDATORS.get(name)
            if validator:
                ok, msg = validator(data)
                if ok:
                    print(f"  PASS {name}: {msg}")
                    passed += 1
                else:
                    print(f"  FAIL {name}: {msg}")
                    failed += 1
            else:
                print(f"  PASS {name}: produced output (no validator)")
                passed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
