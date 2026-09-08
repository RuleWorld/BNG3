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
    auto model = bng::parser::parseModel(R"(
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
    REQUIRE(graph.edges.size() == 1);
    CHECK(graph.edges[0].first_node == 0);
    CHECK(graph.edges[0].first_component == 0);
    CHECK(graph.edges[0].second_node == 1);
    CHECK(graph.edges[0].second_component == 0);
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

TEST_CASE("native NFcore2 reader keeps local DOR rules on compatibility fallback") {
    auto system = localFunctionSystem();
    const auto snapshot = NFcore2::snapshotLegacyNFsim(*system);
    REQUIRE(snapshot.rules.size() == 1);
    CHECK(snapshot.rules[0].uses_local_function);
    const auto lowered = NFcore2::lowerLegacyNFsim(*system);
    CHECK(lowered.supported_rule_count == 0);
    CHECK(lowered.fallback_rule_count == 1);
    CHECK(lowered.rules[0].reason == NFcore2::LOWERING_LOCAL_FUNCTION);
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
