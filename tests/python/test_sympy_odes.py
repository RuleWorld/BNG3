import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")
pytest.importorskip("sympy")

from bionetgen.modelapi.sympy_odes import SympyOdes, export_sympy_odes


def test_export_sympy_odes_uses_modern_cpp_writer(tmp_path):
    bngl = tmp_path / "sympy_decay.bngl"
    bngl.write_text(
        """
begin model
begin parameters
    k 0.1
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() 10
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
"""
    )
    output_dir = tmp_path / "mex"

    result = export_sympy_odes(
        str(bngl), out_dir=str(output_dir), mex_suffix="sym", keep_files=True
    )

    assert isinstance(result, SympyOdes)
    assert result.source_path == str(output_dir / "sympy_decay_sym_mex.c")
    assert len(result.species) == 1
    assert len(result.params) == 1
    assert len(result.odes) == 1
    assert str(result.odes[0]) == "-p0*s0"
