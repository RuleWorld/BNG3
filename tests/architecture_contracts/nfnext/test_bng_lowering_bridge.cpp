#ifdef NDEBUG
#undef NDEBUG
#endif

#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"
#include "parser/BNGAstVisitor.hpp"

#include <cassert>
#include <iostream>

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
  A(x~u~p)
  B(y)
end molecule types
begin seed species
  A(x~u) 1
  B(y) 1
end seed species
begin reaction rules
  bind_and_phosphorylate: A(x~u) + B(y) -> A(x~p!1).B(y!1) k
end reaction rules
)BNG");
    assert(parsed);

    const bng::compile::CompiledModel semantic(*parsed);
    assert(semantic.valid());

    auto lowered = nfnext::lowerFromBioNetGen(semantic);
    assert(lowered.ok());
    assert(lowered.issues.empty());
    assert(lowered.model.molecule_types.size() == 2);
    assert(lowered.model.expanded_rules.size() == 1);

    const auto& rule = lowered.model.expanded_rules.front();
    assert(rule.pattern.nodes.size() == 2);
    assert(rule.pattern.molecularity.size() == 1);
    assert(rule.pattern.molecularity.front().kind ==
           nfnext::MolecularityKind::DifferentComplex);
    assert(rule.pattern.molecularity.front().left == 0);
    assert(rule.pattern.molecularity.front().right == 1);

    // An omitted bond marker is lowered as the native free-site constraint;
    // both reactant sites are therefore explicit alongside A.x~u.
    assert(rule.predicates.size() == 3);
    assert(rule.predicates.front().kind == nfnext::PredicateKind::SiteStateEq);
    assert(rule.predicates.front().node == 0);
    assert(rule.predicates.front().site == 0);
    assert(rule.predicates.front().value == 0); // A.x~u
    assert(rule.predicates[1].kind == nfnext::PredicateKind::SiteFree);
    assert(rule.predicates[1].node == 0);
    assert(rule.predicates[1].site == 0);
    assert(rule.predicates[2].kind == nfnext::PredicateKind::SiteFree);
    assert(rule.predicates[2].node == 1);
    assert(rule.predicates[2].site == 0);

    assert(rule.actions.size() == 2);
    assert(rule.actions[0].kind == nfnext::ActionKind::SetSiteState);
    assert(rule.actions[0].target_node == 0);
    assert(rule.actions[0].site == 0);
    assert(rule.actions[0].value == 1); // A.x~p

    assert(rule.actions[1].kind == nfnext::ActionKind::Bind);
    assert(rule.actions[1].target_node == 0);
    assert(rule.actions[1].partner_node == 1);
    assert(rule.actions[1].site == 0);
    assert(rule.actions[1].partner_site == 0);
    assert(rule.rate == 1.0);

    std::cout << "BNG -> NFnext lowering bridge: PASS\n";
    return 0;
}
