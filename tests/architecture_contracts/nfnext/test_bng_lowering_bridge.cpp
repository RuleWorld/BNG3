#ifdef NDEBUG
#undef NDEBUG
#endif

#include "compile/CompiledModel.hpp"
#include "nfnext/from_bng.hpp"
#include "parser/BNGAstVisitor.hpp"

#include <cassert>
#include <iostream>
#include <sstream>
#include <string>

namespace {

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

    std::cout << "BNG -> NFnext lowering bridge: PASS\n";
    return 0;
}
