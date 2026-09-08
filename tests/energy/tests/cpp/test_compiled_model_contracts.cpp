#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include <utility>

#include "compile/Capabilities.hpp"
#include "compile/Document.hpp"
#include "compile/CompiledModel.hpp"
#include "compile/SymbolTable.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("typed symbol table resolves names and rejects duplicate declarations") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
end molecule types
begin observables
  Molecules A_count A(x)
end observables
begin reaction rules
  r: A(x) -> A(x) k
end reaction rules
)BNG");
    REQUIRE(model != nullptr);

    const auto symbols = bng::compile::SymbolTable::fromModel(*model);
    const auto parameter = symbols.resolveParameter("k");
    const auto molecule = symbols.resolveMoleculeType("A");
    const auto observable = symbols.resolveObservable("A_count");
    REQUIRE(parameter.has_value());
    REQUIRE(molecule.has_value());
    REQUIRE(observable.has_value());
    CHECK(parameter->value() == 0);
    CHECK(molecule->value() == 0);
    CHECK(observable->value() == 0);
    CHECK(symbols.resolveParameter("missing") == std::nullopt);
    CHECK(symbols.resolve(bng::compile::SymbolKind::MoleculeType, "A").has_value());
    CHECK(symbols.diagnostics().empty());

    bng::ast::Model duplicateModel;
    duplicateModel.addMoleculeType(bng::ast::MoleculeType("A", {}));
    duplicateModel.addMoleculeType(bng::ast::MoleculeType("A", {}));
    const auto duplicateSymbols = bng::compile::SymbolTable::fromModel(duplicateModel);
    REQUIRE(duplicateSymbols.diagnostics().size() == 1);
    CHECK(duplicateSymbols.diagnostics().front().category ==
          bng::compile::ValidationCategory::Symbols);
    CHECK(duplicateSymbols.diagnostics().front().severity == bng::compile::Severity::Error);
}

TEST_CASE("semantic feature inference and capability reports are explicit") {
    auto model = bng::parser::parseModel(R"BNG(
begin compartments
  cell 3 1.0
end compartments
begin molecule types
  A(state~0~1)
end molecule types
begin seed species
  A(state~0)@cell 1
end seed species
begin energy patterns
  A(state~1) G
end energy patterns
begin reaction rules
  A(state~0) -> A(state~1) 1
end reaction rules
begin actions
  generate_network({overwrite=>1})
end actions
)BNG");
    REQUIRE(model != nullptr);

    const auto features = bng::compile::featuresUsed(*model);
    CHECK(features.contains(bng::compile::Feature::EnergyPatterns));
    CHECK(features.contains(bng::compile::Feature::Compartments));
    CHECK(features.contains(bng::compile::Feature::IntegerStates));
    CHECK(features.contains(bng::compile::Feature::ProtocolActions));

    bng::compile::CapabilityReport report;
    report.set(bng::compile::Feature::EnergyPatterns, bng::compile::CapabilityState::Native);
    report.set(bng::compile::Feature::TableFunctions, bng::compile::CapabilityState::Unsupported);
    bng::compile::Diagnostic diagnostic;
    diagnostic.code = bng::compile::DiagnosticCode::UnsupportedFeature;
    diagnostic.category = bng::compile::ValidationCategory::BackendCapability;
    diagnostic.severity = bng::compile::Severity::Error;
    diagnostic.message = "table functions are unavailable";
    report.addDiagnostic(std::move(diagnostic));

    CHECK(report.state(bng::compile::Feature::EnergyPatterns) == bng::compile::CapabilityState::Native);
    CHECK(report.state(bng::compile::Feature::TableFunctions) == bng::compile::CapabilityState::Unsupported);
    CHECK_FALSE(report.isSupported());
    REQUIRE(report.diagnostics().size() == 1);
}

TEST_CASE("capability preflight rejects population maps for direct NFsim") {
    bng::ast::Model model;
    model.addPopulationMap({"pm", "A()", "lumped", {}});

    const auto report = bng::compile::capabilitiesFor(
        model, bng::compile::BackendKind::NFsim);
    CHECK_FALSE(report.isSupported());
    CHECK(report.state(bng::compile::Feature::PopulationMaps) ==
          bng::compile::CapabilityState::Unsupported);
    REQUIRE(report.diagnostics().size() == 1);
    CHECK(report.diagnostics().front().code ==
          bng::compile::DiagnosticCode::UnsupportedFeature);
}

TEST_CASE("compiled entities expose namespace-specific dense IDs") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin observables
 Molecules count A(x)
end observables
begin seed species
 A(x) 1
end seed species
begin reaction rules
 r: A(x) -> A(x) 1
end reaction rules
)BNG");
    REQUIRE(model);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    CHECK(compiled.rules()[0].id().value() == 0);
    CHECK(compiled.observables()[0].id.value() == 0);
    CHECK(compiled.seeds()[0].id.value() == 0);
}

TEST_CASE("compiled model resolves function bodies with lexical arguments") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
 k 1
end parameters
begin functions
 local(x) = k + x
end functions
)BNG");
    REQUIRE(model);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.diagnostics().empty());
    REQUIRE(compiled.functions().size() == 1);
    CHECK(compiled.functions()[0].id.value() == 0);
    REQUIRE(compiled.functions()[0].expression.arguments.size() == 2);
    CHECK(compiled.functions()[0].expression.arguments[0].kind ==
          bng::compile::ResolvedExpressionKind::ParameterRef);
    CHECK(compiled.functions()[0].expression.arguments[1].kind ==
          bng::compile::ResolvedExpressionKind::LocalRef);
    CHECK(compiled.functions()[0].expression.arguments[1].localName == "x");
}

TEST_CASE("Document separates compiled model metadata from simulation protocol") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x) 1
end seed species
begin reaction rules
  r: A(x) -> A(x) k
end reaction rules
begin protocol
  simulate_nf({t_end=>1})
end protocol
)BNG");
    REQUIRE(model);
    REQUIRE(model->getSimulationProtocol().size() == 1);
    const bng::compile::Document document(*model);
    CHECK(document.model().rules().size() == 1);
    CHECK(document.valid());
    CHECK(document.diagnostics().empty());
    REQUIRE(document.protocol().actions.size() == 1);
    CHECK(document.protocol().actions.front().name == "simulate_nf");
    model->addProtocolAction({"later_action", {}});
    CHECK(document.protocol().actions.size() == 1);
}

TEST_CASE("CompiledModel preserves source rule ordering and energy-factor provenance") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  e1 1
  e2 2
end parameters
begin molecule types
  A(x~U~P,y)
  B(z)
end molecule types
begin energy patterns
  ep1: A(x~P) e1
  ep2: A(y!1).B(z!1) e2
end energy patterns
begin observables
  Molecules phospho A(x~P)
  Species complexes A(y!1).B(z!1)
end observables
begin seed species
  A(x~U,y) 10
  B(z) 10
end seed species
begin reaction rules
  phos: A(x~U) -> A(x~P) 1
  bind: A(y) + B(z) -> A(y!1).B(z!1) 2
end reaction rules
)BNG");
    REQUIRE(model != nullptr);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 2);
    CHECK(compiled.features().contains(bng::compile::Feature::EnergyPatterns));
    CHECK(compiled.rules()[0].name() == model->getReactionRules()[0].getRuleName());
    CHECK(compiled.rules()[0].label() == "phos:");
    CHECK(compiled.rules()[1].name() == model->getReactionRules()[1].getRuleName());
    CHECK(compiled.rules()[1].label() == "bind:");
    REQUIRE(compiled.rules()[0].reactantPatterns().size() == 1);
    CHECK(compiled.rules()[0].reactantPatterns()[0].hasSite("A", "x"));
    REQUIRE(compiled.energyFactors().size() == 2);
    CHECK(compiled.energyFactors()[0].label == "ep1");
    CHECK(compiled.energyFactors()[1].label == "ep2");
    CHECK(compiled.energyFactors()[0].pattern.hasSite("A", "x"));
    CHECK_FALSE(compiled.energyFactors()[0].structuralFingerprint.empty());
    CHECK_FALSE(compiled.energyFactors()[1].structuralFingerprint.empty());
    REQUIRE(compiled.observables().size() == 2);
    CHECK(compiled.observables()[0].name == "phospho");
    REQUIRE(compiled.observables()[0].patterns.size() == 1);
    CHECK(compiled.observables()[0].patterns[0].hasSite("A", "x"));
    REQUIRE(compiled.seeds().size() == 2);
    CHECK(compiled.seeds()[0].pattern.hasSite("A", "x"));
    CHECK(compiled.seeds()[0].amountExpression == "10");

    const bng::compile::CompiledModel compiledAgain(*model);
    CHECK(compiledAgain.rules().size() == compiled.rules().size());
    CHECK(compiledAgain.energyFactors()[1].structuralFingerprint ==
          compiled.energyFactors()[1].structuralFingerprint);

    bng::ast::Model invalidModel;
    invalidModel.addObservable(bng::ast::Observable("bad", "Molecules", {"A("}));
    const bng::compile::CompiledModel invalidCompiled(invalidModel);
    REQUIRE(invalidCompiled.diagnostics().size() == 1);
    CHECK(invalidCompiled.diagnostics().front().category ==
          bng::compile::ValidationCategory::Patterns);
    CHECK(invalidCompiled.diagnostics().front().severity ==
          bng::compile::Severity::Error);
    const bng::compile::Document invalidDocument(invalidModel);
    CHECK_FALSE(invalidDocument.valid());
}

TEST_CASE("CompiledRule reports both endpoints of a bond mutation") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
  A(x)
  B(y)
end molecule types
begin seed species
  A(x) 1
  B(y) 1
end seed species
begin reaction rules
  r: A(x) + B(y) -> A(x!1).B(y!1) 1
end reaction rules
)BNG");
    REQUIRE(model != nullptr);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    CHECK(compiled.rules()[0].affectedComponents().size() == 2);
}

TEST_CASE("CompiledRule preserves typed and unknown modifiers") {
    auto model = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
end molecule types
begin seed species
  A(x) 1
end seed species
begin reaction rules
  r: A(x) -> A(x) k DeleteMolecules MatchOnce TotalRate include_products(1,A(x))
end reaction rules
)BNG");
    REQUIRE(model != nullptr);
    const bng::compile::CompiledModel compiled(*model);
    REQUIRE(compiled.rules().size() == 1);
    REQUIRE(compiled.rules()[0].modifiers().size() == 4);
    CHECK(compiled.rules()[0].modifiers()[0].kind ==
          bng::compile::ModifierKind::DeleteMolecules);
    CHECK(compiled.rules()[0].modifiers()[1].kind ==
          bng::compile::ModifierKind::MatchOnce);
    CHECK(compiled.rules()[0].modifiers()[2].kind ==
          bng::compile::ModifierKind::TotalRate);
    CHECK(compiled.rules()[0].modifiers()[3].kind ==
          bng::compile::ModifierKind::IncludeProducts);
    CHECK(compiled.rules()[0].modifiers()[3].source == "include_products(1,A(x))");
    REQUIRE(compiled.rules()[0].filters().size() == 1);
    CHECK(compiled.rules()[0].filters()[0].include);
    CHECK(compiled.rules()[0].filters()[0].products);
    CHECK(compiled.rules()[0].filters()[0].patternIndex == 0);
    REQUIRE(compiled.rules()[0].filters()[0].patterns.size() == 1);
    CHECK(compiled.rules()[0].filters()[0].patterns[0].hasSite("A", "x"));

    bng::ast::Model malformed;
    malformed.addReactionRule(bng::ast::ReactionRule(
        "bad", "bad:", {}, {}, {bng::ast::Expression::number(1.0)},
        {"include_products(0,A())"}, false));
    const bng::compile::CompiledModel malformedCompiled(malformed);
    REQUIRE(malformedCompiled.diagnostics().size() == 1);
    CHECK(malformedCompiled.diagnostics().front().category ==
          bng::compile::ValidationCategory::Rules);
}

TEST_CASE("state change contributes exactly one affected component") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 1
end seed species
begin reaction rules
 flip: A(s~U)->A(s~P) 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    REQUIRE(c.rules().size()==1);
    REQUIRE(c.rules()[0].mutations().size()==1);
    CHECK(c.rules()[0].mutations()[0].kind==bng::compile::MutationKind::ChangeState);
    CHECK(c.rules()[0].affectedComponents().size()==1);
}

TEST_CASE("unbinding reports both affected bond endpoints") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
 B(y)
end molecule types
begin seed species
 A(x!1).B(y!1) 1
end seed species
begin reaction rules
 unbind: A(x!1).B(y!1)->A(x)+B(y) 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    const auto& r=c.rules().front();
    CHECK(std::any_of(r.mutations().begin(),r.mutations().end(),[](const auto&m){return m.kind==bng::compile::MutationKind::DeleteBond;}));
    CHECK(r.affectedComponents().size()==2);
}

TEST_CASE("implicit whole-species deletion requires conservative invalidation") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 1
end seed species
begin reaction rules
 die: A(x)->0 1
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    const auto& r=c.rules().front();
    // ReactionRule::initialize returns before operations for A -> 0.
    // The native adapter handles whole-species deletion separately.
    CHECK(r.mutations().empty());
    CHECK(r.requiresConservativeInvalidation());
}

TEST_CASE("bidirectional source rule remains marked bidirectional and retains both rates") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(s~U~P)
end molecule types
begin seed species
 A(s~U) 1
end seed species
begin reaction rules
 flip: A(s~U)<->A(s~P) 1,2
end reaction rules
)BNG");
    REQUIRE(model);
    bng::compile::CompiledModel c(*model);
    REQUIRE(c.rules().size()==1);
    CHECK(c.rules()[0].isBidirectional());
    CHECK(c.rules()[0].rateLaws().size()==2);
}
