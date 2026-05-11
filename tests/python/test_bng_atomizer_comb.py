from bionetgen.atomizer.sbml2json import comb


def test_comb_basic():
    """Test basic combinations calculation"""
    assert comb(5, 2) == 10
    assert comb(10, 3) == 120
    assert comb(10, 7) == 120


def test_comb_boundary():
    """Test boundary conditions for combinations"""
    assert comb(5, 0) == 1
    assert comb(5, 5) == 1
    assert comb(0, 0) == 1
    assert comb(1, 1) == 1
    assert comb(1, 0) == 1


def test_comb_invalid():
    """Test combinations with mathematically invalid inputs based on current implementation"""
    # The current implementation of factorial(x) returns 1 for x <= 0
    # so comb(5, 6) = 5! / (6! * (-1)!) = 120 / (720 * 1) = 1/6
    assert comb(5, 6) == 120 / 720
