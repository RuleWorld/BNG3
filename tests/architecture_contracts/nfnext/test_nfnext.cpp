#ifdef NDEBUG
#undef NDEBUG
#endif
#include "nfnext/cache.hpp"
#include "nfnext/compiler.hpp"
#include "nfnext/compiled_model.hpp"
#include "nfnext/generic_state.hpp"
#include "nfnext/counter_rng.hpp"
#include "nfnext/fenwick.hpp"
#include "nfnext/lattice.hpp"
#include "nfnext/soa_arena.hpp"
#include "nfnext/scheduler.hpp"
#include "nfnext/trajectory.hpp"

#include <cassert>
#include <cstdio>
#include <iostream>

using namespace nfnext;

static ExpandedRuleIR makeElong(std::uint32_t i) {
    ExpandedRuleIR r;
    r.id = i - 1;
    r.name = "elongate_" + std::to_string(i);
    r.rate = 4.0 + 0.01 * i;
    r.predicates.push_back(PredicateIR{PredicateKind::PositionEq, 0, 0, static_cast<std::int32_t>(i), 0});
    r.predicates.push_back(PredicateIR{PredicateKind::NeighborFree, 0, 0, 1, 0});
    r.actions.push_back(ActionIR{ActionKind::MovePosition, 0, 0, 1, 0});
    return r;
}

int main() {
    {
        CounterRng a(123, 7), b(123, 7), c(123, 8);
        assert(a.u64(99) == b.u64(99));
        assert(a.u64(99) != c.u64(99));
    }
    {
        ParticleArena arena;
        auto x = arena.create(2, 4);
        assert(arena.alive(x));
        arena.destroy(x);
        assert(!arena.alive(x));
        auto y = arena.create(3, 9);
        assert(y.index == x.index && y.generation != x.generation);
    }
    {
        FenwickTree f(4);
        f.set(0, 1); f.set(1, 2); f.set(2, 3); f.set(3, 4);
        assert(f.total() == 10);
        assert(f.lowerBound(0.0) == 0);
        assert(f.lowerBound(1.0) == 1);
        assert(f.lowerBound(9.999) == 3);
    }
    {
        HierarchicalScheduler s({2, 3});
        s.set(0, 0, 1.0); s.set(0, 1, 2.0);
        s.set(1, 0, 3.0); s.set(1, 1, 0.0); s.set(1, 2, 4.0);
        assert(s.total() == 10.0);
        auto a = s.sample(0.5); assert(a.family == 0 && a.channel == 0);
        auto b = s.sample(3.1); assert(b.family == 1 && b.channel == 0);
        auto c = s.sample(9.9); assert(c.family == 1 && c.channel == 2);
    }
    {
        ModelIR m; m.model_name = "rasi-mini"; m.lattice_length = 32;
        for (std::uint32_t i = 1; i <= 20; ++i) m.expanded_rules.push_back(makeElong(i));
        ModelCompiler compiler;
        auto report = compiler.compile(m);
        assert(report.family_stats.input_rules == 20);
        assert(m.rule_families.size() == 1);
        assert(m.rule_families[0].coordinate_parameterized);
        assert(m.rule_families[0].begin_index == 1 && m.rule_families[0].end_index == 20);
        assert(m.rule_families[0].predicates[0].value == 0); // coordinate offset
        assert(m.preferred_backend == BackendKind::Lattice);
        assert(!m.dependencies.feature_to_families.empty());
        const char* cache = "nfnext_test.nfir";
        ModelCache::save(m, cache);
        auto loaded = ModelCache::load(cache);
        assert(loaded.rule_families.size() == 1);
        assert(loaded.fingerprint() == m.fingerprint());
        std::remove(cache);
    }
    {
        auto a = makeElong(1);
        auto b = makeElong(2);
        a.predicates.push_back(PredicateIR{PredicateKind::SiteStateEq, 0, 1, 7, 0});
        b.predicates.push_back(PredicateIR{PredicateKind::SiteStateEq, 0, 1, 8, 0});
        auto r = collapseIndexedRuleFamilies(std::vector<ExpandedRuleIR>{a, b});
        assert(r.families.size() == 2); // do not over-collapse state differences
    }
    {
        ModelIR m;
        RuleFamilyIR f;
        f.id = 0;
        f.name = "scoped";
        f.default_rate = 2.0;
        f.rate_law.kind = RateLawKind::Function;
        f.rate_law.expression = "k*Obs";
        f.predicates.push_back(PredicateIR::stateSet(0, 0, {1, 3, 5}));
        f.pattern.addNode(0);
        f.pattern.addNode(0);
        f.pattern.node(0).siteStateSet(0, {1, 3, 5});
        f.pattern.requireBond(0, 1, 1, 1);
        f.pattern.molecularity.push_back(MolecularityConstraint::sameComplex(0, 1));
        f.pattern.allowAlias(0, 1);
        f.pattern.requireConnectedTo(0, 1);
        f.pattern.markInterchangeable({0, 1});
        f.source_rules.push_back(0);
        m.rule_families.push_back(f);
        const auto before = m.fingerprint();
        const char* cache = "/tmp/nfnext_semantic_family.nfir";
        ModelCache::save(m, cache);
        const auto loaded = ModelCache::load(cache);
        std::remove(cache);
        assert(loaded.fingerprint() == before);
        assert(loaded.rule_families[0].rate_law.expression == "k*Obs");
        assert(loaded.rule_families[0].predicates[0].state_set ==
               std::vector<std::int32_t>({1, 3, 5}));
        assert(loaded.rule_families[0].pattern.molecularity[0].kind ==
               MolecularityKind::SameComplex);
        assert(loaded.rule_families[0].pattern.nodes.size() == 2);
        assert(loaded.rule_families[0].pattern.nodes[0].constraints[0].states ==
               std::vector<std::int32_t>({1, 3, 5}));
        assert(loaded.rule_families[0].pattern.bonds.size() == 1);
        assert(loaded.rule_families[0].pattern.aliases.size() == 1);
        assert(loaded.rule_families[0].pattern.connected_to.size() == 1);
        assert(loaded.rule_families[0].pattern.interchangeable.size() == 1);
    }
    {
        ModelIR m;
        MoleculeTypeIR mt; mt.id = 0; mt.name = "A"; mt.sites = {SiteSpec{"x", {"u", "p"}}, SiteSpec{"b", {}}};
        m.molecule_types.push_back(mt);
        RuleFamilyIR f; f.id = 0; f.name = "local";
        f.predicates.push_back(PredicateIR{PredicateKind::SiteStateEq, 0, 0, 1, 0});
        f.predicates.push_back(PredicateIR{PredicateKind::SiteFree, 0, 1, 0, 0});
        m.rule_families.push_back(f);
        ModelCompiler::buildDependencies(m);
        CompiledModel cm(std::move(m));
        GenericGraphState g(cm.ir());
        auto a = g.create(0), b = g.create(0);
        g.setSiteState(a, 0, 1);
        assert(g.matchesLocal(a, cm.family(0).predicates));
        g.bind(a, 1, b, 1);
        assert(!g.matchesLocal(a, cm.family(0).predicates));
        g.unbind(a, 1);
        assert(g.matchesLocal(a, cm.family(0).predicates));
        const auto old = a; g.destroy(a); assert(!g.alive(old));
        auto reused = g.create(0); assert(reused.index == old.index && reused.generation != old.generation);
    }
    {
        GenomeLattice lattice({16, 2.0, false});
        lattice.place(0); lattice.place(3);
        assert(lattice.totalPropensity() == 4.0);
        auto r = lattice.run(20, 100.0, 42, 0);
        assert(r.events > 0 && r.events <= 20);
        assert(r.hops == r.events);
        assert(r.null_events == 0);
    }
    {
        LatticeConfig cfg; cfg.length = 20; cfg.hop_rate = 5.0; cfg.footprint = 3;
        cfg.initiation_rate = 2.0; cfg.termination_rate = 3.0;
        GenomeLattice lattice(cfg);
        assert(lattice.canInitiate());
        assert(lattice.initiate());
        assert(!lattice.canInitiate());
        assert(lattice.occupied(0) && lattice.occupied(1) && lattice.occupied(2));
        assert(lattice.isHead(0));
        assert(lattice.hop(0));
        assert(!lattice.occupied(0) && lattice.occupied(1) && lattice.occupied(3));
        auto r = lattice.run(1000, 1000.0, 1234, 2);
        assert(r.events > 0);
        assert(r.null_events == 0);
        assert(r.initiations + r.hops + r.terminations == r.events);
    }
    {
        TrajectoryRequest req;
        req.lattice = {64, 3.0, false};
        req.initial_positions = {0, 5, 10};
        req.max_events = 100;
        req.max_time = 50.0;
        req.seed = 777;
        auto serial = TrajectoryBatchRunner::run(req, 16, 1);
        auto parallel = TrajectoryBatchRunner::run(req, 16, 4);
        assert(serial.size() == parallel.size());
        for (std::size_t i = 0; i < serial.size(); ++i) {
            assert(serial[i].run.events == parallel[i].run.events);
            assert(serial[i].run.null_events == parallel[i].run.null_events);
            assert(serial[i].run.time == parallel[i].run.time);
        }
    }
    std::cout << "nfnext tests: PASS\n";
    return 0;
}
