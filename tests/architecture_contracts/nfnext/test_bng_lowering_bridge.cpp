#ifdef NDEBUG
#undef NDEBUG
#endif

#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"
#include "nfnext/generic_matcher.hpp"
#include "nfnext/transformation.hpp"
#include "parser/BNGAstVisitor.hpp"

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <iterator>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

nfnext::TypeId moleculeTypeId(const nfnext::ModelIR& model, const std::string& name) {
    const auto found = std::find_if(model.molecule_types.begin(), model.molecule_types.end(),
        [&](const auto& type) { return type.name == name; });
    if (found == model.molecule_types.end())
        throw std::runtime_error("test molecule type is missing: " + name);
    return found->id;
}

std::uint32_t siteIndex(const nfnext::ModelIR& model, nfnext::TypeId type,
                        const std::string& name) {
    const auto molecule = std::find_if(model.molecule_types.begin(), model.molecule_types.end(),
        [&](const auto& candidate) { return candidate.id == type; });
    if (molecule == model.molecule_types.end())
        throw std::runtime_error("test molecule type ID is missing");
    const auto found = std::find_if(molecule->sites.begin(), molecule->sites.end(),
        [&](const auto& site) { return site.name == name; });
    if (found == molecule->sites.end())
        throw std::runtime_error("test molecule site is missing: " + name);
    return static_cast<std::uint32_t>(std::distance(molecule->sites.begin(), found));
}

void executeLoweredDeletionActions(const std::vector<nfnext::ActionIR>& actions,
                                   const nfnext::MatchEmbedding& embedding,
                                   nfnext::GenericGraphState& state) {
    nfnext::TransformationIR transformation;
    for (const auto& action : actions) {
        switch (action.kind) {
        case nfnext::ActionKind::SetSiteState:
            transformation.setState(action.target_node, action.site, action.value);
            break;
        case nfnext::ActionKind::Unbind:
            transformation.deleteBond(action.target_node, action.site,
                                       action.partner_node, action.partner_site);
            break;
        case nfnext::ActionKind::Destroy:
            transformation.destroyMolecule(action.target_node);
            break;
        case nfnext::ActionKind::DestroyComplex:
            transformation.destroyComplexContaining(action.target_node);
            break;
        default:
            throw std::runtime_error("unexpected action in deletion runtime regression");
        }
    }
    nfnext::applyTransformation(transformation, embedding, state);
}

nfnext::MatchEmbedding transformationEmbedding(const nfnext::Embedding& embedding) {
    nfnext::MatchEmbedding result;
    for (std::size_t node = 0; node < embedding.particles().size(); ++node)
        result.bindNode(node, embedding.particle(node));
    return result;
}

void rejectsUnrepresentablePackedSiteIndex() {
    // NFnext ActionIR and PredicateIR store packed site IDs as uint16_t.
    // A 65,537th component therefore cannot be represented: its zero-based
    // index is 65,536 and must be rejected instead of wrapping to site zero.
    std::ostringstream source;
    source << "begin molecule types\n  A(";
    constexpr std::size_t componentCount = 65'537;
    for (std::size_t index = 0; index < componentCount; ++index) {
        if (index != 0) source << ',';
        source << 'c' << index;
        if (index + 1 == componentCount) source << "~u";
    }
    source << ")\nend molecule types\n"
           << "begin reaction rules\n"
           << "  high_site: A(c65536~u) -> A(c65536~u) 1\n"
           << "end reaction rules\n";

    auto parsed = bng::parser::parseModel(source.str());
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (lowered.ok()) {
        std::cerr << "unrepresentable component index 65536 was accepted\n";
    }
    assert(!lowered.ok());
    assert(lowered.issues.size() == 1);
    assert(lowered.issues.front().message.find("uint16 site capacity") != std::string::npos);
    assert(lowered.model.expanded_rules.empty());
}

void rejectsMolecularityNodeIndexOverflow() {
    const auto maxNodeIndex = static_cast<std::size_t>(
        std::numeric_limits<std::uint16_t>::max());
    const auto maxNodeCount = maxNodeIndex + 1;
    nfnext::PatternIR boundary;
    for (std::size_t index = 0; index < maxNodeCount; ++index)
        boundary.addNode(0);
    boundary.requireSameComplex(0, maxNodeIndex);
    assert(boundary.nodes.size() == 65536);
    assert(boundary.molecularity.size() == 1);
    assert(boundary.molecularity.front().left == 0);
    assert(boundary.molecularity.front().right == 65535);

    std::ostringstream source;
    source << "begin parameters\n  k 1\nend parameters\n"
           << "begin molecule types\n  A(x)\n  B(y)\nend molecule types\n"
           << "begin reaction rules\n  overflow: ";
    // The first complex reaches node index 65,536; the '+' reactant adds
    // another node. Lowering must reject before either molecularity cast.
    for (std::size_t index = 0; index < maxNodeCount + 1; ++index) {
        if (index != 0) source << '.';
        source << "A()";
    }
    source << " + B() -> 0 k\nend reaction rules\n";
    const auto parsed = bng::parser::parseModel(source.str());
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    assert(!lowered.ok());
    assert(lowered.model.expanded_rules.empty());
    assert(std::any_of(lowered.issues.begin(), lowered.issues.end(), [](const auto& item) {
        return item.message.find("uint16 molecularity capacity") != std::string::npos;
    }));
}

void lowersWholeSpeciesDeletionWithHiddenConnectedContext() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
  B(y~u~p)
  C(z)
end molecule types
begin reaction rules
  delete_A_and_transform_B: A(x!+) + B(y~u) -> B(y~p) k
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);
    assert(semantic.rules().front().forward().wholeSpeciesDeletions ==
           std::vector<std::size_t>{0});
    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        for (const auto& item : lowered.issues)
            std::cerr << item.entity << ": " << item.message << '\n';
    }
    assert(lowered.ok());
    const auto& actions = lowered.model.expanded_rules.front().actions;

    // Exercise the lowered action through NFnext's existing graph transformation
    // runtime. A is matched, while C is omitted from the rule but is connected
    // to A in the runtime state; default deletion must remove the whole complex.
    const auto& model = lowered.model;
    const auto aType = moleculeTypeId(model, "A");
    const auto bType = moleculeTypeId(model, "B");
    const auto cType = moleculeTypeId(model, "C");
    const auto aSite = siteIndex(model, aType, "x");
    const auto bSite = siteIndex(model, bType, "y");
    const auto cSite = siteIndex(model, cType, "z");
    nfnext::GenericGraphState state(model);
    const auto a = state.create(aType);
    const auto b = state.create(bType);
    const auto c = state.create(cType);
    state.setSiteState(b, static_cast<std::uint16_t>(bSite), 0);
    state.bind(a, static_cast<std::uint16_t>(aSite), c, static_cast<std::uint16_t>(cSite));
    nfnext::MatchEmbedding embedding;
    embedding.bindNode(0, a);
    embedding.bindNode(1, b);
    executeLoweredDeletionActions(actions, embedding, state);
    assert(state.liveCount() == 1);
    assert(!state.alive(a));
    assert(!state.alive(c));
    assert(state.alive(b));
    assert(state.siteState(b, static_cast<std::uint16_t>(bSite)) == 1);
    assert(actions.size() == 2);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::DestroyComplex;
    }) == 1);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::Destroy;
    }) == 0);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::SetSiteState;
    }) == 1);
    const auto wholeSpeciesAction = std::find_if(
        actions.begin(), actions.end(), [](const auto& action) {
            return action.kind == nfnext::ActionKind::DestroyComplex;
        });
    assert(wholeSpeciesAction != actions.end());
    assert(wholeSpeciesAction->target_node == 0);
    assert(wholeSpeciesAction->molecule_type == 0);
}

void lowersExplicitBondAndHiddenContextAsOneSpeciesDeletion() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
  D(y,z)
  B(s~u~p)
  C(q)
end molecule types
begin reaction rules
  delete_AD_and_transform_B: A(x!1).D(y!1,z!+) + B(s~u) -> B(s~p) k
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);
    assert(semantic.rules().front().forward().wholeSpeciesDeletions ==
           std::vector<std::size_t>{0});
    assert(std::any_of(
        semantic.rules().front().forward().mutations.begin(),
        semantic.rules().front().forward().mutations.end(), [](const auto& mutation) {
            return mutation.kind == bng::compile::MutationKind::DeleteBond &&
                   mutation.source.patternIndex == 0 && mutation.partner.patternIndex == 0;
        }));

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        for (const auto& item : lowered.issues)
            std::cerr << item.entity << ": " << item.message << '\n';
    }
    assert(lowered.ok());
    const auto& actions = lowered.model.expanded_rules.front().actions;

    const auto& model = lowered.model;
    const auto aType = moleculeTypeId(model, "A");
    const auto dType = moleculeTypeId(model, "D");
    const auto bType = moleculeTypeId(model, "B");
    const auto cType = moleculeTypeId(model, "C");
    const auto aSite = siteIndex(model, aType, "x");
    const auto dY = siteIndex(model, dType, "y");
    const auto dZ = siteIndex(model, dType, "z");
    const auto bSite = siteIndex(model, bType, "s");
    const auto cSite = siteIndex(model, cType, "q");
    nfnext::GenericGraphState state(model);
    const auto a = state.create(aType);
    const auto d = state.create(dType);
    const auto b = state.create(bType);
    const auto c = state.create(cType);
    state.setSiteState(b, static_cast<std::uint16_t>(bSite), 0);
    state.bind(a, static_cast<std::uint16_t>(aSite), d, static_cast<std::uint16_t>(dY));
    state.bind(d, static_cast<std::uint16_t>(dZ), c, static_cast<std::uint16_t>(cSite));
    nfnext::MatchEmbedding embedding;
    embedding.bindNode(0, a);
    embedding.bindNode(1, d);
    embedding.bindNode(2, b);
    executeLoweredDeletionActions(actions, embedding, state);
    assert(state.liveCount() == 1);
    assert(!state.alive(a));
    assert(!state.alive(d));
    assert(!state.alive(c));
    assert(state.alive(b));
    assert(state.siteState(b, static_cast<std::uint16_t>(bSite)) == 1);

    assert(actions.size() == 2);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::DestroyComplex;
    }) == 1);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::Destroy;
    }) == 0);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::Unbind;
    }) == 0);
    const auto wholeSpeciesAction = std::find_if(
        actions.begin(), actions.end(), [](const auto& action) {
            return action.kind == nfnext::ActionKind::DestroyComplex;
        });
    assert(wholeSpeciesAction != actions.end());
    assert(wholeSpeciesAction->target_node == 0);
    assert(wholeSpeciesAction->molecule_type == 0);
}

void loweredReactantPatternRequiresOneSharedComplex() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
  D(y,z)
  B(s~u~p,t)
  C(q,w)
end molecule types
begin reaction rules
  delete_AD_and_transform_B: A().D() + B(s~u) -> B(s~p) k
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);
    assert(semantic.rules().front().forward().wholeSpeciesDeletions ==
           std::vector<std::size_t>{0});

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        for (const auto& item : lowered.issues)
            std::cerr << item.entity << ": " << item.message << '\n';
    }
    assert(lowered.ok());
    const auto& model = lowered.model;
    const auto& rule = model.expanded_rules.front();
    const auto aType = moleculeTypeId(model, "A");
    const auto dType = moleculeTypeId(model, "D");
    const auto bType = moleculeTypeId(model, "B");
    const auto cType = moleculeTypeId(model, "C");
    const auto aSite = siteIndex(model, aType, "x");
    const auto dY = siteIndex(model, dType, "y");
    const auto dZ = siteIndex(model, dType, "z");
    const auto bSite = siteIndex(model, bType, "s");
    const auto bT = siteIndex(model, bType, "t");
    const auto cSite = siteIndex(model, cType, "q");
    const auto cW = siteIndex(model, cType, "w");
    nfnext::GenericMatcher matcher(model);

    nfnext::GenericGraphState disconnected(model);
    disconnected.create(aType);
    disconnected.create(dType);
    const auto disconnectedB = disconnected.create(bType);
    disconnected.setSiteState(disconnectedB, static_cast<std::uint16_t>(bSite), 0);
    const auto disconnectedMatches = matcher.enumerate(rule.pattern, disconnected);
    if (!disconnectedMatches.empty())
        std::cerr << "disconnected A and D unexpectedly matched as one BNGL pattern ("
                  << disconnectedMatches.size() << " embedding(s))\n";
    assert(disconnectedMatches.empty());

    nfnext::GenericGraphState sameComplexAcrossPlus(model);
    const auto sharedA = sameComplexAcrossPlus.create(aType);
    const auto sharedD = sameComplexAcrossPlus.create(dType);
    const auto sharedB = sameComplexAcrossPlus.create(bType);
    const auto sharedC = sameComplexAcrossPlus.create(cType);
    sameComplexAcrossPlus.setSiteState(sharedB, static_cast<std::uint16_t>(bSite), 0);
    sameComplexAcrossPlus.bind(sharedA, static_cast<std::uint16_t>(aSite),
                               sharedD, static_cast<std::uint16_t>(dY));
    sameComplexAcrossPlus.bind(sharedD, static_cast<std::uint16_t>(dZ),
                               sharedC, static_cast<std::uint16_t>(cSite));
    sameComplexAcrossPlus.bind(sharedC, static_cast<std::uint16_t>(cW),
                               sharedB, static_cast<std::uint16_t>(bT));
    assert(matcher.enumerate(rule.pattern, sameComplexAcrossPlus).empty());

    nfnext::GenericGraphState connected(model);
    const auto a = connected.create(aType);
    const auto d = connected.create(dType);
    const auto b = connected.create(bType);
    const auto c = connected.create(cType);
    connected.setSiteState(b, static_cast<std::uint16_t>(bSite), 0);
    connected.bind(a, static_cast<std::uint16_t>(aSite),
                   d, static_cast<std::uint16_t>(dY));
    connected.bind(d, static_cast<std::uint16_t>(dZ),
                   c, static_cast<std::uint16_t>(cSite));
    const auto connectedMatches = matcher.enumerate(rule.pattern, connected);
    assert(connectedMatches.size() == 1);
    executeLoweredDeletionActions(
        rule.actions, transformationEmbedding(connectedMatches.front()), connected);
    assert(connected.liveCount() == 1);
    assert(!connected.alive(a));
    assert(!connected.alive(d));
    assert(!connected.alive(c));
    assert(connected.alive(b));
    assert(connected.siteState(b, static_cast<std::uint16_t>(bSite)) == 1);
}

void deleteMoleculesRemainsMoleculeScoped() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
  D(y,z)
  B(s~u~p)
  C(q)
end molecule types
begin reaction rules
  delete_AD_and_transform_B: A(x!1).D(y!1,z!+) + B(s~u) -> B(s~p) k DeleteMolecules
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);
    assert(semantic.rules().front().forward().wholeSpeciesDeletions.empty());

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        for (const auto& item : lowered.issues)
            std::cerr << item.entity << ": " << item.message << '\n';
    }
    assert(lowered.ok());
    const auto& actions = lowered.model.expanded_rules.front().actions;
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::DestroyComplex;
    }) == 0);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::Destroy;
    }) == 2);
    assert(std::count_if(actions.begin(), actions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::SetSiteState;
    }) == 1);

    const auto& model = lowered.model;
    const auto aType = moleculeTypeId(model, "A");
    const auto dType = moleculeTypeId(model, "D");
    const auto bType = moleculeTypeId(model, "B");
    const auto cType = moleculeTypeId(model, "C");
    const auto aSite = siteIndex(model, aType, "x");
    const auto dY = siteIndex(model, dType, "y");
    const auto dZ = siteIndex(model, dType, "z");
    const auto bSite = siteIndex(model, bType, "s");
    const auto cSite = siteIndex(model, cType, "q");
    nfnext::GenericGraphState state(model);
    const auto a = state.create(aType);
    const auto d = state.create(dType);
    const auto b = state.create(bType);
    const auto c = state.create(cType);
    state.setSiteState(b, static_cast<std::uint16_t>(bSite), 0);
    state.bind(a, static_cast<std::uint16_t>(aSite), d, static_cast<std::uint16_t>(dY));
    state.bind(d, static_cast<std::uint16_t>(dZ), c, static_cast<std::uint16_t>(cSite));
    nfnext::MatchEmbedding embedding;
    embedding.bindNode(0, a);
    embedding.bindNode(1, d);
    embedding.bindNode(2, b);
    executeLoweredDeletionActions(actions, embedding, state);
    assert(state.liveCount() == 2);
    assert(!state.alive(a));
    assert(!state.alive(d));
    assert(state.alive(b));
    assert(state.siteState(b, static_cast<std::uint16_t>(bSite)) == 1);
    assert(state.alive(c));
    assert(!state.bound(c, static_cast<std::uint16_t>(cSite)));
}

void rejectsSimultaneousMoleculeReplacement() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x)
  B(y)
  C(z)
end molecule types
begin reaction rules
  replace_B_with_C: A(x!1).B(y!1) -> A(x) + C(z) k
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    assert(!lowered.ok());
    assert(lowered.model.expanded_rules.empty());
    assert(std::any_of(lowered.issues.begin(), lowered.issues.end(), [](const auto& item) {
        return item.message.find("simultaneous molecule replacement requires orphan-context semantics") !=
               std::string::npos;
    }));
}

void reverseDirectionRetainsWholeSpeciesDeletionScope() {
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  kf 1
  kr 1
end parameters
begin molecule types
  A(x~u~p)
  B()
end molecule types
begin reaction rules
  reversible_add_B: A(x~u) <-> A(x~p) + B() kf, kr
end reaction rules
)BNG");
    assert(parsed);
    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());
    assert(semantic.rules().size() == 1);
    assert(semantic.rules().front().reverse().has_value());
    assert(semantic.rules().front().reverse()->wholeSpeciesDeletions ==
           std::vector<std::size_t>{1});

    const auto lowered = nfnext::lowerFromBioNetGen(semantic);
    if (!lowered.ok()) {
        for (const auto& item : lowered.issues)
            std::cerr << item.entity << ": " << item.message << '\n';
    }
    assert(lowered.ok());
    assert(lowered.model.expanded_rules.size() == 2);
    const auto& reverseActions = lowered.model.expanded_rules.back().actions;
    assert(reverseActions.size() == 2);
    assert(std::count_if(reverseActions.begin(), reverseActions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::DestroyComplex;
    }) == 1);
    assert(std::count_if(reverseActions.begin(), reverseActions.end(), [](const auto& action) {
        return action.kind == nfnext::ActionKind::Destroy;
    }) == 0);
    const auto wholeSpeciesAction = std::find_if(
        reverseActions.begin(), reverseActions.end(), [](const auto& action) {
            return action.kind == nfnext::ActionKind::DestroyComplex;
        });
    assert(wholeSpeciesAction != reverseActions.end());
    assert(wholeSpeciesAction->target_node == 1);
    assert(wholeSpeciesAction->molecule_type == 1);
}

} // namespace

int main() {
    // Mirror the worked typed-semantic fixture in formal/lean/BNG/Examples.lean.
    // The production side deliberately starts from BNGL so this test crosses
    // parser -> canonical CompiledModel -> NFIR rather than constructing NFIR
    // directly and merely testing its containers.
    auto parsed = bng::parser::parseModel(R"BNG(
begin parameters
  k 1
end parameters
begin molecule types
  A(x~u~p,y~off~on)
  B(y)
end molecule types
begin seed species
  A(x~u) 1
  B(y) 1
end seed species
begin reaction rules
  bind_and_phosphorylate: A(x~u) + B(y) -> A(x~p!1).B(y!1) k
  nonzero_site_state: A(y~off) -> A(y~on) 1
end reaction rules
)BNG");
    assert(parsed);

    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());

    auto lowered = nfnext::lowerFromBioNetGen(semantic);
    assert(lowered.ok());
    assert(lowered.issues.empty());
    assert(lowered.model.molecule_types.size() == 2);
    assert(lowered.model.molecule_types[0].id == 0);
    assert(lowered.model.molecule_types[1].id == 1);
    assert(lowered.model.molecule_types[0].sites.size() == 2);
    assert(lowered.model.molecule_types[0].sites[1].states.size() == 2);
    assert(lowered.model.expanded_rules.size() == 2);

    const auto& rule = lowered.model.expanded_rules.front();
    assert(rule.pattern.nodes.size() == 2);
    assert(rule.pattern.nodes[0].molecule_type == 0);
    assert(rule.pattern.nodes[1].molecule_type == 1);
    assert(rule.pattern.molecularity.size() == 1);
    assert(rule.pattern.molecularity.front().kind ==
           nfnext::MolecularityKind::DifferentComplex);
    assert(rule.pattern.molecularity.front().left == 0);
    assert(rule.pattern.molecularity.front().right == 1);

    // This first rule mirrors the worked typed-semantic Lean fixture. An
    // omitted bond marker is lowered as the native free-site constraint.
    assert(rule.predicates.size() == 3);
    assert(rule.predicates.front().kind == nfnext::PredicateKind::SiteStateEq);
    assert(rule.predicates.front().node == 0);
    assert(rule.predicates.front().molecule_type == 0);
    assert(rule.predicates.front().site == 0);
    assert(rule.predicates.front().value == 0); // A.x~u
    assert(rule.predicates[1].kind == nfnext::PredicateKind::SiteFree);
    assert(rule.predicates[1].node == 0);
    assert(rule.predicates[1].site == 0);
    assert(rule.predicates[2].kind == nfnext::PredicateKind::SiteFree);
    assert(rule.predicates[2].node == 1);
    assert(rule.predicates[2].molecule_type == 1);
    assert(rule.predicates[2].site == 0);

    assert(rule.actions.size() == 2);
    assert(rule.actions[0].kind == nfnext::ActionKind::SetSiteState);
    assert(rule.actions[0].target_node == 0);
    assert(rule.actions[0].molecule_type == 0);
    assert(rule.actions[0].site == 0);
    assert(rule.actions[0].value == 1); // A.x~p

    assert(rule.actions[1].kind == nfnext::ActionKind::Bind);
    assert(rule.actions[1].target_node == 0);
    assert(rule.actions[1].partner_node == 1);
    assert(rule.actions[1].molecule_type == 0);
    assert(rule.actions[1].site == 0);
    assert(rule.actions[1].partner_site == 0);
    assert(rule.rate == 1.0);

    // The second rule exercises nonzero molecule-local site and state IDs.
    const auto& nonzeroSiteRule = lowered.model.expanded_rules[1];
    assert(nonzeroSiteRule.predicates.size() == 2);
    assert(nonzeroSiteRule.predicates[0].kind == nfnext::PredicateKind::SiteStateEq);
    assert(nonzeroSiteRule.predicates[0].molecule_type == 0);
    assert(nonzeroSiteRule.predicates[0].site == 1);
    assert(nonzeroSiteRule.predicates[0].value == 0); // A.y~off
    assert(nonzeroSiteRule.predicates[1].kind == nfnext::PredicateKind::SiteFree);
    assert(nonzeroSiteRule.predicates[1].site == 1);
    assert(nonzeroSiteRule.actions.size() == 1);
    assert(nonzeroSiteRule.actions[0].kind == nfnext::ActionKind::SetSiteState);
    assert(nonzeroSiteRule.actions[0].molecule_type == 0);
    assert(nonzeroSiteRule.actions[0].site == 1);
    assert(nonzeroSiteRule.actions[0].value == 1); // A.y~on

    rejectsUnrepresentablePackedSiteIndex();
    rejectsMolecularityNodeIndexOverflow();
    lowersWholeSpeciesDeletionWithHiddenConnectedContext();
    lowersExplicitBondAndHiddenContextAsOneSpeciesDeletion();
    loweredReactantPatternRequiresOneSharedComplex();
    deleteMoleculesRemainsMoleculeScoped();
    reverseDirectionRetainsWholeSpeciesDeletionScope();
    rejectsSimultaneousMoleculeReplacement();

    std::cout << "BNG -> NFnext lowering bridge: PASS\n";
    return 0;
}
