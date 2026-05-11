from bionetgen.atomizer.writer.bnglWriter import bnglReaction


def test_bnglReaction_basic():
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() <-> B() k1 "


def test_bnglReaction_multiple_stoichiometry():
    reactant = [("A", 2, "comp1")]
    product = [("B", 3, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() + A() <-> B() + B() + B() k1 "


def test_bnglReaction_compartments():
    reactant = [("A", 1, "comp1"), ("B", 1, "comp2")]
    product = [("C", 1, "comp3")]
    rate = "k1"
    tags = {"comp1": "@C1", "comp2": "@C2", "comp3": "@C3"}

    result = bnglReaction(reactant, product, rate, tags, isCompartments=True)
    assert result == "A()@C1 + B()@C2 <-> C()@C3 k1 "


def test_bnglReaction_irreversible():
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags, reversible=False)
    assert result == "A() -> B() k1 "


def test_bnglReaction_zero_reactants():
    reactant = []
    product = [("A", 1, "comp1")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "0  <-> A() k1 "


def test_bnglReaction_zero_products():
    reactant = [("A", 1, "comp1")]
    product = []
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() <-> 0  k1 "


def test_bnglReaction_with_comment_and_name():
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(
        reactant, product, rate, tags, comment="# my comment", reactionName="R1"
    )
    assert result == "R1: A() <-> B() k1 # my comment"


def test_bnglReaction_reactant_stoichiometry_zero_run():
    reactant = [("A", 0, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "0  <-> B() k1 "


def test_bnglReaction_0_product_fix():
    reactant = [("0", 1, "comp1")]
    product = [("0", 1, "comp2")]
    rate = "k1"
    tags = {}
    result = bnglReaction(reactant, product, rate, tags)
    assert result == "0 <->0 k1 "


def test_bnglReaction_multiple_reactants_one_zero():
    reactant = [("A", 1, "comp1"), ("B", 0, "comp2")]
    product = [("C", 1, "comp3")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() +  <-> C() k1 "


def test_bnglReaction_printTranslate_translator():
    class DummyTranslator:
        def __init__(self, name):
            self.name = name
            self.comp = None

        def addCompartment(self, comp):
            self.comp = comp

        def __str__(self):
            return f"{self.name}(){self.comp}"

    translator = {"A": DummyTranslator("A_trans")}
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {"comp1": "@C1", "comp2": "@C2"}

    result = bnglReaction(
        reactant, product, rate, tags, translator=translator, isCompartments=True
    )
    assert result == "A_trans()@C1 <-> B()@C2 k1 "


def test_bnglReaction_non_integer_stoichiometry():
    reactant = [("A", 1.5, "comp1")]
    product = [("B", 1, "comp2")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() <-> B() k1 "


def test_bnglReaction_product_branch():
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2"), ("C", 1, "comp3")]
    rate = "k1"
    tags = {"comp3": "@C3"}

    result = bnglReaction(reactant, product, rate, tags, isCompartments=False)
    assert result == "A() <-> B() + C() k1 "

    product2 = [("B", 1), ("C", 1, "comp3")]
    result2 = bnglReaction(reactant, product2, rate, tags, isCompartments=True)
    assert result2 == "A() <-> B() + C()@C3 k1 "


def test_bnglReaction_multiple_reactants_one_zero_product():
    reactant = [("A", 1, "comp1")]
    product = [("B", 1, "comp2"), ("C", 1, "comp3")]
    rate = "k1"
    tags = {}

    result = bnglReaction(reactant, product, rate, tags)
    assert result == "A() <-> B() + C() k1 "
