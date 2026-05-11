import os
from bionetgen.main import BioNetGenTest
from bionetgen.atomizer.sbml2json import factorial

tfold = os.path.dirname(__file__)


def test_factorial():
    assert factorial(5) == 120
    assert factorial(1) == 1
    assert factorial(0) == 1
    assert factorial(-1) == 1


def test_atomize_flat():
    if not os.path.exists(os.path.join(tfold, "test")):
        os.mkdir(os.path.join(tfold, "test"))
    argv = [
        "atomize",
        "-i",
        os.path.join(tfold, "test_sbml.xml"),
        "-o",
        os.path.join(*[tfold, "test", "test_sbml_flat.bngl"]),
    ]
    to_match = ["test_sbml_flat.bngl"]
    with BioNetGenTest(argv=argv) as app:
        app.run()
        assert app.exit_code == 0
        file_list = os.listdir(os.path.join(tfold, "test"))
        assert file_list.sort() == to_match.sort()


def test_atomize_atomized():
    if not os.path.exists(os.path.join(tfold, "test")):
        os.mkdir(os.path.join(tfold, "test"))
    argv = [
        "atomize",
        "-i",
        os.path.join(tfold, "test_sbml.xml"),
        "-o",
        os.path.join(*[tfold, "test", "test_sbml_atom.bngl"]),
        "-a",
    ]
    to_match = ["test_sbml_atom.bngl"]
    with BioNetGenTest(argv=argv) as app:
        app.run()
        assert app.exit_code == 0
        file_list = os.listdir(os.path.join(tfold, "test"))
        assert file_list.sort() == to_match.sort()


def test_propagate_changes_error_path():
    from bionetgen.atomizer.atomizer.moleculeCreation import propagateChanges
    from unittest.mock import patch, MagicMock

    translator = MagicMock()
    dependencyGraph = {"dep": [["mol1"]]}

    with patch(
        "bionetgen.atomizer.atomizer.moleculeCreation.updateSpecies",
        side_effect=Exception("Test Exception"),
    ):
        with patch("bionetgen.atomizer.atomizer.moleculeCreation.logMess") as mock_log:
            propagateChanges(translator, dependencyGraph)
            mock_log.assert_called_with(
                "CRITICAL:Program", "Species is not being properly propagated"
            )
