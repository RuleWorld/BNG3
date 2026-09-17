#include "nfnext/generic_matcher.hpp"
#include "nfnext/transformation.hpp"

#include <iostream>
#include <stdexcept>
#include <string>

using namespace nfnext;

struct Checks {
    int passed{0};
    int total{0};
    void check(bool value, const std::string& message) {
        ++total;
        if (!value) throw std::runtime_error(message);
        ++passed;
    }
};

static ModelIR makeModel() {
    ModelIR model;
    model.model_name = "formal-contract";
    MoleculeTypeIR a;
    a.id = 0; a.name = "A"; a.sites.push_back({"x", {"u", "p", "q"}});
    MoleculeTypeIR b;
    b.id = 1; b.name = "B"; b.sites.push_back({"y", {}});
    MoleculeTypeIR c;
    c.id = 2; c.name = "C"; c.sites.push_back({"z", {}}); c.sites.push_back({"w", {}});
    model.molecule_types = {a, b, c};
    return model;
}

static void matcherChecks(Checks& t, const ModelIR& model) {
    GenericMatcher matcher(model);
    GenericGraphState state(model);
    auto a1 = state.create(0);
    auto a2 = state.create(0);
    auto b = state.create(1);
    state.setSiteState(a1, 0, 0);
    state.setSiteState(a2, 0, 1);

    PatternIR p;
    auto na = p.addNode(0);
    p.node(na).siteState(0, 0);
    p.node(na).siteFree(0);
    auto nb = p.addNode(1);
    p.node(nb).siteFree(0);
    p.requireDifferentComplex(na, nb);
    auto m = matcher.enumerate(p, state, MatchMode::ReferenceBacktracking);
    t.check(m.size() == 1, "A(x~u)+B(y) should have one match");
    t.check(m[0].particle(0) == a1, "state predicate chose wrong A");

    PatternIR stateSet;
    auto ns = stateSet.addNode(0);
    stateSet.node(ns).siteStateSet(0, {0, 1});
    auto ms = matcher.enumerate(stateSet, state, MatchMode::ReferenceBacktracking);
    t.check(ms.size() == 2, "state-set matcher should accept u and p");

    state.bind(a1, 0, b, 0);
    auto afterBond = matcher.enumerate(p, state, MatchMode::ReferenceBacktracking);
    t.check(afterBond.empty(), "DifferentComplex/free constraints should reject bound A-B");

    PatternIR same;
    auto s0 = same.addNode(0);
    auto s1 = same.addNode(1);
    same.requireSameComplex(s0, s1);
    same.requireBond(s0, 0, s1, 0);
    auto sameMatches = matcher.enumerate(same, state, MatchMode::ReferenceBacktracking);
    t.check(sameMatches.size() == 1, "same-complex exact-bond pattern should match once");

    PatternIR symmetric;
    auto q0 = symmetric.addNode(0);
    auto q1 = symmetric.addNode(0);
    symmetric.requireDifferentComplex(q0, q1);
    symmetric.markInterchangeable({q0, q1});
    auto sym = matcher.enumerate(symmetric, state, MatchMode::ReferenceBacktracking);
    t.check(bruteForceAutomorphismCount(symmetric, model) == 2,
            "two identical interchangeable nodes should have automorphism count 2");
    t.check(sym.size() == 1, "interchangeable nodes should canonicalize swapped embeddings");

    GenericGraphState chain(model);
    auto ca = chain.create(0);
    auto cc = chain.create(2);
    auto cb = chain.create(1);
    chain.bind(ca, 0, cc, 0);
    chain.bind(cc, 1, cb, 0);
    PatternIR connected;
    auto c0 = connected.addNode(0);
    auto c1 = connected.addNode(1);
    connected.requireConnectedTo(c0, c1);
    auto connectedMatches = matcher.enumerate(connected, chain, MatchMode::ReferenceBacktracking);
    t.check(connectedMatches.size() == 1, "connected_to should accept an indirect path");
}

static void transformationChecks(Checks& t, const ModelIR& model) {
    GenericGraphState state(model);
    auto a = state.create(0);
    auto b = state.create(1);
    state.setSiteState(a, 0, 0);

    MatchEmbedding pair;
    pair.bindNode(0, a);
    pair.bindNode(1, b);

    TransformationIR setAndBind;
    setAndBind.setState(0, 0, 1);
    setAndBind.addBond(0, 0, 1, 0);
    applyTransformation(setAndBind, pair, state);
    t.check(state.siteState(a, 0) == 1, "SetState failed");
    t.check(state.bound(a, 0) && state.bound(b, 0), "AddBond failed");
    t.check(state.sameComplex(a, b), "AddBond did not connect complexes");

    TransformationIR unbind;
    unbind.deleteBond(0, 0, 1, 0);
    applyTransformation(unbind, pair, state);
    t.check(!state.bound(a, 0) && !state.bound(b, 0), "DeleteBond failed");

    TransformationIR create;
    auto newB = create.createMolecule(1, {});
    create.addBondExistingToCreated(0, 0, newB, 0);
    MatchEmbedding one;
    one.bindNode(0, a);
    auto createResult = applyTransformation(create, one, state);
    auto b2 = createResult.created(newB);
    t.check(state.alive(b2), "CreateMolecule failed");
    t.check(state.bound(a, 0) && state.bound(b2, 0), "AddBondExistingToCreated failed");

    state.unbind(a, 0);
    TransformationIR twoCreated;
    auto c1 = twoCreated.createMolecule(2, {});
    auto c2 = twoCreated.createMolecule(2, {});
    twoCreated.addBondCreated(c1, 0, c2, 0);
    MatchEmbedding empty;
    auto twoResult = applyTransformation(twoCreated, empty, state);
    auto pc1 = twoResult.created(c1);
    auto pc2 = twoResult.created(c2);
    t.check(state.bound(pc1, 0) && state.bound(pc2, 0), "AddBondCreated failed");

    TransformationIR destroyOne;
    destroyOne.destroyMolecule(0);
    MatchEmbedding kill;
    kill.bindNode(0, b);
    applyTransformation(destroyOne, kill, state);
    t.check(!state.alive(b), "DestroyMolecule failed");

    GenericGraphState complexState(model);
    auto xa = complexState.create(0);
    auto xb = complexState.create(1);
    complexState.bind(xa, 0, xb, 0);
    TransformationIR destroyComplex;
    destroyComplex.destroyComplexContaining(0);
    MatchEmbedding complexEmbedding;
    complexEmbedding.bindNode(0, xa);
    applyTransformation(destroyComplex, complexEmbedding, complexState);
    t.check(!complexState.alive(xa) && !complexState.alive(xb), "DestroyComplex failed");

    TransformationIR createdState;
    auto createdA = createdState.createMolecule(0, {{0, 2}});
    auto stateResult = applyTransformation(createdState, empty, state);
    auto qa = stateResult.created(createdA);
    t.check(state.siteState(qa, 0) == 2, "created molecule initial state failed");
}

int main() {
    try {
        Checks checks;
        auto model = makeModel();
        matcherChecks(checks, model);
        transformationChecks(checks, model);
        std::cout << "NFNEXT CONTRACT PASS: " << checks.passed << "/" << checks.total << " checks\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "NFNEXT CONTRACT FAIL: " << e.what() << "\n";
        return 1;
    }
}
