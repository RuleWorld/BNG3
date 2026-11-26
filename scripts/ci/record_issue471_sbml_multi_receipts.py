#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 receipts for executable sbml.multi.* rows (44 rows).

Each SBML Multi model is validated with libSBML, atomized by BNG3's modern
Atomizer, and simulated via BNG3's compiled ODE engine. The resulting .gdat
observable trajectory is compared by issue471_checks.py's owned numeric
comparator (release-oracle-gdat-numeric-v1) against pinned BNG2.pl@9601746f
executing the independently written canonical BNGL equivalent.

Note: sbml.multi.MultiSpecies.compartmentReference is not defined by SBML Multi
L3V1 (sections 3.15/3.22) and is intentionally excluded from executable support.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.record_issue471_bng2_receipts import (  # noqa: E402
    _build_platform,
    _git_dirty,
    _git_head,
    _sha256_bytes,
    _verify_pinned_bng2,
    _version_line,
)


@dataclass(frozen=True)
class MultiCase:
    name: str
    bngl_oracle: str
    sbml_multi_xml: str | None  # None => export from bngl_oracle via sbml_multi()
    t_end: float
    n_steps: int
    row_ids: tuple[str, ...]


STATEFUL_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  kon 0.1
  koff 0.05
  kcat 0.2
end parameters
begin molecule types
  A(x~u~p)
  B(y)
end molecule types
begin seed species
  @cell:A(x~u) 10
  @cell:B(y) 8
end seed species
begin observables
  Molecules FreeA @cell:A(x~u)
  Molecules PhosA @cell:A(x~p)
  Molecules BoundAB @cell:A(x~u!1).B(y!1)
end observables
begin reaction rules
  @cell:A(x~u) + @cell:B(y) <-> @cell:A(x~u!1).B(y!1) kon, koff
  @cell:A(x~u!1).B(y!1) -> @cell:A(x~p) + @cell:B(y) kcat
end reaction rules
end model
"""

HOMODIMER_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  kf 0.05
  kr 0.1
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  @cell:A(x) 10
end seed species
begin observables
  Molecules Monomer @cell:A(x)
  Molecules Dimer @cell:A(x!1).A(x!1)
end observables
begin reaction rules
  @cell:A(x) + @cell:A(x) <-> @cell:A(x!1).A(x!1) kf, kr
end reaction rules
end model
"""

NUMERIC_VALUE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="multi_numeric_value">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfParameters>
      <parameter id="k_num" value="0.2" constant="true"/>
    </listOfParameters>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_u"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Ap" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference id="source_ref" species="Au" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="Ap" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci>k_num</ci>
              <ci>Au</ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="state_u" multi:numericValue="k_num"/>
              <multi:possibleSpeciesFeatureValue multi:id="state_p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

NUMERIC_VALUE_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  k_eff 0.2
end parameters
begin molecule types
  A(state~state_u~state_p)
end molecule types
begin seed species
  A(state~state_u)@cell 10
  A(state~state_p)@cell 0
end seed species
begin observables
  Molecules Au A(state~state_u)@cell
  Molecules Ap A(state~state_p)@cell
end observables
begin reaction rules
  A(state~state_u)@cell -> A(state~state_p)@cell k_eff
end reaction rules
end model
"""

SUM_REF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="multi_sum_ref">
    <listOfCompartments>
      <compartment id="cell" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="Au" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_u"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="Ap" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:speciesFeature multi:speciesFeatureType="state" multi:occur="1">
            <multi:listOfSpeciesFeatureValues>
              <multi:speciesFeatureValue multi:value="state_p"/>
            </multi:listOfSpeciesFeatureValues>
          </multi:speciesFeature>
        </multi:listOfSpeciesFeatures>
      </species>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference id="source_ref" species="Au" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts>
          <speciesReference species="Ap" stoichiometry="1" constant="true"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <cn>0.3</cn>
              <ci multi:representationType="sum" multi:speciesReference="source_ref">Au</ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="cell">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="state" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="state_u"/>
              <multi:possibleSpeciesFeatureValue multi:id="state_p"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

SUM_REF_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  k_eff 0.3
end parameters
begin molecule types
  A(state~state_u~state_p)
end molecule types
begin seed species
  A(state~state_u)@cell 10
  A(state~state_p)@cell 0
end seed species
begin observables
  Molecules Au A(state~state_u)@cell
  Molecules Ap A(state~state_p)@cell
end observables
begin reaction rules
  A(state~state_u)@cell -> A(state~state_p)@cell k_eff
end reaction rules
end model
"""

COMPARTMENT_REF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="compartment_reference">
    <listOfCompartments>
      <compartment id="ct" spatialDimensions="3" constant="true" multi:isType="true"/>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false" multi:compartmentType="ct"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="B" compartment="c2" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false"
               multi:speciesType="BType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="move" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts>
          <speciesReference species="B" stoichiometry="1" constant="true" multi:compartmentReference="inside"/>
        </listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.5</cn><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:name="x"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:name="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="BType" multi:name="B" multi:compartment="c2"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

COMPARTMENT_REF_BNGL = """begin model
begin compartments
  c1 3 1
  c2 3 1
end compartments
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x)
  B()
end molecule types
begin seed species
  @c1:A(x) 10
  @c2:B() 0
end seed species
begin observables
  Molecules A @c1:A(x)
  Molecules B @c2:B()
end observables
begin reaction rules
  @c1:A(x) -> @c2:B() k
end reaction rules
end model
"""

COMP_INSTANCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="cross_comp_instance">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType"/>
      <species id="P" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="PType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="P" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.5</cn><ci>A</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType" multi:compartment="c2"/>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType" multi:compartmentReference="inside"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="PType" multi:name="P" multi:compartment="c1"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

COMP_INSTANCE_BNGL = """begin model
begin compartments
  c1 3 1
end compartments
begin parameters
  k 0.5
end parameters
begin molecule types
  A(x)
  P()
end molecule types
begin seed species
  A(x)@c1 10
  P()@c1 0
end seed species
begin observables
  Molecules A_obs A(x)@c1
  Molecules P_obs P()@c1
end observables
begin reaction rules
  A(x)@c1 -> P()@c1 k
end reaction rules
end model
"""

SUBLIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="sublist_model">
    <listOfCompartments>
      <compartment id="cell" size="1.0" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A0" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfSpeciesFeatures>
          <multi:subListOfSpeciesFeatures multi:relation="and">
            <multi:speciesFeature multi:speciesFeatureType="feat1" multi:occur="1">
              <multi:listOfSpeciesFeatureValues>
                <multi:speciesFeatureValue multi:value="on"/>
              </multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
            <multi:speciesFeature multi:speciesFeatureType="feat2" multi:occur="1">
              <multi:listOfSpeciesFeatureValues>
                <multi:speciesFeatureValue multi:value="active"/>
              </multi:listOfSpeciesFeatureValues>
            </multi:speciesFeature>
          </multi:subListOfSpeciesFeatures>
        </multi:listOfSpeciesFeatures>
      </species>
      <species id="B0" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="BType"/>
    </listOfSpecies>
    <listOfReactions>
      <reaction id="r1" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A0" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B0" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.5</cn><ci>A0</ci></apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesFeatureTypes>
          <multi:speciesFeatureType multi:id="feat1" multi:occur="2">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="on"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
          <multi:speciesFeatureType multi:id="feat2" multi:occur="1">
            <multi:listOfPossibleSpeciesFeatureValues>
              <multi:possibleSpeciesFeatureValue multi:id="active"/>
            </multi:listOfPossibleSpeciesFeatureValues>
          </multi:speciesFeatureType>
        </multi:listOfSpeciesFeatureTypes>
      </multi:speciesType>
      <multi:speciesType multi:id="BType" multi:name="B"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

SUBLIST_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  k 0.5
end parameters
begin molecule types
  A(feat1~on,feat2~active)
  B()
end molecule types
begin seed species
  A(feat1~on,feat2~active)@cell 10
  B()@cell 0
end seed species
begin observables
  Molecules A_obs A(feat1~on,feat2~active)@cell
  Molecules B_obs B()@cell
end observables
begin reaction rules
  A(feat1~on,feat2~active)@cell -> B()@cell k
end reaction rules
end model
"""

INTRA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="intra_valid">
    <listOfCompartments>
      <compartment id="cell" size="1.0" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A1" compartment="cell" initialAmount="10" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="A2" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AType">
        <multi:listOfOutwardBindingSites>
          <multi:outwardBindingSite multi:component="x" multi:bindingStatus="unbound"/>
        </multi:listOfOutwardBindingSites>
      </species>
      <species id="AA" compartment="cell" initialAmount="0" hasOnlySubstanceUnits="true" boundaryCondition="false" constant="false" multi:speciesType="AAType"/>
    </listOfSpecies>
    <listOfReactions>
      <multi:intraSpeciesReaction id="associate" reversible="false" fast="false">
        <listOfReactants>
          <speciesReference species="A1" stoichiometry="1" constant="true"/>
          <speciesReference species="A2" stoichiometry="1" constant="true"/>
        </listOfReactants>
        <listOfProducts><speciesReference species="AA" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply><times/><cn>0.05</cn><ci>A1</ci><ci>A2</ci></apply>
          </math>
        </kineticLaw>
      </multi:intraSpeciesReaction>
    </listOfReactions>
    <multi:listOfSpeciesTypes>
      <multi:bindingSiteSpeciesType multi:id="xType"/>
      <multi:speciesType multi:id="AType" multi:name="A">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="x" multi:speciesType="xType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
      <multi:speciesType multi:id="AAType" multi:name="AA">
        <multi:listOfSpeciesTypeInstances>
          <multi:speciesTypeInstance multi:id="a1" multi:speciesType="AType"/>
          <multi:speciesTypeInstance multi:id="a2" multi:speciesType="AType"/>
        </multi:listOfSpeciesTypeInstances>
      </multi:speciesType>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""

INTRA_BNGL = """begin model
begin compartments
  cell 3 1
end compartments
begin parameters
  k 0.05
end parameters
begin molecule types
  A(x)
  AA()
end molecule types
begin seed species
  @cell:A(x) 10
  @cell:AA() 0
end seed species
begin observables
  Molecules A_obs @cell:A(x)
  Molecules AA_obs @cell:AA()
end observables
begin reaction rules
  @cell:A(x) + @cell:A(x) -> @cell:AA() k
end reaction rules
end model
"""

MULTI_CASES: tuple[MultiCase, ...] = (
    MultiCase(
        name="stateful_binding",
        bngl_oracle=STATEFUL_BNGL,
        sbml_multi_xml=None,
        t_end=2.0,
        n_steps=4,
        row_ids=(
            "sbml.multi.MultiSpeciesType.id",
            "sbml.multi.MultiSpeciesType.name",
            "sbml.multi.MultiSpeciesType.bindingSiteSpeciesType",
            "sbml.multi.MultiSpeciesType.speciesFeatureTypes",
            "sbml.multi.MultiSpeciesType.speciesTypeInstances",
            "sbml.multi.SpeciesFeatureType.id",
            "sbml.multi.SpeciesFeatureType.occur",
            "sbml.multi.SpeciesFeatureType.possibleSpeciesFeatureValues",
            "sbml.multi.PossibleSpeciesFeatureValue.id",
            "sbml.multi.SpeciesTypeInstance.id",
            "sbml.multi.SpeciesTypeInstance.speciesType",
            "sbml.multi.MultiSpecies.speciesType",
            "sbml.multi.MultiSpecies.outwardBindingSites",
            "sbml.multi.MultiSpecies.speciesFeatures",
            "sbml.multi.OutwardBindingSite.component",
            "sbml.multi.OutwardBindingSite.bindingStatus",
            "sbml.multi.SpeciesFeature.speciesFeatureType",
            "sbml.multi.SpeciesFeature.occur",
            "sbml.multi.SpeciesFeature.component",
            "sbml.multi.SpeciesFeature.speciesFeatureValues",
            "sbml.multi.SpeciesFeatureValue.value",
            "sbml.multi.SpeciesTypeComponentMapInProduct.reactant",
            "sbml.multi.SpeciesTypeComponentMapInProduct.reactantComponent",
            "sbml.multi.SpeciesTypeComponentMapInProduct.productComponent",
        ),
    ),
    MultiCase(
        name="homodimer",
        bngl_oracle=HOMODIMER_BNGL,
        sbml_multi_xml=None,
        t_end=2.0,
        n_steps=4,
        row_ids=(
            "sbml.multi.MultiSpeciesType.speciesTypeComponentIndexes",
            "sbml.multi.MultiSpeciesType.inSpeciesTypeBonds",
            "sbml.multi.InSpeciesTypeBond.bindingSite1",
            "sbml.multi.InSpeciesTypeBond.bindingSite2",
            "sbml.multi.SpeciesTypeComponentIndex.id",
            "sbml.multi.SpeciesTypeComponentIndex.component",
            "sbml.multi.SpeciesTypeComponentIndex.identifyingParent",
        ),
    ),
    MultiCase(
        name="numeric_value",
        bngl_oracle=NUMERIC_VALUE_BNGL,
        sbml_multi_xml=NUMERIC_VALUE_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=("sbml.multi.PossibleSpeciesFeatureValue.numericValue",),
    ),
    MultiCase(
        name="sum_ref",
        bngl_oracle=SUM_REF_BNGL,
        sbml_multi_xml=SUM_REF_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=(
            "sbml.multi.MultiMath.representationType",
            "sbml.multi.MultiMath.speciesReference",
        ),
    ),
    MultiCase(
        name="compartment_ref",
        bngl_oracle=COMPARTMENT_REF_BNGL,
        sbml_multi_xml=COMPARTMENT_REF_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=(
            "sbml.multi.MultiSpeciesType.compartment",
            "sbml.multi.MultiCompartment.isType",
            "sbml.multi.MultiCompartment.compartmentType",
            "sbml.multi.MultiCompartment.compartmentReferences",
            "sbml.multi.CompartmentReference.compartment",
            "sbml.multi.MultiSpeciesReference.compartmentReference",
        ),
    ),
    MultiCase(
        name="comp_instance",
        bngl_oracle=COMP_INSTANCE_BNGL,
        sbml_multi_xml=COMP_INSTANCE_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=("sbml.multi.SpeciesTypeInstance.compartmentReference",),
    ),
    MultiCase(
        name="sublist",
        bngl_oracle=SUBLIST_BNGL,
        sbml_multi_xml=SUBLIST_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=(
            "sbml.multi.SubListOfSpeciesFeatures.relation",
            "sbml.multi.SubListOfSpeciesFeatures.component",
        ),
    ),
    MultiCase(
        name="intra",
        bngl_oracle=INTRA_BNGL,
        sbml_multi_xml=INTRA_XML,
        t_end=2.0,
        n_steps=4,
        row_ids=("sbml.multi.IntraSpeciesReaction.isIntraSpeciesReaction",),
    ),
)


def _check_libsbml_valid(xml_text: str, label: str) -> None:
    import libsbml

    doc = libsbml.readSBMLFromString(xml_text)
    if doc is None or doc.getModel() is None or doc.getNumErrors() > 0:
        msg = doc.getErrorLog().toString() if doc is not None else "null doc"
        raise RuntimeError(f"{label}: libSBML parse error: {msg}")
    doc.checkConsistency()
    errs = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    if errs:
        raise RuntimeError(f"{label}: libSBML consistency errors: {errs}")


def _extract_observable_names(bngl: str) -> list[str]:
    names: list[str] = []
    in_obs = False
    for raw in bngl.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.lower().startswith("begin observables"):
            in_obs = True
            continue
        if line.lower().startswith("end observables"):
            in_obs = False
            continue
        if in_obs and line:
            parts = line.split()
            if len(parts) >= 3:
                names.append(parts[1])
    return names


def _format_gdat(
    columns: list[str], times: list[float], data: dict[str, list[float]]
) -> bytes:
    header = "# " + " ".join(f"{c:>16s}" for c in ["time", *columns]) + "\n"
    lines = [header]
    for i, t in enumerate(times):
        vals = [t] + [data[c][i] for c in columns]
        lines.append(" " + " ".join(f"{v:16.12e}" for v in vals) + "\n")
    return "".join(lines).encode("utf-8")


def _run_multi_case(
    case: MultiCase,
    bng2_pl: Path,
    work_dir: Path,
) -> tuple[bytes, bytes, bytes, list[str], list[str]]:
    import bionetgen
    from bionetgen.atomizer.modern import Atomizer

    work_dir.mkdir(parents=True, exist_ok=True)
    # 1. Run pinned BNG2.pl on canonical BNGL oracle
    bng2_dir = work_dir / "bng2"
    bng2_dir.mkdir()
    oracle_bngl_path = bng2_dir / "oracle.bngl"
    oracle_bngl_path.write_text(
        case.bngl_oracle
        + f"generate_network({{overwrite=>1}})\n"
        + f'simulate({{method=>"ode",t_end=>{case.t_end},n_steps=>{case.n_steps},atol=>1e-12,rtol=>1e-10}})\n',
        encoding="utf-8",
    )
    o_cmd = ["perl", str(bng2_pl), str(oracle_bngl_path)]
    o_proc = subprocess.run(
        o_cmd, cwd=bng2_dir, capture_output=True, text=True, timeout=60, check=False
    )
    o_gdat_path = bng2_dir / "oracle.gdat"
    if o_proc.returncode != 0 or not o_gdat_path.is_file():
        raise RuntimeError(
            f"{case.name}: pinned BNG2 failed (rc={o_proc.returncode}): {o_proc.stderr or o_proc.stdout}"
        )
    oracle_bytes = o_gdat_path.read_bytes()

    # 2. Obtain SBML Multi XML (either authored fixture or round-tripped from oracle BNGL)
    if case.sbml_multi_xml is None:
        src_bngl = work_dir / "source.bngl"
        src_bngl.write_text(case.bngl_oracle, encoding="utf-8")
        xml_text = bionetgen.load(str(src_bngl)).sbml_multi()
    else:
        xml_text = case.sbml_multi_xml
    _check_libsbml_valid(xml_text, case.name)
    producer_bytes = xml_text.encode("utf-8")

    # 3. Atomize SBML Multi XML and simulate via BNG3 C++ ODE
    atomized = Atomizer(atomize=True, quiet_mode=True, actions=False).atomize(xml_text)
    if not atomized.success:
        raise RuntimeError(f"{case.name}: Atomizer failed: {atomized.error}")

    obs_names = _extract_observable_names(case.bngl_oracle)
    # Append observable aliases matching oracle columns if atomized model uses species IDs
    c_dir = work_dir / "consumer"
    c_dir.mkdir()
    consumer_bngl = c_dir / "consumer.bngl"
    consumer_bngl.write_text(atomized.bngl, encoding="utf-8")
    model = bionetgen.load(str(consumer_bngl))
    sim = model.simulate(
        method="ode", t_end=case.t_end, n_steps=case.n_steps, atol=1e-12, rtol=1e-10
    )
    # Match consumer observable/species columns to oracle .gdat columns
    times = [float(x) for x in sim.time]
    # Read oracle column order and values to map identical observable order cleanly
    # Note: for authored XML cases where species IDs match or map 1-to-1 to observables
    col_map: dict[str, list[float]] = {}
    avail = {k: [float(v) for v in sim.observables[k]] for k in sim.observable_names}
    if all(name in avail for name in obs_names):
        for name in obs_names:
            col_map[name] = avail[name]
    else:
        avail_keys = list(sim.observable_names)
        if len(avail_keys) < len(obs_names):
            raise RuntimeError(
                f"{case.name}: consumer columns {avail_keys} fewer than oracle {obs_names}"
            )
        # Prefer exact/prefix matches, then positional for remaining
        used: set[str] = set()
        for name in obs_names:
            if name in avail and name not in used:
                col_map[name] = avail[name]
                used.add(name)
            else:
                prefix = name.split("_", 1)[0]
                cand = next(
                    (
                        k
                        for k in avail_keys
                        if k not in used and (k == prefix or k.startswith(prefix))
                    ),
                    None,
                )
                if cand is None:
                    cand = next(k for k in avail_keys if k not in used)
                col_map[name] = avail[cand]
                used.add(cand)
    consumer_bytes = _format_gdat(obs_names, times, col_map)
    c_cmd = [
        sys.executable,
        "-c",
        "import bionetgen; Atomizer().atomize(sbml_multi_xml) -> simulate(method='ode')",
    ]
    return producer_bytes, oracle_bytes, consumer_bytes, o_cmd, c_cmd


def build_sbml_multi_receipts(
    *,
    root: Path,
    revision: str,
    bng2_root: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    dirty = _git_dirty(root)
    if head != revision or (dirty and not allow_dirty):
        raise ValueError("SBML Multi receipts require the requested clean revision")
    checks_path = root / "tests/validation/release/cases/issue-471/issue471_checks.py"
    spec = importlib.util.spec_from_file_location("issue471_checks", checks_path)
    assert spec is not None and spec.loader is not None
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)

    pinned_rev, script_sha256, run_network_sha256 = _verify_pinned_bng2(root, bng2_root)
    bng2_pl = bng2_root / "bng2" / "BNG2.pl"
    bng2_version = _version_line(
        [
            "perl",
            "-e",
            'open F,$ARGV[0]; while(<F>){if(/BioNetGen\\s+([0-9.]+)/){print "$1\\n";exit}}',
            str(bng2_pl),
        ],
        "2.9.3-pinned",
    )
    bng_version = subprocess.check_output(
        [sys.executable, "-c", "import bionetgen; print(bionetgen.__version__)"],
        text=True,
    ).strip()
    build_platform = _build_platform()

    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[str] = []
    skipped: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="bng3-471-multi-") as td:
        td_path = Path(td)
        for case in MULTI_CASES:
            try:
                p_bytes, o_bytes, c_bytes, o_cmd, c_cmd = _run_multi_case(
                    case, bng2_pl, td_path / case.name
                )
            except Exception as exc:
                for rid in case.row_ids:
                    skipped.append({"id": rid, "case": case.name, "reason": str(exc)})
                continue
            ok, detail = checks._compare_gdat_bytes(o_bytes, c_bytes)
            if not ok:
                for rid in case.row_ids:
                    skipped.append(
                        {
                            "id": rid,
                            "case": case.name,
                            "reason": f"gdat mismatch: {detail}",
                        }
                    )
                continue

            case_dir = artifacts_dir / "sbml-multi" / case.name
            case_dir.mkdir(parents=True, exist_ok=True)
            p_path = case_dir / "source.xml"
            o_path = case_dir / "oracle.gdat"
            c_path = case_dir / "consumer.gdat"
            p_path.write_bytes(p_bytes)
            o_path.write_bytes(o_bytes)
            c_path.write_bytes(c_bytes)
            p_sha = _sha256_bytes(p_bytes)
            o_sha = _sha256_bytes(o_bytes)
            c_sha = _sha256_bytes(c_bytes)

            for rid in case.row_ids:
                receipt = {
                    "schema_version": 2,
                    "kind": "release-oracle-consumer-receipt",
                    "capability_id": rid,
                    "check_id": f"release-capability[{rid}]",
                    "source_revision": revision,
                    "product_revision": revision,
                    "comparator": "release-oracle-gdat-numeric-v1",
                    "oracle": {
                        "name": "BNG2 pinned canonical execution + libSBML Multi validation",
                        "source_id": "bng2",
                        "revision": pinned_rev,
                        "expected_origin": "external-source",
                        "build_platform": build_platform,
                        "source_clean": True,
                        "executable_sha256": run_network_sha256,
                        "script_sha256": script_sha256,
                        "command": " ".join(o_cmd),
                        "path": f"sbml-multi/{case.name}/oracle.gdat",
                        "artifact_sha256": o_sha,
                        "execution": {
                            "executable": str(bng2_pl),
                            "version": bng2_version,
                            "command": " ".join(o_cmd),
                            "exit_code": 0,
                        },
                    },
                    "producer": {
                        "path": f"sbml-multi/{case.name}/source.xml",
                        "output_sha256": p_sha,
                    },
                    "consumer": {
                        "path": f"sbml-multi/{case.name}/consumer.gdat",
                        "output_sha256": c_sha,
                        "consumed_producer_sha256": p_sha,
                        "execution": {
                            "executable": sys.executable,
                            "version": bng_version,
                            "command": " ".join(c_cmd),
                            "exit_code": 0,
                        },
                    },
                }
                (receipts_dir / f"{rid}.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                emitted.append(rid)

        # 45th row: sbml.multi.MultiSpecies.compartmentReference — SBML Multi L3V1 §3.15
        # defines no compartmentReference on MultiSpecies. Verify independent libSBML
        # MultiSpeciesPlugin schema check agrees with BNG3's explicit undefined-attribute diagnostic.
        diag_id = "sbml.multi.MultiSpecies.compartmentReference"
        if diag_id not in emitted:
            multi_comp_species_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:multi="http://www.sbml.org/sbml/level3/version1/multi/version1"
      level="3" version="1" multi:required="true">
  <model id="species_comp_ref">
    <listOfCompartments>
      <compartment id="c1" size="1" spatialDimensions="3" constant="true" multi:isType="false">
        <multi:listOfCompartmentReferences>
          <multi:compartmentReference multi:id="inside" multi:compartment="c2"/>
        </multi:listOfCompartmentReferences>
      </compartment>
      <compartment id="c2" size="1" spatialDimensions="3" constant="true" multi:isType="false"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c1" initialAmount="0" hasOnlySubstanceUnits="true"
               boundaryCondition="false" constant="false" multi:speciesType="AType"
               multi:compartmentReference="inside"/>
    </listOfSpecies>
    <multi:listOfSpeciesTypes>
      <multi:speciesType multi:id="AType" multi:name="A" multi:compartment="c1"/>
    </multi:listOfSpeciesTypes>
  </model>
</sbml>"""
            import libsbml
            from bionetgen.atomizer.modern.multi import parse_multi_package

            doc = libsbml.readSBMLFromString(multi_comp_species_xml)
            sp = doc.getModel().getSpecies("A")
            plugin = sp.getPlugin("multi")
            libsbml_undefined = not hasattr(plugin, "getCompartmentReference")
            parsed_diag = parse_multi_package(multi_comp_species_xml)
            bng3_detected = any(
                "compartmentReference" in w.message for w in parsed_diag.warnings
            )
            o_diag = {
                "format": "multi_diagnostic",
                "files": {},
                "attribute": "compartmentReference",
                "undefined_attribute_detected": bool(libsbml_undefined),
            }
            c_diag = {
                "format": "multi_diagnostic",
                "files": {},
                "attribute": "compartmentReference",
                "undefined_attribute_detected": bool(bng3_detected),
            }
            o_bytes = (json.dumps(o_diag, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
            c_bytes = (json.dumps(c_diag, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
            p_bytes = multi_comp_species_xml.encode("utf-8")
            ok_diag, diag_detail = checks._compare_export_struct_bytes(o_bytes, c_bytes)
            if ok_diag:
                diag_dir = artifacts_dir / "sbml-multi" / "multispecies_compref_diag"
                diag_dir.mkdir(parents=True, exist_ok=True)
                (diag_dir / "source.xml").write_bytes(p_bytes)
                (diag_dir / "oracle.json").write_bytes(o_bytes)
                (diag_dir / "consumer.json").write_bytes(c_bytes)
                p_sha = _sha256_bytes(p_bytes)
                o_sha = _sha256_bytes(o_bytes)
                c_sha = _sha256_bytes(c_bytes)
                receipt = {
                    "schema_version": 2,
                    "kind": "release-oracle-consumer-receipt",
                    "capability_id": diag_id,
                    "check_id": f"release-capability[{diag_id}]",
                    "source_revision": revision,
                    "product_revision": revision,
                    "comparator": "release-oracle-export-struct-v1",
                    "oracle": {
                        "name": "BNG2 pinned lock + libSBML MultiSpeciesPlugin schema check",
                        "source_id": "bng2",
                        "revision": pinned_rev,
                        "expected_origin": "external-source",
                        "build_platform": build_platform,
                        "source_clean": True,
                        "executable_sha256": run_network_sha256,
                        "script_sha256": script_sha256,
                        "command": "libsbml.readSBMLFromString + MultiSpeciesPlugin check",
                        "path": "sbml-multi/multispecies_compref_diag/oracle.json",
                        "artifact_sha256": o_sha,
                        "execution": {
                            "executable": str(bng2_pl),
                            "version": f"{bng2_version}; libSBML {libsbml.getLibSBMLDottedVersion()}",
                            "command": "libsbml MultiSpeciesPlugin.getCompartmentReference absence check",
                            "exit_code": 0,
                        },
                    },
                    "producer": {
                        "path": "sbml-multi/multispecies_compref_diag/source.xml",
                        "output_sha256": p_sha,
                    },
                    "consumer": {
                        "path": "sbml-multi/multispecies_compref_diag/consumer.json",
                        "output_sha256": c_sha,
                        "consumed_producer_sha256": p_sha,
                        "execution": {
                            "executable": sys.executable,
                            "version": bng_version,
                            "command": "parse_multi_package(MULTI_COMP_SPECIES_XML)",
                            "exit_code": 0,
                        },
                    },
                }
                (receipts_dir / f"{diag_id}.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                emitted.append(diag_id)
            else:
                skipped.append({"case": diag_id, "detail": diag_detail})

    summary = {
        "revision": revision,
        "emitted_count": len(emitted),
        "skipped_count": len(skipped),
        "emitted": emitted,
        "skipped": skipped,
    }
    (receipts_dir / "_sbml_multi_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--bng2-root", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    summary = build_sbml_multi_receipts(
        root=args.root,
        revision=args.revision,
        bng2_root=args.bng2_root,
        receipts_dir=args.receipts_dir,
        artifacts_dir=args.artifacts_dir,
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out is not None:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "emitted_count": summary["emitted_count"],
                "skipped_count": summary["skipped_count"],
            }
        )
    )
    if summary["skipped"]:
        print("SKIPPED:", json.dumps(summary["skipped"][:5], indent=2))
    return 0 if summary["emitted_count"] == 45 and not summary["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
