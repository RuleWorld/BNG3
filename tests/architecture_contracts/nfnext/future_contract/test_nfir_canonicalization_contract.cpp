#include "contract_test.hpp"

#if __has_include("nfnext/canonical.hpp") && __has_include("nfnext/validator.hpp")
#include "nfnext/canonical.hpp"
#include "nfnext/validator.hpp"
#include "nfnext/nfir.hpp"
#include <algorithm>
#include <limits>
using namespace nfnext;

static ModelIR simpleModel() {
    ModelIR m;
    m.model_name = "canonical";
    MoleculeTypeIR a; a.id = 0; a.name = "A";
    a.sites.push_back(SiteSpec{"x", {"u", "p"}});
    MoleculeTypeIR b; b.id = 1; b.name = "B";
    b.sites.push_back(SiteSpec{"a", {}});
    m.molecule_types = {a, b};
    ExpandedRuleIR r;
    r.id = 0; r.name = "bind_17"; r.rate = 2.5;
    r.predicates.push_back(PredicateIR{PredicateKind::SiteStateEq, 0, 0, 0, 0});
    r.actions.push_back(ActionIR{ActionKind::SetSiteState, 0, 0, 1, 0});
    m.expanded_rules.push_back(r);
    return m;
}

CONTRACT_CASE("canonicalization is idempotent") {
    auto a = canonicalizeModel(simpleModel());
    auto b = canonicalizeModel(a);
    REQUIRE_EQ(a.semanticFingerprint(), b.semanticFingerprint());
    REQUIRE_EQ(a.canonicalBytes(), b.canonicalBytes());
}

CONTRACT_CASE("canonicalization does not depend on vector insertion order for keyed declarations") {
    auto a = simpleModel();
    auto b = simpleModel();
    std::reverse(b.molecule_types.begin(), b.molecule_types.end());
    auto ca = canonicalizeModel(a);
    auto cb = canonicalizeModel(b);
    REQUIRE_EQ(ca.semanticFingerprint(), cb.semanticFingerprint());
    REQUIRE_EQ(ca.canonicalBytes(), cb.canonicalBytes());
}

CONTRACT_CASE("semantic fingerprint changes on rate change") {
    auto a = canonicalizeModel(simpleModel());
    auto m = simpleModel();
    m.expanded_rules[0].rate = 2.5000001;
    auto b = canonicalizeModel(m);
    REQUIRE_NE(a.semanticFingerprint(), b.semanticFingerprint());
}

CONTRACT_CASE("semantic fingerprint ignores source line metadata") {
    auto m1 = simpleModel();
    auto m2 = simpleModel();
    m1.expanded_rules[0].source = SourceSpan{"a.xml", 10};
    m2.expanded_rules[0].source = SourceSpan{"b.xml", 999};
    REQUIRE_EQ(canonicalizeModel(m1).semanticFingerprint(),
               canonicalizeModel(m2).semanticFingerprint());
}

CONTRACT_CASE("diagnostic fingerprint can include source metadata separately") {
    auto m1 = simpleModel();
    auto m2 = simpleModel();
    m1.expanded_rules[0].source = SourceSpan{"a.xml", 10};
    m2.expanded_rules[0].source = SourceSpan{"b.xml", 999};
    auto c1 = canonicalizeModel(m1);
    auto c2 = canonicalizeModel(m2);
    REQUIRE_NE(c1.diagnosticFingerprint(), c2.diagnosticFingerprint());
}

CONTRACT_CASE("duplicate molecule type IDs are rejected") {
    auto m = simpleModel();
    auto duplicate = m.molecule_types.front();
    duplicate.name = "DifferentName";
    m.molecule_types.push_back(duplicate);
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("duplicate molecule type names are rejected") {
    auto m = simpleModel();
    MoleculeTypeIR c; c.id = 7; c.name = "A";
    m.molecule_types.push_back(c);
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("duplicate site names within a molecule type are rejected") {
    auto m = simpleModel();
    m.molecule_types[0].sites.push_back(SiteSpec{"x", {"u", "p"}});
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("duplicate enumerated site states are rejected") {
    auto m = simpleModel();
    m.molecule_types[0].sites[0].states = {"u", "p", "u"};
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("non-finite elementary rates are rejected") {
    for (double bad : {std::numeric_limits<double>::infinity(),
                       -std::numeric_limits<double>::infinity(),
                       std::numeric_limits<double>::quiet_NaN()}) {
        auto m = simpleModel();
        m.expanded_rules[0].rate = bad;
        REQUIRE_THROWS_AS(validateModel(m), ValidationError);
    }
}

CONTRACT_CASE("negative elementary rate is rejected") {
    auto m = simpleModel();
    m.expanded_rules[0].rate = -1.0;
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("site reference outside molecule schema is rejected") {
    auto m = simpleModel();
    m.expanded_rules[0].predicates[0].site = 99;
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("unknown molecule type reference is rejected") {
    auto m = simpleModel();
    m.expanded_rules[0].predicates[0].molecule_type = 900;
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("state index outside allowed enumeration is rejected") {
    auto m = simpleModel();
    m.expanded_rules[0].predicates[0].value = 99;
    REQUIRE_THROWS_AS(validateModel(m), ValidationError);
}

CONTRACT_CASE("canonicalization assigns dense deterministic IDs") {
    auto m = simpleModel();
    m.molecule_types[0].id = 77;
    m.molecule_types[1].id = 42;
    m.expanded_rules[0].id = 1234;
    auto c = canonicalizeModel(m);
    REQUIRE_EQ(c.model.molecule_types[0].id, 0u);
    REQUIRE_EQ(c.model.molecule_types[1].id, 1u);
    REQUIRE_EQ(c.model.expanded_rules[0].id, 0u);
}

CONTRACT_CASE("canonicalization rewrites all references after ID densification") {
    auto m = simpleModel();
    m.molecule_types[0].id = 77;
    m.molecule_types[1].id = 42;
    m.expanded_rules[0].predicates[0].molecule_type = 77;
    auto c = canonicalizeModel(m);
    REQUIRE_EQ(c.model.expanded_rules[0].predicates[0].molecule_type, 0u);
}

CONTRACT_CASE("canonical serialization is byte deterministic across repeated processes") {
    const auto bytes = canonicalizeModel(simpleModel()).canonicalBytes();
    for (int i = 0; i < 100; ++i)
        REQUIRE_EQ(canonicalizeModel(simpleModel()).canonicalBytes(), bytes);
}

CONTRACT_CASE("empty model has a stable nonzero semantic fingerprint") {
    ModelIR m;
    m.model_name = "empty";
    auto c = canonicalizeModel(m);
    REQUIRE_NE(c.semanticFingerprint(), 0ull);
    REQUIRE_EQ(c.semanticFingerprint(), canonicalizeModel(m).semanticFingerprint());
}

CONTRACT_CASE("model name can be excluded from simulation semantics") {
    auto a = simpleModel();
    auto b = simpleModel();
    a.model_name = "pretty_name_a";
    b.model_name = "pretty_name_b";
    CanonicalOptions opts;
    opts.include_model_name_in_semantic_hash = false;
    REQUIRE_EQ(canonicalizeModel(a, opts).semanticFingerprint(),
               canonicalizeModel(b, opts).semanticFingerprint());
}

CONTRACT_CASE("compiler options that affect semantics enter canonical key") {
    auto m = simpleModel();
    CanonicalOptions a;
    CanonicalOptions b;
    a.connectivity_policy = ConnectivityPolicy::Strict;
    b.connectivity_policy = ConnectivityPolicy::Legacy;
    REQUIRE_NE(canonicalizeModel(m, a).compileKey(),
               canonicalizeModel(m, b).compileKey());
}

CONTRACT_CASE("semantic hash is invariant to diagnostic-only annotations") {
    auto m1 = simpleModel();
    auto m2 = simpleModel();
    m1.expanded_rules[0].annotations["comment"] = "alpha";
    m2.expanded_rules[0].annotations["comment"] = "beta";
    REQUIRE_EQ(canonicalizeModel(m1).semanticFingerprint(),
               canonicalizeModel(m2).semanticFingerprint());
}

CONTRACT_CASE("canonical bytes never contain host pointer values") {
    auto bytes = canonicalizeModel(simpleModel()).canonicalBytes();
    REQUIRE(bytes.find("0x7f") == std::string::npos);
    REQUIRE(bytes.find("0x0000") == std::string::npos);
}

CONTRACT_MAIN("nfir-canonicalization")
#else
#error "RED CONTRACT: implement nfnext/canonical.hpp and nfnext/validator.hpp"
#endif
