#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts for BNGL language features.

Runs pinned ``BNG2.pl`` (external oracle) and ``bng_cpp`` (downstream consumer)
on self-contained BNGL probes covering verified ``bngl.*`` and ``builtin.tfun``
matrix rows (energy/Arrhenius, compartment transport, include/exclude filters,
fixed species, global/nested/local functions, Hill/MM/Sat/TotalRate,
MoveConnected, Molecules/Species observables & count predicates, population
maps, simulation protocols, and inline/file/counter/step ``tfun``), emitting
schema-v2 receipts ONLY where oracle and consumer outputs agree.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / "tests/validation/release/cases/issue-471"
for entry in (str(ROOT), str(CASE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import issue471_checks as checks  # noqa: E402
from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
    _verify_pinned_bng2,
    _version_line,
)

_GDAT = "release-oracle-gdat-numeric-v1"
_NET = "release-oracle-net-canonical-v1"
_HYBRID = "release-oracle-bngl-hybrid-v1"


@dataclass(frozen=True)
class FeatureProbeSpec:
    """Single pinned-BNG2 vs bng_cpp BNGL feature probe."""

    row_id: str
    comparator: str
    output_file: str
    bngl_text: str
    extra_files: tuple[tuple[str, str], ...] = field(default_factory=tuple)


FEATURE_PROBES: tuple[FeatureProbeSpec, ...] = (
    FeatureProbeSpec(
        "bngl.actions",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\nend model\n"
        "begin actions\n  generate_network({overwrite=>1})\n"
        '  simulate({method=>"ode",t_end=>2,n_steps=>4})\nend actions\n',
    ),
    FeatureProbeSpec(
        "bngl.arrhenius",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  phi 0.5\n  Ea0 1.0\n  Gf 2.0\nend parameters\n"
        "begin molecule types\n  A(s~u~p)\nend molecule types\n"
        "begin seed species\n  A(s~u) 10\nend seed species\n"
        "begin observables\n  Molecules Ap A(s~p)\nend observables\n"
        "begin energy patterns\n  A(s~p) Gf\nend energy patterns\n"
        "begin reaction rules\n  A(s~u) <-> A(s~p) Arrhenius(phi,Ea0)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.energy-patterns",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  phi 0.5\n  Ea0 1.0\n  Gf -1.5\nend parameters\n"
        "begin molecule types\n  A(s~u~p)\nend molecule types\n"
        "begin seed species\n  A(s~u) 100\nend seed species\n"
        "begin observables\n  Molecules Ap A(s~p)\nend observables\n"
        "begin energy patterns\n  A(s~p) Gf\nend energy patterns\n"
        "begin reaction rules\n  A(s~u) <-> A(s~p) Arrhenius(phi,Ea0)\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.compartment-transport",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin compartments\n  EC 3 10\n  PM 2 1 EC\n  CP 3 5 PM\nend compartments\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  @EC:A() 100\nend seed species\n"
        "begin observables\n  Molecules A_cp @CP:A()\nend observables\n"
        "begin reaction rules\n  @EC:A() -> @CP:A() k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.exclude-reactants",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A(b,c)\n  B(a)\n  C(a)\nend molecule types\n"
        "begin seed species\n  A(b,c) 10\n  A(b!1,c).B(a!1) 10\n  C(a) 10\nend seed species\n"
        "begin reaction rules\n  A(c) + C(a) -> A(c!1).C(a!1) k exclude_reactants(1,B)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.include-reactants",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A(b,c)\n  B(a)\n  C(a)\nend molecule types\n"
        "begin seed species\n  A(b,c) 10\n  A(b!1,c).B(a!1) 10\n  C(a) 10\nend seed species\n"
        "begin reaction rules\n  A(c) + C(a) -> A(c!1).C(a!1) k include_reactants(1,B)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.exclude-products",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A(b,c)\n  B(a)\n  C(a)\nend molecule types\n"
        "begin seed species\n  A(b!1,c!2).B(a!1).C(a!2) 10\n  A(b,c!2).C(a!2) 10\nend seed species\n"
        "begin reaction rules\n  A(c!1).C(a!1) -> A(c) + C(a) k exclude_products(1,B)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.include-products",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A(b,c)\n  B(a)\n  C(a)\nend molecule types\n"
        "begin seed species\n  A(b!1,c!2).B(a!1).C(a!2) 10\n  A(b,c!2).C(a!2) 10\nend seed species\n"
        "begin reaction rules\n  A(c!1).C(a!1) -> A(c) + C(a) k include_products(1,B)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.fixed-species",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  $A() 10\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin reaction rules\n  A() -> B() k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.global-functions",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  f1() = k * A_obs / (A_obs + 5)\nend functions\n"
        "begin reaction rules\n  0 -> A() f1()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.nested-function-calls",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  inner() = A_obs + 2\n  outer() = k * inner()\nend functions\n"
        "begin reaction rules\n  0 -> A() outer()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.local-functions",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  kp 0.5\n  km 0.1\n  ks 0.5\nend parameters\n"
        "begin molecule types\n  A(b,b)\n  B(a)\n  C()\nend molecule types\n"
        "begin seed species\n  A(b,b) 1\n  B(a) 2\n  C() 0\nend seed species\n"
        "begin observables\n  Molecules AB A(b!1).B(a!1)\n  Molecules Ctot C()\nend observables\n"
        "begin functions\n  f(x) = ks * (AB(x) + 1)\nend functions\n"
        "begin reaction rules\n  %x::A() -> %x::A() + C() f(x)\n"
        "  A(b) + B(a) <-> A(b!1).B(a!1) kp, km\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.local-molecule-scope",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  kp 0.5\n  km 0.1\n  ks 0.5\nend parameters\n"
        "begin molecule types\n  A(b,b)\n  B(a)\n  C()\nend molecule types\n"
        "begin seed species\n  A(b,b) 1\n  B(a) 2\n  C() 0\nend seed species\n"
        "begin observables\n  Molecules AB A(b!1).B(a!1)\n  Molecules Ctot C()\nend observables\n"
        "begin functions\n  f(x) = ks * AB(x)\nend functions\n"
        "begin reaction rules\n  A()%x -> A()%x + C() f(x)\n"
        "  A(b) + B(a) <-> A(b!1).B(a!1) kp, km\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.local-species-scope",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  kp 0.5\n  km 0.1\n  ks 0.5\nend parameters\n"
        "begin molecule types\n  A(b,b)\n  B(a)\n  C()\nend molecule types\n"
        "begin seed species\n  A(b,b) 1\n  B(a) 2\n  C() 0\nend seed species\n"
        "begin observables\n  Molecules AB A(b!1).B(a!1)\n  Molecules Ctot C()\nend observables\n"
        "begin functions\n  f(x) = ks * (AB(x) + 1)\nend functions\n"
        "begin reaction rules\n  %x::A() -> %x::A() + C() f(x)\n"
        "  A(b) + B(a) <-> A(b!1).B(a!1) kp, km\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.hill",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  Vmax 2.0\n  Kh 5.0\n  nh 2\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 10\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin reaction rules\n  A() -> B() Hill(Vmax,Kh,nh)\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.mm",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  kcat 2.0\n  Km 5.0\nend parameters\n"
        "begin molecule types\n  E()\n  S()\n  P()\nend molecule types\n"
        "begin seed species\n  E() 5\n  S() 20\n  P() 0\nend seed species\n"
        "begin observables\n  Molecules S_obs S()\n  Molecules P_obs P()\nend observables\n"
        "begin reaction rules\n  E() + S() -> E() + P() MM(kcat,Km)\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.sat",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  kcat 2.0\n  Km 5.0\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 10\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin reaction rules\n  A() -> B() Sat(kcat,Km)\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.totalrate",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 10\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin reaction rules\n  A() -> B() k TotalRate\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.moveconnected",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin compartments\n  EC 3 10\n  PM 2 1 EC\n  CP 3 5 PM\nend compartments\n"
        "begin molecule types\n  A(b)\n  B(a)\nend molecule types\n"
        "begin seed species\n  @EC:A(b!1).B(a!1) 10\nend seed species\n"
        "begin reaction rules\n  @EC:A() -> @CP:A() k MoveConnected\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.molecules-observables",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Molecules A_tot A()\n  Molecules A_dim A(b!1).A(b!1)\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.species-observables",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Species A_dim_sp A(b!1).A(b!1)\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.observables",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Molecules A_mol A()\n  Species A_sp A()\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.observable-coefficients",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Molecules A_mol A()\n  Species A_sp A(b!+)\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.observable-dependencies",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 10\n  B() 0\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin functions\n  f() = k * A_obs\nend functions\n"
        "begin reaction rules\n  0 -> B() f()\n  A() -> 0 0.2\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.parameter-dependencies",
        _NET,
        "probe.net",
        "begin model\nbegin parameters\n  p1 2.0\n  p2 p1 * 3.0\n  p3 p2 + 1.0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin reaction rules\n  A() -> 0 p3\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.species-count-equality",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Species A_exact2 A()==2\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.species-count-greater-than",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.2\nend parameters\n"
        "begin molecule types\n  A(b)\nend molecule types\n"
        "begin seed species\n  A(b) 10\nend seed species\n"
        "begin observables\n  Species A_gt1 A()>1\nend observables\n"
        "begin reaction rules\n  A(b) + A(b) -> A(b!1).A(b!1) k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.population-maps",
        _HYBRID,
        "probe_hpp.bngl",
        "begin model\nbegin parameters\n  k 0.5\n  k_pop 100\nend parameters\n"
        "begin molecule types\n  A()\n  B()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\n  Molecules B_obs B()\nend observables\n"
        "begin reaction rules\n  R1: A() -> B() k\nend reaction rules\n"
        "begin population maps\n  A() -> A_pop() k_pop\nend population maps\n"
        "end model\ngenerate_hybrid_model({overwrite=>1})\n",
    ),
    FeatureProbeSpec(
        "bngl.simulation-protocols",
        _GDAT,
        "probe_p2.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>1,n_steps=>2})\n'
        'setParameter("k",1.0)\nsimulate({method=>"ode",t_end=>2,n_steps=>2,suffix=>"p2"})\n',
    ),
    FeatureProbeSpec(
        "bngl.tfun-inline",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 1\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  tf() = tfun([0,1,2],[1,3,2],time)\nend functions\n"
        "begin reaction rules\n  0 -> A() tf()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "builtin.tfun",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 1\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  tf() = tfun([0,1,2],[1,3,2],time)\nend functions\n"
        "begin reaction rules\n  0 -> A() tf()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.tfun-file",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 1\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  tf() = tfun('tbl.tfun',time)\nend functions\n"
        "begin reaction rules\n  0 -> A() tf()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        extra_files=(("tbl.tfun", "# time val\n0 1\n1 3\n2 2\n"),),
    ),
    FeatureProbeSpec(
        "bngl.tfun-counter-expressions",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 1\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  tf() = tfun([0,5,10],[1,2,4],A_obs)\nend functions\n"
        "begin reaction rules\n  0 -> A() tf()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "bngl.tfun-interpolation-and-extrapolation",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 1\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin functions\n  tf() = tfun([0,1],[1,3],time,method=>'step')\nend functions\n"
        "begin reaction rules\n  0 -> A() tf()\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "action.saveParameters",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsaveParameters()\nsetParameter("k",1.5)\nresetParameters()\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "action.resetParameters",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsaveParameters()\nsetParameter("k",2.0)\nresetParameters()\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\n',
    ),
    FeatureProbeSpec(
        "action.quit",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>2,n_steps=>4})\nquit()\nsetParameter("k",99)\nsimulate({method=>"ode",t_end=>2,n_steps=>4,suffix=>"after"})\n',
    ),
    FeatureProbeSpec(
        "action.simulate_ssa",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nsimulate_ssa({t_end=>2,n_steps=>4,seed=>1})\n",
    ),
    FeatureProbeSpec(
        "action.simulate_psa",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nsimulate_psa({t_end=>2,n_steps=>4,seed=>1})\n",
    ),
    FeatureProbeSpec(
        "action.simulate_pla",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nsimulate_pla({t_end=>0,n_steps=>1,seed=>1})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.t_end",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>3,n_steps=>6})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.n_steps",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>5})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.atol",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,atol=>1e-8})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.rtol",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,rtol=>1e-6})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.bump",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,bump=>0.05})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.sparse",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,sparse=>1})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.steady_state",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,steady_state=>0})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.stochast",
        _GDAT,
        "probe_k_.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        "end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,stochast=>0})\n",
    ),
    FeatureProbeSpec(
        "action.LinearParameterSensitivity.suffix",
        _GDAT,
        "probe_k_s1.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nLinearParameterSensitivity({t_end=>2,n_steps=>4,suffix=>"s1"})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.continue",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ode",t_end=>1,n_steps=>2})\nsimulate({method=>"ode",t_end=>2,n_steps=>2,continue=>1})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.seed",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>7})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.max_sim_steps",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1,max_sim_steps=>1000})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.poplevel",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"psa",t_end=>2,n_steps=>4,seed=>1,poplevel=>5})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.update_interval",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"ssa",t_end=>2,n_steps=>4,seed=>1,update_interval=>10})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.pla_config",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"pla",t_end=>0,n_steps=>1,seed=>1,pla_config=>"fEuler|pre-neg:sb|eps=0.03"})\n',
    ),
    FeatureProbeSpec(
        "action.simulate.pla_output",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate({method=>"pla",t_end=>0,n_steps=>1,seed=>1,pla_output=>0})\n',
    ),
    FeatureProbeSpec(
        "action.simulate_ssa.method",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate_ssa({method=>"ssa",t_end=>2,n_steps=>4,seed=>1})\n',
    ),
    FeatureProbeSpec(
        "action.simulate_psa.method",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate_psa({method=>"psa",t_end=>2,n_steps=>4,seed=>1})\n',
    ),
    FeatureProbeSpec(
        "action.simulate_pla.method",
        _GDAT,
        "probe.gdat",
        "begin model\nbegin parameters\n  k 0.5\nend parameters\n"
        "begin molecule types\n  A()\nend molecule types\n"
        "begin seed species\n  A() 10\nend seed species\n"
        "begin observables\n  Molecules A_obs A()\nend observables\n"
        "begin reaction rules\n  A() -> 0 k\nend reaction rules\n"
        'end model\ngenerate_network({overwrite=>1})\nsimulate_pla({method=>"pla",t_end=>0,n_steps=>1,seed=>1})\n',
    ),
)


def _compare(
    comparator: str, oracle_bytes: bytes, consumer_bytes: bytes
) -> tuple[bool, str]:
    if comparator == _GDAT:
        return checks._compare_gdat_bytes(oracle_bytes, consumer_bytes)
    if comparator == _NET:
        return checks._compare_net_bytes(oracle_bytes, consumer_bytes)
    if comparator == _HYBRID:
        return checks._compare_hybrid_bngl_bytes(oracle_bytes, consumer_bytes)
    return False, f"unsupported comparator {comparator}"


def build_bngl_feature_receipts(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    bng_cpp: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError(
            "issue #471 BNGL feature receipts require the requested clean revision"
        )
    matrix = json.loads(
        (root / "provenance/capability-matrix.yml").read_text(encoding="utf-8")
    )
    matrix_ids = {
        str(entry["id"])
        for entry in matrix.get("rows", [])
        if str(entry.get("upstream", "")).startswith("bionetgen:")
    }
    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    build_platform = _build_platform()
    bng2_version = _version_line(
        [
            "perl",
            "-e",
            'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
            str(bng2_root / "bng2" / "BNG2.pl"),
        ],
        "2.9.3-pinned",
    )
    bng_cpp_version = _version_line([str(bng_cpp), "--version"], "bng_cpp")
    bng2_pl = (bng2_root / "bng2" / "BNG2.pl").resolve()
    bng2_env = {**dict(os.environ), "BNGPATH": str((bng2_root / "bng2").resolve())}

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="bng3-471-bngl-features-") as td:
        work_root = Path(td)
        for idx, spec in enumerate(FEATURE_PROBES):
            if spec.row_id not in matrix_ids:
                continue
            inp_bytes = spec.bngl_text.encode("utf-8")
            ref_dir = work_root / f"{idx:03d}_{spec.row_id}" / "oracle"
            sub_dir = work_root / f"{idx:03d}_{spec.row_id}" / "consumer"
            ref_dir.mkdir(parents=True, exist_ok=True)
            sub_dir.mkdir(parents=True, exist_ok=True)
            ref_bngl = ref_dir / "probe.bngl"
            sub_bngl = sub_dir / "probe.bngl"
            ref_bngl.write_bytes(inp_bytes)
            sub_bngl.write_bytes(inp_bytes)
            for fname, content in spec.extra_files:
                (ref_dir / fname).write_text(content, encoding="utf-8")
                (sub_dir / fname).write_text(content, encoding="utf-8")

            ref_cmd = ["perl", str(bng2_pl), str(ref_bngl)]
            sub_cmd = [str(bng_cpp), str(sub_bngl)]
            ref_proc = subprocess.run(
                ref_cmd,
                cwd=ref_dir,
                env=bng2_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            sub_proc = subprocess.run(
                sub_cmd,
                cwd=sub_dir,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            ref_out = ref_dir / spec.output_file
            sub_out = sub_dir / spec.output_file
            if (
                ref_proc.returncode != 0
                or sub_proc.returncode != 0
                or not ref_out.is_file()
                or not sub_out.is_file()
            ):
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "execution_or_output_missing",
                        "oracle_rc": ref_proc.returncode,
                        "consumer_rc": sub_proc.returncode,
                    }
                )
                continue

            o_bytes = ref_out.read_bytes()
            c_bytes = sub_out.read_bytes()
            ok, detail = _compare(spec.comparator, o_bytes, c_bytes)
            if not ok:
                skipped.append(
                    {
                        "id": spec.row_id,
                        "reason": "comparator_mismatch",
                        "detail": detail,
                    }
                )
                continue

            ext = Path(spec.output_file).suffix or ".out"
            row_art = artifacts_dir / spec.row_id
            row_art.mkdir(parents=True, exist_ok=True)
            producer_rel = f"{spec.row_id}/producer.bngl"
            oracle_rel = f"{spec.row_id}/oracle{ext}"
            consumer_rel = f"{spec.row_id}/consumer{ext}"
            (artifacts_dir / producer_rel).write_bytes(inp_bytes)
            (artifacts_dir / oracle_rel).write_bytes(o_bytes)
            (artifacts_dir / consumer_rel).write_bytes(c_bytes)

            producer_sha = _sha256_bytes(inp_bytes)
            oracle_sha = _sha256_bytes(o_bytes)
            consumer_sha = _sha256_bytes(c_bytes)
            ref_cmd_str = " ".join(ref_cmd)
            sub_cmd_str = " ".join(sub_cmd)

            receipt = {
                "schema_version": 2,
                "kind": "release-oracle-consumer-receipt",
                "capability_id": spec.row_id,
                "check_id": f"release-capability[{spec.row_id}]",
                "comparator": spec.comparator,
                "source_revision": revision,
                "product_revision": revision,
                "oracle": {
                    "name": f"Pinned BNG2.pl ({spec.row_id})",
                    "source_id": "bng2",
                    "revision": pinned_rev,
                    "build_platform": build_platform,
                    "source_clean": True,
                    "path": oracle_rel,
                    "artifact_sha256": oracle_sha,
                    "script_sha256": script_sha256,
                    "executable_sha256": run_network_sha256,
                    "command": ref_cmd_str,
                    "expected_origin": "external-source",
                    "execution": {
                        "executable": "BNG2.pl",
                        "version": bng2_version,
                        "command": ref_cmd_str,
                        "exit_code": ref_proc.returncode,
                    },
                },
                "producer": {
                    "path": producer_rel,
                    "output_sha256": producer_sha,
                },
                "consumer": {
                    "path": consumer_rel,
                    "output_sha256": consumer_sha,
                    "consumed_producer_sha256": producer_sha,
                    "execution": {
                        "executable": "bng_cpp",
                        "version": bng_cpp_version,
                        "command": sub_cmd_str,
                        "exit_code": sub_proc.returncode,
                    },
                },
            }
            (receipts_dir / f"{spec.row_id}.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            emitted.append(spec.row_id)

    return {
        "schema_version": 1,
        "source_revision": revision,
        "oracle_revision": pinned_rev,
        "emitted_count": len(emitted),
        "skipped_count": len(skipped),
        "emitted_rows": emitted,
        "skipped_rows": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_bngl_feature_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        bng2_root=args.bng2_root.resolve(),
        bng_cpp=args.bng_cpp.resolve(),
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"Emitted {summary['emitted_count']} BNGL feature #471/#180 receipts "
        f"({summary['skipped_count']} skipped) for {summary['source_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
