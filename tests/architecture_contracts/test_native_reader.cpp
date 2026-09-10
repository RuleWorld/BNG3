#include <algorithm>
#include <memory>
#include <catch2/catch_test_macros.hpp>
#include "NFcore.hh"
#include "NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"
#include "nfsim_native_reader.hh"
#include "legacy_bridge.hh"
#include "engine.hh"

namespace {
std::unique_ptr<NFcore::System> systemFor(const std::string& rule) {
    auto model = bng::parser::parseModel(
        "begin molecule types\n A(s~U~P,b)\n B(a)\nend molecule types\n"
        "begin seed species\n A(s~U,b) 2\n B(a) 2\nend seed species\n"
        "begin reaction rules\n" + rule + "\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> compartmentSystemFor(const std::string& rule) {
    auto model = bng::parser::parseModel(
        "begin compartments\n c1 3 1.0\n c2 3 1.0\nend compartments\n"
        "begin molecule types\n A(site)\nend molecule types\n"
        "begin seed species\n @c1:A(site) 1\nend seed species\n"
        "begin reaction rules\n" + rule + "\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> populationSystemFor(const std::string& rule) {
    auto model = bng::parser::parseModel(
        "begin molecule types\n P() population\nend molecule types\n"
        "begin seed species\n P() 5\nend seed species\n"
        "begin reaction rules\n" + rule + "\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> moveConnectedSystem() {
    auto model = bng::parser::parseModel(
        "begin compartments\n c1 3 1.0\n c2 3 1.0\nend compartments\n"
        "begin molecule types\n A(site)\n B(site)\nend molecule types\n"
        "begin seed species\n @c1:A(site!1).B(site!1) 1\nend seed species\n"
        "begin reaction rules\n @c1:A(site!1).B(site!1) -> "
        "@c2:A(site!1).B(site!1) 1 MoveConnected\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> symmetricGraphSystem() {
    auto model = bng::parser::parseModel(R"BNGL(
begin molecule types
 A(x~U~P,x~U~P)
 B(y)
end molecule types
begin seed species
 A(x~U!1,x~U).B(y!1) 1
end seed species
begin reaction rules
 flip: A(x~U!1,x~U).B(y!1) -> A(x~P!1,x~U).B(y!1) 1
end reaction rules
)BNGL");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> multiSymmetricGraphSystem() {
    auto model = bng::parser::parseModel(R"(
begin molecule types
 A(x,x)
 B(y)
 C(z)
end molecule types
begin seed species
 A(x!1,x!2).B(y!1).C(z!2) 1
end seed species
begin reaction rules
 swap: A(x!1,x!2).B(y!1).C(z!2) -> A(x!1,x!2).B(y!1).C(z!2) 1
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> symmetricSystem() {
    auto model = bng::parser::parseModel(R"(
begin molecule types
 A(x,x)
 B(y)
end molecule types
begin seed species
 A(x,x) 20
 B(y) 20
end seed species
begin reaction rules
 bind: A(x) + B(y) -> A(x!1).B(y!1) 1
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> stateGraphSystem() {
    auto model = bng::parser::parseModel(
        "begin molecule types\n A(s~U~P,b)\n B(a,s~U~P)\nend molecule types\n"
        "begin seed species\n A(s~U,b!1).B(a!1,s~P) 1\nend seed species\n"
        "begin reaction rules\n flip: A(s~U,b!1).B(a!1,s~P) -> "
        "A(s~P,b!1).B(a!1,s~P) 2\nend reaction rules\n");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> localFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin parameters
 k 2.0
end parameters
begin molecule types
 A()
 C()
end molecule types
begin seed species
 A() 1
end seed species
begin observables
 Molecules atotal A()
end observables
begin functions
 f(x) = k*atotal(x)
end functions
begin reaction rules
 %x::A() -> %x::A() + C() f(x)
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> complexGlobalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin molecule types
 A(b)
 B(a)
 C()
end molecule types
begin seed species
 A(b) 1
 B(a) 1
end seed species
begin observables
 Molecules ab A(b!1).B(a!1)
end observables
begin functions
 rate() = 1*ab + 0
end functions
begin reaction rules
 A(b) -> A(b) + C() rate
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> complexScopedLocalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin molecule types
 A(b)
 B(a)
 C()
end molecule types
begin seed species
 A(b) 1
 B(a) 1
end seed species
begin observables
 Molecules ab A(b!1).B(a!1)
end observables
begin functions
 f(x) = ab(x)
end functions
begin reaction rules
 %x::A(b) -> %x::A(b) + C() f(x)
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> stateScopedLocalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin parameters
 k 2.0
end parameters
begin molecule types
 A(s~U~P)
 C()
end molecule types
begin seed species
 A(s~P) 1
end seed species
begin observables
 Molecules active A(s~P)
end observables
begin functions
 f(x) = k*active(x)
end functions
begin reaction rules
 %x::A(s~P) -> %x::A(s~P) + C() f(x)
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> stateScopedGlobalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin parameters
 k 2.0
end parameters
begin molecule types
 A(s~U~P)
 C()
end molecule types
begin seed species
 A(s~P) 1
 A(s~U) 1
end seed species
begin observables
 Molecules active A(s~P)
end observables
begin functions
 rate() = k*active
end functions
begin reaction rules
 A(s~P) -> A(s~P) + C() rate
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> compartmentScopedGlobalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin compartments
 c1 3 1.0
 c2 3 1.0
end compartments
begin molecule types
 A()
end molecule types
begin seed species
 @c1:A() 1
 @c2:A() 1
end seed species
begin observables
 Molecules atotal @c1:A()
end observables
begin functions
 rate() = atotal
end functions
begin reaction rules
 A() -> A() rate
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> localFunctionProductSystem() {
    auto model = bng::parser::parseModel(R"BNGL(
begin parameters
 kA 2.0
 kB 3.0
end parameters
begin molecule types
 A()
 B()
end molecule types
begin seed species
 A() 1
 B() 1
end seed species
begin observables
 Molecules atotal A()
 Molecules btotal B()
end observables
begin functions
 fA(x) = kA*atotal(x)
 fB(y) = kB*btotal(y)
end functions
begin reaction rules
 %x::A() + %y::B() -> %x::A() + %y::B() FunctionProduct("fA(x)", "fB(y)")
end reaction rules
)BNGL");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> nestedLocalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin parameters
 k 2.0
end parameters
begin molecule types
 A()
 C()
end molecule types
begin seed species
 A() 1
end seed species
begin observables
 Molecules atotal A()
end observables
begin functions
 g(x) = k*atotal(x)
 f(x) = g(x) + 1
end functions
begin reaction rules
 %x::A() -> %x::A() + C() f(x)
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> globalFunctionSystem() {
    auto model = bng::parser::parseModel(R"BNGL(
begin parameters
 k 2.0
end parameters
begin molecule types
 A()
 C()
end molecule types
begin seed species
 A() 2
end seed species
begin observables
 Molecules atotal A()
end observables
begin functions
 rate() = k*atotal + time()
end functions
begin reaction rules
 A() -> A() rate
end reaction rules
)BNGL");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}

std::unique_ptr<NFcore::System> nestedGlobalFunctionSystem() {
    auto model = bng::parser::parseModel(R"(
begin parameters
 k 2.0
end parameters
begin molecule types
 A()
end molecule types
begin seed species
 A() 2
end seed species
begin observables
 Molecules atotal A()
end observables
begin functions
 base() = k*atotal
 rate() = base() + 1
end functions
begin reaction rules
 A() -> A() rate
end reaction rules
)");
    REQUIRE(model);
    int traversal = 0;
    auto system = std::unique_ptr<NFcore::System>(
        NFinput::buildSystemFromAst(*model, false, 100, false, traversal));
    REQUIRE(system);
    return system;
}
}

TEST_CASE("native NFcore2 reader preserves root state and transformation") {
    auto system = systemFor("flip: A(s~U)->A(s~P) 2");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.base_rate == 2);
    CHECK_FALSE(rule.uses_connected_to);
    REQUIRE(rule.dependencies.size() >= 1);
    const auto state_dependency = std::find_if(
        rule.dependencies.begin(), rule.dependencies.end(), [](const auto& dependency) {
            return dependency.kind == NFcore2::NATIVE_STATE_REQUIRED;
        });
    REQUIRE(state_dependency != rule.dependencies.end());
    CHECK(state_dependency->state == 0);
    REQUIRE(rule.transforms.size() == 1);
    CHECK(rule.transforms[0].kind == NFcore2::NATIVE_STATE_CHANGE);
    CHECK(rule.transforms[0].new_value == 1);
}

TEST_CASE("native NFcore2 reader resolves both halves of a binding transform") {
    auto system = systemFor("bind: A(b)+B(a)->A(b!1).B(a!1) 3");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK_FALSE(rule.uses_connected_to);
    REQUIRE(rule.dependencies.size() == 2);
    REQUIRE(rule.transforms.size() == 1);
    CHECK(rule.transforms[0].kind == NFcore2::NATIVE_BINDING);
    CHECK(rule.transforms[0].reactant != rule.transforms[0].other_reactant);
}

TEST_CASE("native NFcore2 reader captures internal graph topology") {
    auto system = systemFor("flip: A(s~U,b!1).B(a!1)->A(s~P,b!1).B(a!1) 2");
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_connected_to);
    REQUIRE(snapshot.rules[0].graph_patterns.size() == 1);
    CHECK(snapshot.rules[0].graph_patterns[0].nodes.size() == 2);
    CHECK(snapshot.rules[0].graph_patterns[0].edges.size() == 1);
}

TEST_CASE("native NFcore2 reader preserves symmetric internal graph automorphisms") {
    auto system = symmetricGraphSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() >= 1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == snapshot.rules.size());
    CHECK(lowered.fallback_rule_count == 0);
    for (const auto& rule : lowered.rules) CHECK(rule.supported());
    REQUIRE(snapshot.rules[0].graph_patterns.size() >= 1);
    const auto& graph = snapshot.rules[0].graph_patterns[0];
    REQUIRE(graph.nodes.size() == 2);
    REQUIRE(graph.nodes[0].symmetric_constraints.size() >= 1);
    CHECK(graph.nodes[0].symmetric_constraints[0].components.size() == 2);
    // The symmetric bond is represented by its orbit constraint so a concrete
    // component index cannot pin one representative of the equivalence class.
    CHECK(graph.edges.empty());
}

TEST_CASE("native NFcore2 reader preserves symmetric component automorphisms") {
    auto system = symmetricSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() >= 1);
    for (const auto& rule : snapshot.rules) CHECK_FALSE(rule.uses_connected_to);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == snapshot.rules.size());
    CHECK(lowered.fallback_rule_count == 0);
    REQUIRE(lowered.rules.size() == snapshot.rules.size());
    for (const auto& rule : lowered.rules) CHECK(rule.supported());
}

TEST_CASE("native NFcore2 matcher preserves multi-edge equivalent-site automorphisms") {
    auto system = multiSymmetricGraphSystem();
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    REQUIRE(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto b = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    const auto c = engine.state().molecules(NFcore2::MoleculeTypeId(2)).create();
    // Swap the two equivalent sites relative to the source spelling. The
    // legacy matcher treats the sites as an automorphism, so this is still a
    // valid match of the same graph rule.
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        a, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(2), c));
    engine.state().molecules(NFcore2::MoleculeTypeId(2)).setBondRef(
        c, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        a, 1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setBondRef(
        b, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
}

TEST_CASE("native NFcore2 reader preserves internal graph-node state constraints") {
    auto system = stateGraphSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    REQUIRE(snapshot.rules[0].graph_patterns.size() == 1);
    const auto& graph = snapshot.rules[0].graph_patterns[0];
    const auto childNode = std::find_if(graph.nodes.begin(), graph.nodes.end(), [](const auto& node) {
        return node.molecule_type == 1;
    });
    REQUIRE(childNode != graph.nodes.end());
    CHECK(childNode->state_component == 1);
    CHECK(childNode->state == 1);

    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    const auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto b = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        a, 1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setBondRef(
        b, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setStateWord(b, 1, 1);
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setStateWord(b, 1, 0);
    CHECK_FALSE(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
}

TEST_CASE("native NFcore2 graph nodes preserve multiple state constraints and exclusions") {
    NFcore2::NativeModelSnapshot source;
    NFcore2::NativeMoleculeTypeSnapshot a; a.name = "A"; a.component_count = 2;
    NFcore2::NativeMoleculeTypeSnapshot b; b.name = "B"; b.component_count = 2;
    source.molecule_types.push_back(a); source.molecule_types.push_back(b);
    NFcore2::NativeReactionSnapshot rule;
    rule.name = "graph_states"; rule.base_rate = 1.0; rule.reactant_types.push_back(0);
    NFcore2::NativeGraphPatternSnapshot graph;
    NFcore2::NativeGraphNodeSnapshot root; root.molecule_type = 0; root.reactant = 0;
    NFcore2::NativeGraphNodeSnapshot child; child.molecule_type = 1;
    child.state_constraints.push_back(std::make_pair(0u, 1));
    child.state_constraints.push_back(std::make_pair(1u, 2));
    child.excluded_states.push_back(std::make_pair(0u, 3));
    graph.nodes.push_back(root); graph.nodes.push_back(child);
    graph.edges.push_back(NFcore2::NativeGraphEdgeSnapshot());
    graph.edges.back().first_node = 0; graph.edges.back().first_component = 0;
    graph.edges.back().second_node = 1; graph.edges.back().second_component = 0;
    rule.graph_patterns.push_back(graph); source.rules.push_back(rule);
    const auto legacy = NFcore2::NFsimSnapshotAdapter::toLegacy(source);
    REQUIRE(legacy.rules.size() == 1);
    CHECK(legacy.rules[0].graph_patterns[0].nodes[1].state_constraints.size() == 2);
    CHECK(legacy.rules[0].graph_patterns[0].nodes[1].excluded_states.size() == 1);
    const auto lowered = NFcore2::LegacyLowerer::lower(legacy);
    REQUIRE(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    const auto left = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto right = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        left, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), right));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setBondRef(
        right, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), left));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setStateWord(right, 0, 1);
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setStateWord(right, 1, 2);
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), left));
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setStateWord(right, 1, 3);
    CHECK_FALSE(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
}

TEST_CASE("native NFcore2 graph patterns preserve connectedTo links") {
    NFcore2::NativeModelSnapshot source;
    NFcore2::NativeMoleculeTypeSnapshot a; a.name = "A"; a.component_count = 2;
    NFcore2::NativeMoleculeTypeSnapshot b; b.name = "B"; b.component_count = 1;
    NFcore2::NativeMoleculeTypeSnapshot c; c.name = "C"; c.component_count = 1;
    source.molecule_types.push_back(a); source.molecule_types.push_back(b);
    source.molecule_types.push_back(c);
    NFcore2::NativeReactionSnapshot rule;
    rule.name = "graph_connected"; rule.base_rate = 1.0; rule.reactant_types.push_back(0);
    NFcore2::NativeGraphPatternSnapshot graph;
    NFcore2::NativeGraphNodeSnapshot root; root.molecule_type = 0; root.reactant = 0;
    NFcore2::NativeGraphNodeSnapshot first; first.molecule_type = 1;
    NFcore2::NativeGraphNodeSnapshot second; second.molecule_type = 2;
    graph.nodes.push_back(root); graph.nodes.push_back(first); graph.nodes.push_back(second);
    graph.edges.push_back(NFcore2::NativeGraphEdgeSnapshot());
    graph.edges.back().first_node = 0; graph.edges.back().first_component = 0;
    graph.edges.back().second_node = 1; graph.edges.back().second_component = 0;
    graph.connected_to.push_back(NFcore2::NativeGraphConnectivitySnapshot(1, 2));
    rule.graph_patterns.push_back(graph); source.rules.push_back(rule);
    const auto legacy = NFcore2::NFsimSnapshotAdapter::toLegacy(source);
    REQUIRE(legacy.rules.size() == 1);
    REQUIRE(legacy.rules[0].graph_patterns[0].connected_to.size() == 1);
    CHECK(legacy.rules[0].graph_patterns[0].connected_to[0].first_node == 1);
    CHECK(legacy.rules[0].graph_patterns[0].connected_to[0].second_node == 2);
    const auto lowered = NFcore2::LegacyLowerer::lower(legacy);
    REQUIRE(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    REQUIRE(lowered.executable.matchers().at(
        lowered.executable.metadata().ruleFamilies()[0].matcher)
        .graphPatterns()[0].connected_to.size() == 1);
    const auto aHandle = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto bHandle = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    const auto cHandle = engine.state().molecules(NFcore2::MoleculeTypeId(2)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        aHandle, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), bHandle));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setBondRef(
        bHandle, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), aHandle));
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        aHandle, 1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(2), cHandle));
    engine.state().molecules(NFcore2::MoleculeTypeId(2)).setBondRef(
        cHandle, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), aHandle));
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), aHandle));
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        aHandle, 1, NFcore2::MoleculeRef());
    engine.state().molecules(NFcore2::MoleculeTypeId(2)).setBondRef(
        cHandle, 0, NFcore2::MoleculeRef());
    CHECK_FALSE(lowered.executable.matchers().at(family.matcher).evaluate(
        engine.state(), engine.scaffolds(), context));
}

TEST_CASE("native NFcore2 reader captures dot-separated connectedTo topology") {
    auto system = systemFor("dot: A(b).B(a) -> A(b).B(a) 1");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_connected_to);
    REQUIRE(snapshot.rules[0].graph_patterns.size() == 1);
    REQUIRE(snapshot.rules[0].graph_patterns[0].connected_to.size() == 1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto b = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    context.setMoleculeAt(1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
}

TEST_CASE("native NFcore2 reader captures zero-reactant synthesis") {
    auto system = systemFor("birth: 0 -> B(a) 1");
    REQUIRE(system->getReaction(0)->getTransformationSet()->getNumOfAddMoleculeTransforms() == 1);
    auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_connected_to);
    REQUIRE(snapshot.rules[0].transforms.size() == 1);
    CHECK(snapshot.rules[0].transforms[0].kind == NFcore2::NATIVE_ADD);
    CHECK(snapshot.rules[0].transforms[0].added_molecule_type == 1);

    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    NFcore2::MatchContext context;
    NFcore2::FeatureDelta delta;
    CHECK(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK(engine.state().molecules(NFcore2::MoleculeTypeId(1)).liveCount() == 1);
}

TEST_CASE("native NFcore2 lowering executes the real state-rule adapter path") {
    auto system = systemFor("flip: A(s~U)->A(s~P) 2");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.rules.size() == 1);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    REQUIRE(lowered.executable.metadata().ruleFamilies().size() == 1);
    CHECK(lowered.executable.metadata().ruleFamilies()[0].members.size() == 1);

    NFcore2::SimulationState state(lowered.executable.metadata());
    const NFcore2::MoleculeHandle molecule =
        state.molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(
        NFcore2::MoleculeTypeId(0), molecule));
    NFcore2::ScaffoldStore scaffolds;
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        state, scaffolds, context));
    NFcore2::FeatureDelta delta;
    lowered.executable.transforms().at(family.transform).execute(
        state, scaffolds, context, delta);
    CHECK(state.molecules(NFcore2::MoleculeTypeId(0)).stateWord(molecule, 0) == 1);
    REQUIRE(delta.changed.size() == 1);
    CHECK(delta.changed[0].value() == 0);
}

TEST_CASE("native NFcore2 lowering executes internal graph topology") {
    auto system = systemFor("flip: A(s~U,b!1).B(a!1)->A(s~P,b!1).B(a!1) 2");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.rules.size() == 1);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    CHECK(lowered.rules[0].supported());
}

TEST_CASE("native NFcore2 reader executes a simple scoped local DOR rate") {
    auto system = localFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_local_function);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto molecule = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(
        NFcore2::MoleculeTypeId(0), molecule));
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member,
                              context) == 2.0);
}

TEST_CASE("native NFcore2 reader preserves local-function pointer scope") {
    auto system = localFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto reference = std::find_if(
        snapshot.rules[0].transforms.begin(), snapshot.rules[0].transforms.end(),
        [](const auto& transform) {
            return transform.kind == NFcore2::NATIVE_LOCAL_FUNCTION_REFERENCE;
        });
    REQUIRE(reference != snapshot.rules[0].transforms.end());
    CHECK(reference->local_function_pointer == "x");
    CHECK(reference->local_function_scope ==
          NFcore::LocalFunction::SPECIES);
}

TEST_CASE("native NFcore2 reader lowers a simple scoped local function descriptor") {
    auto system = localFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    CHECK_FALSE(rule.uses_local_function);
    CHECK_FALSE(rule.rate_expression.empty());
    const auto observable = std::find_if(
        rule.rate_expression_bindings.begin(), rule.rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
        });
    REQUIRE(observable != rule.rate_expression_bindings.end());
    CHECK(observable->reactant == 0);
    CHECK(observable->molecule_type == 0);
    CHECK(observable->scope == NFcore::LocalFunction::SPECIES);
    const auto constant = std::find_if(
        rule.rate_expression_bindings.begin(), rule.rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_CONSTANT &&
                   binding.name == "k";
        });
    REQUIRE(constant != rule.rate_expression_bindings.end());
    CHECK(constant->value == 2.0);

    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
}

TEST_CASE("native NFcore2 reader lowers an exact complex global observable") {
    auto system = complexGlobalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto observable = std::find_if(
        snapshot.rules[0].rate_expression_bindings.begin(),
        snapshot.rules[0].rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT;
        });
    REQUIRE(observable != snapshot.rules[0].rate_expression_bindings.end());
    CHECK(observable->molecule_type == 0);
    CHECK(observable->component == 0);
    CHECK(observable->partner_molecule_type == 1);
    CHECK(observable->partner_component == 0);
    CHECK(observable->scope == -1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
}

TEST_CASE("native NFcore2 reader lowers an exact complex scoped observable") {
    auto system = complexScopedLocalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto observable = std::find_if(
        snapshot.rules[0].rate_expression_bindings.begin(),
        snapshot.rules[0].rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_COMPLEX_MOLECULE_COUNT;
        });
    REQUIRE(observable != snapshot.rules[0].rate_expression_bindings.end());
    CHECK(observable->molecule_type == 0);
    CHECK(observable->partner_molecule_type == 1);
    CHECK(observable->scope == NFcore::LocalFunction::SPECIES);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
}

TEST_CASE("native NFcore2 reader evaluates state-constrained scoped observables") {
    auto system = stateScopedLocalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_local_function);
    const auto observable = std::find_if(
        snapshot.rules[0].rate_expression_bindings.begin(),
        snapshot.rules[0].rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_SPECIES_MOLECULE_COUNT;
        });
    REQUIRE(observable != snapshot.rules[0].rate_expression_bindings.end());
    CHECK(observable->state_value == 1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto molecule = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setStateWord(molecule, 0, 1);
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(
        NFcore2::MoleculeTypeId(0), molecule));
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member,
                               context) == 2.0);
}

TEST_CASE("native NFcore2 reader evaluates state-constrained global observables") {
    auto system = stateScopedGlobalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK_FALSE(snapshot.rules[0].uses_local_function);
    const auto observable = std::find_if(
        snapshot.rules[0].rate_expression_bindings.begin(),
        snapshot.rules[0].rate_expression_bindings.end(),
        [](const auto& binding) {
            return binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT;
        });
    REQUIRE(observable != snapshot.rules[0].rate_expression_bindings.end());
    CHECK(observable->state_value == 1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto p = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto u = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto bound = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto partner = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setStateWord(p, 0, 1);
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setStateWord(u, 0, 0);
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setStateWord(bound, 0, 1);
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setStateWord(partner, 0, 0);
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        bound, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), partner));
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(
        partner, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), bound));
    NFcore2::MatchContext context;
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member,
                              context) == 2.0);
}

TEST_CASE("native NFcore2 reader preserves compartment-scoped global observables") {
    auto system = compartmentScopedGlobalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    REQUIRE(rule.rate_expression_bindings.size() == 1);
    const auto& binding = rule.rate_expression_bindings[0];
    CHECK(binding.kind == NFcore2::NATIVE_RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT);
    CHECK(binding.molecule_type == 0);
    CHECK(binding.compartment == NFcore2::nativeCompartmentId("c1"));
    CHECK_FALSE(binding.compartment_ancestry);
}

TEST_CASE("native NFcore2 reader evaluates nested scoped local functions") {
    auto system = nestedLocalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK(snapshot.rules[0].rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    CHECK_FALSE(snapshot.rules[0].uses_local_function);
    CHECK_FALSE(snapshot.rules[0].rate_expression_functions.empty());
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto molecule = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(
        NFcore2::MoleculeTypeId(0), molecule));
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member,
                               context) == 3.0);
}

TEST_CASE("native NFcore2 reader lowers a FunctionProduct of scoped local functions") {
    auto system = localFunctionProductSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    CHECK_FALSE(rule.uses_local_function);
    CHECK(rule.rate_expression.find("*") != std::string::npos);
    CHECK(rule.rate_expression_bindings.size() == 4);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto b = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    context.setMoleculeAt(1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member, context) == 6.0);
}

TEST_CASE("native NFcore2 reader lowers a simple global observable function") {
    auto system = globalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto& rule = snapshot.rules[0];
    CHECK(rule.rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    CHECK_FALSE(rule.uses_local_function);
    REQUIRE(rule.rate_expression_bindings.size() == 2);
    CHECK(rule.rate_expression_bindings[0].kind == NFcore2::NATIVE_RATE_EXPRESSION_GLOBAL_MOLECULE_COUNT);
    CHECK(rule.rate_expression_bindings[0].molecule_type == 0);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    const auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    const auto b = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    (void)a; (void)b;
    engine.state().setTime(1.0);
    NFcore2::MatchContext context;
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member, context) == 5.0);
}

TEST_CASE("native NFcore2 reader evaluates nested global functions") {
    auto system = nestedGlobalFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK(snapshot.rules[0].rate_law == NFcore2::NATIVE_RATE_EXPRESSION);
    CHECK_FALSE(snapshot.rules[0].uses_local_function);
    REQUIRE(snapshot.rules[0].rate_expression_functions.size() == 1);
    CHECK(snapshot.rules[0].rate_expression_functions[0].name == "base");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    CHECK(engine.evaluateRate(lowered.rules[0].family, lowered.rules[0].member,
                               context) == 5.0);
}

TEST_CASE("native NFcore2 lowering executes a reciprocal binding transform") {
    auto system = systemFor("bind: A(b)+B(a)->A(b!1).B(a!1) 3");
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    REQUIRE(lowered.supported_rule_count == 1);
    REQUIRE(lowered.executable.metadata().ruleFamilies().size() == 1);

    NFcore2::SimulationState state(lowered.executable.metadata());
    const NFcore2::MoleculeHandle a =
        state.molecules(NFcore2::MoleculeTypeId(0)).create();
    const NFcore2::MoleculeHandle b =
        state.molecules(NFcore2::MoleculeTypeId(1)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    context.setMoleculeAt(1, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    NFcore2::ScaffoldStore scaffolds;
    const auto& family = lowered.executable.metadata().ruleFamilies()[0];
    CHECK(lowered.executable.matchers().at(family.matcher).evaluate(
        state, scaffolds, context));
    NFcore2::FeatureDelta delta;
    lowered.executable.transforms().at(family.transform).execute(
        state, scaffolds, context, delta);
    CHECK(state.molecules(NFcore2::MoleculeTypeId(0)).bondRef(a, 1) ==
          NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    CHECK(state.molecules(NFcore2::MoleculeTypeId(1)).bondRef(b, 0) ==
          NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    REQUIRE(delta.changed.size() == 2);
    CHECK(delta.changed[0].value() == 3);
    CHECK(delta.changed[1].value() == 5);
}

TEST_CASE("native NFcore2 reader captures a root-local compartment move") {
    auto system = compartmentSystemFor("move: @c1:A(site) -> @c2:A(site) 1");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    REQUIRE(snapshot.rules[0].transforms.size() == 1);
    CHECK(snapshot.rules[0].transforms[0].kind == NFcore2::NATIVE_MOVE);
    CHECK(snapshot.rules[0].transforms[0].destination_compartment ==
          NFcore2::nativeCompartmentId("c2"));
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    NFcore2::MatchContext context;
    const auto molecule = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setCompartment(
        molecule, NFcore2::nativeCompartmentId("c1"));
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), molecule));
    NFcore2::FeatureDelta delta;
    REQUIRE(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK(engine.state().molecules(NFcore2::MoleculeTypeId(0)).compartment(molecule) ==
          NFcore2::nativeCompartmentId("c2"));
}

TEST_CASE("native NFcore2 reader exports compartment hierarchy metadata") {
    auto model = bng::parser::parseModel(R"(
begin compartments
 cell 3 10.0
 cyto 3 2.0 cell
end compartments
begin molecule types
 A(site)
end molecule types
begin seed species
 @cyto:A(site) 1
end seed species
begin reaction rules
 r: @cyto:A(site) -> @cell:A(site) 1
end reaction rules
)");
    REQUIRE(model);
    int traversal=0;
    auto system=std::unique_ptr<NFcore::System>(NFinput::buildSystemFromAst(*model,false,100,false,traversal));
    REQUIRE(system);
    const auto snapshot=NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.compartments.size()==2);
    auto child=std::find_if(snapshot.compartments.begin(),snapshot.compartments.end(),[](const auto& c){return c.id==NFcore2::nativeCompartmentId("cyto");});
    REQUIRE(child!=snapshot.compartments.end());
    CHECK(child->parent==NFcore2::nativeCompartmentId("cell"));
    CHECK(child->size==2.0);
}

TEST_CASE("native NFcore2 reader captures complete species deletion") {
    auto system = systemFor("kill: A(s~U) -> 0 1");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    REQUIRE(snapshot.rules[0].transforms.size() == 1);
    CHECK(snapshot.rules[0].transforms[0].kind == NFcore2::NATIVE_REMOVE);
    CHECK(snapshot.rules[0].transforms[0].removal_type ==
          NFcore2::NATIVE_DELETE_COMPLETE_SPECIES);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    const auto molecule = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    NFcore2::MatchContext context;
    context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), molecule));
    NFcore2::FeatureDelta delta;
    REQUIRE(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK_FALSE(engine.state().molecules(NFcore2::MoleculeTypeId(0)).alive(molecule));
}

TEST_CASE("native NFcore2 reader preserves implicit conditional deletion") {
    auto system = systemFor("conditional: A(s~U,b!1).B(a!1) -> B(a) 1");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto removal = std::find_if(snapshot.rules[0].transforms.begin(),
                                      snapshot.rules[0].transforms.end(),
                                      [](const auto& transform) {
                                          return transform.kind == NFcore2::NATIVE_REMOVE;
                                      });
    REQUIRE(removal != snapshot.rules[0].transforms.end());
    CHECK(removal->removal_type == NFcore2::NATIVE_DELETE_MOLECULE_CONDITIONAL);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
}

TEST_CASE("native NFcore2 reader preserves explicit DeleteMolecules deletion") {
    auto system = systemFor("explicit: A(s~U,b!1).B(a!1) -> B(a) 1 DeleteMolecules");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto removal = std::find_if(snapshot.rules[0].transforms.begin(),
                                      snapshot.rules[0].transforms.end(),
                                      [](const auto& transform) {
                                          return transform.kind == NFcore2::NATIVE_REMOVE;
                                      });
    REQUIRE(removal != snapshot.rules[0].transforms.end());
    CHECK(removal->removal_type == NFcore2::NATIVE_DELETE_MOLECULE_ONLY);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
}

TEST_CASE("native NFcore2 reader captures population decrement") {
    auto system = populationSystemFor("dec: P() -> 0 1");
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    REQUIRE(snapshot.rules[0].transforms.size() == 1);
    CHECK(snapshot.rules[0].transforms[0].kind == NFcore2::NATIVE_DECREMENT_POPULATION);
    CHECK(snapshot.rules[0].transforms[0].population_delta == 1);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    NFcore2::Engine engine(lowered.executable);
    NFcore2::MatchContext context;
    NFcore2::FeatureDelta delta;
    CHECK_FALSE(engine.fire(lowered.rules[0].family, lowered.rules[0].member,
                            context, delta));
    CHECK(engine.state().populations().value(NFcore2::PopulationId(0)) == 0);
    engine.state().populations().addTo(NFcore2::PopulationId(0), 5);
    // A population reactant is selected by its count, so it must not require
    // an invented particle handle in MatchContext.
    REQUIRE(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK(engine.state().populations().value(NFcore2::PopulationId(0)) == 4);
}

TEST_CASE("native NFcore2 reader executes MoveConnected species relocation") {
    auto system = moveConnectedSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    const auto move = std::find_if(snapshot.rules[0].transforms.begin(),
                                   snapshot.rules[0].transforms.end(),
                                   [](const auto& transform) {
                                       return transform.kind == NFcore2::NATIVE_MOVE;
                                   });
    REQUIRE(move != snapshot.rules[0].transforms.end());
    CHECK(move->move_connected);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 1);
    CHECK(lowered.fallback_rule_count == 0);
    NFcore2::Engine engine(lowered.executable);
    auto a = engine.state().molecules(NFcore2::MoleculeTypeId(0)).create();
    auto b = engine.state().molecules(NFcore2::MoleculeTypeId(1)).create();
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setCompartment(a, NFcore2::nativeCompartmentId("c1"));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setCompartment(b, NFcore2::nativeCompartmentId("c1"));
    engine.state().molecules(NFcore2::MoleculeTypeId(0)).setBondRef(a, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(1), b));
    engine.state().molecules(NFcore2::MoleculeTypeId(1)).setBondRef(b, 0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    NFcore2::MatchContext context; context.setMoleculeAt(0, NFcore2::MoleculeRef(NFcore2::MoleculeTypeId(0), a));
    NFcore2::FeatureDelta delta;
    REQUIRE(engine.fire(lowered.rules[0].family, lowered.rules[0].member, context, delta));
    CHECK(engine.state().molecules(NFcore2::MoleculeTypeId(0)).compartment(a) == NFcore2::nativeCompartmentId("c2"));
    CHECK(engine.state().molecules(NFcore2::MoleculeTypeId(1)).compartment(b) == NFcore2::nativeCompartmentId("c2"));
}
