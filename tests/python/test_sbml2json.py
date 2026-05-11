from bionetgen.atomizer.sbml2json import factorial


def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(2) == 2
    assert factorial(3) == 6
    assert factorial(5) == 120
    assert factorial(10) == 3628800

    # Also test negative number just in case
    # Currently the implementation behaves by returning 1 for negative numbers
    assert factorial(-1) == 1
