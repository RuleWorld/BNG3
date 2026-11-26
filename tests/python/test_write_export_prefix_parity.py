"""Regression tests for BNG2 prefix/alias parity in write* and visualize actions."""

from __future__ import annotations

from pathlib import Path

import bionetgen._bionetgen_cpp as cpp

BASE_MODEL = """begin model
begin parameters
  kf 0.5
  kr 0.1
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules A_obs A()
  Molecules B_obs B()
end observables
begin reaction rules
  A() <-> B() kf, kr
end reaction rules
end model
generate_network({overwrite=>1})
"""


def _exec_bngl(tmp_path: Path, actions: str) -> Path:
    src = tmp_path / "probe.bngl"
    src.write_text(BASE_MODEL + actions, encoding="utf-8")
    model = cpp.parse_file(str(src))
    cpp.execute(model, str(src), False)
    return tmp_path


def test_write_export_actions_honor_prefix_and_suffix(tmp_path: Path):
    out = _exec_bngl(
        tmp_path,
        """
writeMfile({prefix=>"custom_m",suffix=>"s1"})
writeMfile_all({prefix=>"custom_mall",suffix=>"s2"})
writeCPPfile({prefix=>"custom_cpp",suffix=>"s1"})
writeCPYfile({prefix=>"custom_cpy",suffix=>"s1"})
writeMexfile({prefix=>"custom_mex",suffix=>"s1",max_err_test_fails=>5,max_conv_fails=>8,max_step=>0.1,stiff=>0,sparse=>1})
writeLatex({prefix=>"custom_tex",suffix=>"s1"})
writeLaTeXfile({prefix=>"custom_tex_alias",suffix=>"s2"})
writeMDL({prefix=>"custom_mdl",suffix=>"s1"})
writeSSC({prefix=>"custom_ssc",suffix=>"s1"})
writeSSCcfg({prefix=>"custom_cfg",suffix=>"s1"})
writeModel({prefix=>"custom_mod",suffix=>"s1"})
visualize({type=>"contactmap",prefix=>"custom_viz",suffix=>"s1"})
""",
    )
    expected = [
        "custom_m_s1.m",
        "custom_mall_s2.m",
        "initSpecies_custom_mall_s2.m",
        "bngModel_custom_mall_s2.m",
        "custom_cpp_s1_cvode.h",
        "custom_cpy_s1_pyode.py",
        "custom_mex_s1_mex.c",
        "custom_tex_s1.tex",
        "custom_tex_alias_s2.tex",
        "custom_mdl_s1.mdl",
        "custom_ssc_s1.rxn",
        "custom_cfg_s1.cfg",
        "custom_mod_s1.bngl",
        "custom_viz_contactmap_s1.gml",
    ]
    for name in expected:
        p = out / name
        assert p.is_file() and p.stat().st_size > 0, f"missing or empty: {name}"

    init_text = (out / "initSpecies_custom_mall_s2.m").read_text(encoding="utf-8")
    assert "initialize_species" in init_text
    assert "species_init(1) = 100" in init_text

    bng_model_text = (out / "bngModel_custom_mall_s2.m").read_text(encoding="utf-8")
    assert "classdef bngModel_custom_mall_s2 < bngModel" in bng_model_text
    assert "initSpecies_custom_mall_s2" in bng_model_text


def test_visualize_help_exits_without_writing_graph(tmp_path: Path):
    out = _exec_bngl(tmp_path, 'visualize({help=>1,prefix=>"nofile"})\n')
    assert not list(out.glob("nofile*"))
