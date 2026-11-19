"""External comp checksum handling, SBML comp V1R3 section 3.3.2."""

import hashlib

import pytest

from bionetgen.atomizer.modern import Atomizer, SBMLParser
from bionetgen.atomizer.modern.helpers import logger

CHILD = b"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="childModel"><listOfParameters>
    <parameter id="p" value="2" constant="true"/>
  </listOfParameters></model>
</sbml>"""
PARENT = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
 xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"
 level="3" version="1" comp:required="true">
 <model id="parent"><comp:listOfSubmodels>
  <comp:submodel comp:id="child" comp:modelRef="external"/>
 </comp:listOfSubmodels></model>
 <comp:listOfExternalModelDefinitions>
  <comp:externalModelDefinition comp:id="external" comp:source="child.xml"
   comp:modelRef="childModel" comp:md5="{checksum}"/>
 </comp:listOfExternalModelDefinitions>
</sbml>"""


@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("general_flattening", [False, True])
def test_external_checksum_warns_only_on_mismatch(
    tmp_path, mismatch, general_flattening
):
    libsbml = pytest.importorskip("libsbml")
    (tmp_path / "child.xml").write_bytes(CHILD)
    checksum = "0" * 32 if mismatch else hashlib.md5(CHILD).hexdigest()
    source = PARENT.format(checksum=checksum)
    if general_flattening:
        source = source.replace(
            '<model id="parent">',
            '<model id="parent"><listOfParameters><parameter id="q" value="1" constant="true"/></listOfParameters>',
        )
    parent = tmp_path / "parent.xml"
    parent.write_text(source)
    doc = libsbml.readSBMLFromFile(str(parent))
    assert not [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]

    model = SBMLParser().parse(source, source_path=parent)
    assert model.parameters["child__p"].value == 2
    warnings = [w for w in model.import_warnings if w.category == "compChecksum"]
    assert bool(warnings) is mismatch
    if mismatch:
        assert "child.xml" in warnings[0].message
        assert checksum in warnings[0].message
        assert hashlib.md5(CHILD).hexdigest() in warnings[0].message

    logger.clear()
    result = Atomizer(quiet_mode=True).atomize(source, source_path=parent)
    assert result.success
    assert ("compChecksum" in result.bngl) is mismatch
    assert any("compChecksum" in str(entry.message) for entry in result.log) is mismatch


def test_nested_external_checksum_is_reported_before_flattening(tmp_path):
    pytest.importorskip("libsbml")
    leaf_dir = tmp_path / "nested"
    leaf_dir.mkdir()
    (leaf_dir / "child.xml").write_bytes(CHILD)
    inner = PARENT.format(checksum="0" * 32).replace('id="parent"', 'id="middle"')
    (leaf_dir / "middle.xml").write_text(inner)
    outer = PARENT.format(checksum=hashlib.md5(inner.encode()).hexdigest())
    outer = outer.replace('comp:source="child.xml"', 'comp:source="nested/middle.xml"')
    outer = outer.replace('comp:modelRef="childModel"', 'comp:modelRef="middle"')
    parent = tmp_path / "outer.xml"
    parent.write_text(outer)

    model = SBMLParser().parse(outer, source_path=parent)
    assert model.parameters["child__child__p"].value == 2
    warnings = [w for w in model.import_warnings if w.category == "compChecksum"]
    assert len(warnings) == 1
    assert "nested/child.xml" in warnings[0].message
    assert hashlib.md5(CHILD).hexdigest() in warnings[0].message
