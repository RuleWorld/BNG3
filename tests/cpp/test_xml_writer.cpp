// Focused XmlWriter regression tests for the BNG2-parity report slice.
//
// Each case reproduces a validated difference between BNG3 XML output and
// BNG2 (bionetgen 0.8.7) writeXML, with BNG2's RxnRule.pm / SpeciesGraph.pm
// as oracle. Expected strings were diffed against BNG2-generated XML.
#include <string>
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include "ast/Model.hpp"
#include "compile/RuleUnitConversion.hpp"
#include "io/XmlWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::string writeXml(const char* source) {
    auto model = parser::parseModel(source);
    REQUIRE(model != nullptr);
    return io::XmlWriter::write(*model);
}

} // namespace

TEST_CASE("XmlWriter degrades a single molecule per molecule with DeleteMolecules") {
    // BNG2 RxnRule.pm findMap: with the DeleteMolecules modifier every deleted
    // molecule gets its own <Delete> with flag 1, even for pure degradation.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k1 1.0
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    Rule03: A()->0 k1 DeleteMolecules
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Delete id=\"RR1_RP1_M1\" DeleteMolecules=\"1\"/>"));
    CHECK(xml.find("<Delete id=\"RR1_RP1\" DeleteMolecules=\"0\"/>") ==
          std::string::npos);
}

TEST_CASE("XmlWriter deletes a partial pattern per molecule without the modifier") {
    // BNG2: deletedCount (1) < totalMolecules (2), so per-molecule <Delete>
    // with flag 0; the surviving molecule keeps its MapItem target.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k2 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 10
    B(a) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    Rule04: A(b!1).B(a!1)->A(b) k2
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Delete id=\"RR1_RP1_M2\" DeleteMolecules=\"0\"/>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<MapItem sourceID=\"RR1_RP1_M1\" targetID=\"RR1_PP1_M1\"/>"));
    CHECK(xml.find("<Delete id=\"RR1_RP1\" DeleteMolecules=\"0\"/>") ==
          std::string::npos);
}

TEST_CASE("XmlWriter keeps whole-pattern deletion for full patterns without the modifier") {
    // BNG2: every molecule of the pattern deleted and no DeleteMolecules
    // modifier, so the whole reactant pattern is deleted with flag 0.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k2 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 10
    B(a) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A(b!1).B(a!1)->0 k2
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Delete id=\"RR1_RP1\" DeleteMolecules=\"0\"/>"));
}

TEST_CASE("XmlWriter writes observable quantifiers as Pattern attributes") {
    // BNG2 SpeciesGraph.pm toXML: the quantifier becomes relation/quantity on
    // <Pattern> (< and > escaped) and the molecule name stays bare.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k1 1.0
end parameters
begin molecule types
    R(l)
end molecule types
begin seed species
    R(l) 10
end seed species
begin observables
    Molecules Rmon R==1
    Molecules Rbig R>20
    Molecules Rle R<=3
end observables
begin reaction rules
    R(l)->0 k1 DeleteMolecules
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Pattern id=\"O1_P1\" relation=\"==\" quantity=\"1\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Pattern id=\"O2_P1\" relation=\"&gt;\" quantity=\"20\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Pattern id=\"O3_P1\" relation=\"&lt;=\" quantity=\"3\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"O1_P1_M1\" name=\"R\">"));
    CHECK(xml.find("name=\"R==") == std::string::npos);
    CHECK(xml.find("name=\"R&gt;") == std::string::npos);
}

TEST_CASE("XmlWriter orders DeleteBond before AddBond in bond-swap rules") {
    // BNG2 RxnRule.pm toXML orders operations to match application order, so
    // the broken bond is deleted before the new bond is added. A strict reader
    // rejects an AddBond to a site the pattern still shows as bound.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k1 1.0
end parameters
begin molecule types
    A(b,s~U~P)
    B(a)
    C(a)
end molecule types
begin seed species
    A(b,s~U) 10
    B(a) 10
    C(a) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    swap: A(b!1,s~U).B(a!1)+C(a)->A(b!2,s~P).C(a!2)+B(a) k1
end reaction rules
end model
)");
    const std::string expected =
        "          <StateChange site=\"RR1_RP1_M1_C2\" finalState=\"P\"/>\n"
        "          <DeleteBond site1=\"RR1_RP1_M1_C1\" site2=\"RR1_RP1_M2_C1\"/>\n"
        "          <AddBond site1=\"RR1_RP1_M1_C1\" site2=\"RR1_RP2_M1_C1\"/>\n";
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(expected));
}

TEST_CASE("XmlWriter emits product AddBonds for zero-order synthesis") {
    // BNG2 emits EdgeAdd with product-side ids for 0->complex synthesis; the
    // early return in ReactionRule::initialize leaves no bond record, so the
    // writer derives the bonds from the product patterns.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k1 1.0
end parameters
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    A(b) 10
    B(a) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    synth: 0->A(b!1).B(a!1) k1
end reaction rules
end model
)");
    const std::string expected =
        "          <Add id=\"RR1_PP1_M1\"/>\n"
        "          <Add id=\"RR1_PP1_M2\"/>\n"
        "          <AddBond site1=\"RR1_PP1_M1_C1\" site2=\"RR1_PP1_M2_C1\"/>\n";
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(expected));
}

TEST_CASE("XmlWriter wraps TotalRate elementary rates in a Function") {
    // BNG2 RateLaw.pm newRateLaw forces even a plain constant rate into a
    // generated zero-argument function when TotalRate is present (force_fcn).
    const std::string xml = writeXml(R"(
begin model
begin parameters
    kf 1.0
    kr 2.0
end parameters
begin molecule types
    A(s)
    B(t)
end molecule types
begin seed species
    A(s) 10
    B(t) 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    tr: A(s)+B(t)<->A(s!1).B(t!1) kf, kr TotalRate
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<RateLaw id=\"RR1_RateLaw\" type=\"Function\" totalrate=\"1\""));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<RateLaw id=\"RR1r_RateLaw\" type=\"Function\" totalrate=\"1\""));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Function id=\"__bng3_reaction_rate_RR1\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Reference name=\"kf\" type=\"Constant\"/>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<Expression>kf</Expression>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<Expression>kr</Expression>"));
    CHECK(xml.find("type=\"Ele\"") == std::string::npos);
}

TEST_CASE("XmlWriter lists call-site tags for local function rates") {
    // BNG2 writes the call-site tag (x) in the RateLaw argument list, never
    // the declared formal (z). ft_local_functions used to fail with
    // "dynamic rate argument 'z' has no scoped reactant".
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k_base 1.0
    J 0.5
end parameters
begin molecule types
    S(nbr,sp~up~dn)
end molecule types
begin seed species
    S(nbr!1,sp~dn).S(nbr!1,sp~dn) 1
end seed species
begin observables
    Molecules NbrUp S(nbr!0).S(nbr!0,sp~up)
end observables
begin functions
    flipUp(z) = k_base * exp(-J * (1 - NbrUp(z)))
end functions
begin reaction rules
    S%x(sp~dn) -> S%x(sp~up) flipUp(x)
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1_RP1_M1\"/>"));
    CHECK(xml.find("dynamic rate argument") == std::string::npos);
    // The declared formal stays on the Function definition, not the RateLaw.
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring("<Function id=\"flipUp\""));
}

TEST_CASE("XmlWriter distinguishes leading species labels from molecule labels") {
    const std::string speciesScoped = writeXml(R"(
begin model
begin molecule types
    A(s~u~p)
    I(i)
end molecule types
begin seed species
    A(s~u!1).I(i!1) 1
end seed species
begin observables
    Molecules I_total I()
end observables
begin functions
    f(x) = I_total(x)
end functions
begin reaction rules
    %x:A(s~u!1).I(i!1) -> A(s~p!1).I(i!1) f(x)
end reaction rules
end model
)");
    CHECK_THAT(speciesScoped, Catch::Matchers::ContainsSubstring(
        "<ReactantPattern id=\"RR1_RP1\" label=\"x\">"));
    CHECK_THAT(speciesScoped, Catch::Matchers::ContainsSubstring(
        "<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1_RP1\"/>"));
    CHECK(speciesScoped.find("<Molecule id=\"RR1_RP1_M1\" name=\"A\" label=\"x\"") ==
          std::string::npos);

    const std::string moleculeScoped = writeXml(R"(
begin model
begin molecule types
    A(s~u~p)
    I(i)
end molecule types
begin seed species
    A(s~u!1).I(i!1) 1
end seed species
begin observables
    Molecules I_total I()
end observables
begin functions
    f(x) = I_total(x)
end functions
begin reaction rules
    A%x(s~u!1).I(i!1) -> A%x(s~p!1).I(i!1) f(x)
end reaction rules
end model
)");
    CHECK_THAT(moleculeScoped, Catch::Matchers::ContainsSubstring(
        "<ReactantPattern id=\"RR1_RP1\">"));
    CHECK_THAT(moleculeScoped, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"RR1_RP1_M1\" name=\"A\" label=\"x\">"));
    CHECK_THAT(moleculeScoped, Catch::Matchers::ContainsSubstring(
        "<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1_RP1_M1\"/>"));
    CHECK_THAT(moleculeScoped, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"RR1_PP1_M1\" name=\"A\" label=\"x\">"));
    CHECK_THAT(moleculeScoped, Catch::Matchers::ContainsSubstring(
        "<MapItem sourceID=\"RR1_RP1_M1\" targetID=\"RR1_PP1_M1\"/>"));
}

TEST_CASE("XmlWriter binds reverse species scopes to reverse reactants") {
    const std::string xml = writeXml(R"(
begin model
begin molecule types
    A()
    B()
end molecule types
begin observables
    Molecules A_total A()
    Molecules B_total B()
end observables
begin functions
    fromA(x) = A_total(x)
    fromB(x) = B_total(x)
end functions
begin reaction rules
    %x:A() <-> %x:B() fromA(x), fromB(x)
end reaction rules
end model
)");

    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1_RP1\"/>"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Argument id=\"x\" type=\"ObjectReference\" value=\"RR1r_RP1\"/>"));
}

TEST_CASE("XmlWriter refuses ambiguous local scope anchors") {
    auto model = parser::parseModel(R"(
begin model
begin molecule types
    A()
    B()
    C()
end molecule types
begin functions
    f(x) = 1
end functions
begin reaction rules
    A%x() + B%x() -> C() f(x)
end reaction rules
end model
)");
    REQUIRE(model != nullptr);
    CHECK_THROWS(io::XmlWriter::write(*model));
}
TEST_CASE("reactant unit conversion helper mirrors NetWriter") {
    using bng::compile::ReactantCompartment;
    using bng::compile::reactantUnitConversionFactor;

    // Bimolecular in one volume V -> 1/V.
    CHECK(reactantUnitConversionFactor({{3, 3.0}, {3, 3.0}}) ==
          Catch::Approx(1.0 / 3.0));
    // Unimolecular -> no conversion (the single compartment is the anchor).
    CHECK_FALSE(reactantUnitConversionFactor({{3, 3.0}}).has_value());
    // No compartmented reactants -> no conversion.
    CHECK_FALSE(reactantUnitConversionFactor({}).has_value());
    // A surface is the anchor, so a paired volume stays in the denominator.
    CHECK(reactantUnitConversionFactor({{2, 2.0}, {3, 5.0}}) ==
          Catch::Approx(1.0 / 5.0));
    // Distinct volume sizes -> 1/product of the remaining size after the anchor.
    CHECK(reactantUnitConversionFactor({{3, 2.0}, {3, 5.0}}) ==
          Catch::Approx(1.0 / 5.0));
    // Two surfaces anchor one, keeping the other.
    CHECK(reactantUnitConversionFactor({{2, 2.0}, {2, 5.0}}) ==
          Catch::Approx(1.0 / 5.0));
}

TEST_CASE("XmlWriter preserves reactant volume provenance for runtime conversion") {
    // NFsim applies the Rxn.pm 1/product(sizes) factor when it loads the rule,
    // using the current compartment sizes. The writer must therefore keep the
    // source rate expression and the compartment's size parameter instead of
    // baking a load-time numeric factor, so a later parameter update can
    // rescale the rate exactly once.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k 0.8
    Vc 3
end parameters
begin compartments
    cell 3 Vc
end compartments
begin molecule types
    A()
    D()
end molecule types
begin seed species
    @cell:A() 20
end seed species
begin reaction rules
    @cell:A() + @cell:A() -> @cell:D() k
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "sizeParameter=\"Vc\""));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<RateConstant value=\"k\"/>"));
    CHECK(xml.find("<RateConstant value=\"0.26666666666666666\"/>") ==
          std::string::npos);

    const std::string unitVolumeXml = writeXml(R"(
begin model
begin parameters
    k 0.8
end parameters
begin compartments
    cell 3 1
end compartments
begin molecule types
    A()
    D()
end molecule types
begin seed species
    @cell:A() 20
end seed species
begin reaction rules
    @cell:A() + @cell:A() -> @cell:D() k
end reaction rules
end model
)");
    CHECK_THAT(unitVolumeXml, Catch::Matchers::ContainsSubstring(
        "<RateConstant value=\"k\"/>"));
}

TEST_CASE("XmlWriter parses single-colon prefix compartments in observables and rules") {
    // BNGL source uses the single-colon '@Comp:M()' prefix. The writer must
    // split it into a separate molecule name and compartment attribute rather
    // than folding it into a bogus name/compartment pair; native NFsim rejects
    // the malformed form. Both observables and reaction rules are covered, as
    // is the legacy molecule-suffix 'M()@Comp' spelling.
    const std::string xml = writeXml(R"(
begin model
begin parameters
    k1 1.0
end parameters
begin compartments
    cell 3 3
end compartments
begin molecule types
    M_A()
    M_D()
end molecule types
begin seed species
    @cell:M_A() 10
end seed species
begin observables
    Molecules A_obs @cell:M_A()
    Molecules D_obs M_D()@cell
end observables
begin reaction rules
    @cell:M_A() -> @cell:M_D() k1
end reaction rules
end model
)");
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Pattern id=\"O1_P1\" compartment=\"cell\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"O1_P1_M1\" name=\"M_A\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"O2_P1_M1\" name=\"M_D\" compartment=\"cell\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<ReactantPattern id=\"RR1_RP1\" compartment=\"cell\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"RR1_RP1_M1\" name=\"M_A\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<ProductPattern id=\"RR1_PP1\" compartment=\"cell\">"));
    CHECK_THAT(xml, Catch::Matchers::ContainsSubstring(
        "<Molecule id=\"RR1_PP1_M1\" name=\"M_D\">"));
    CHECK(xml.find("compartment=\"cell:M_A\"") == std::string::npos);
    CHECK(xml.find("name=\"\"") == std::string::npos);
}
