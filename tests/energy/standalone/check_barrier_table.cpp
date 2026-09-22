#include "compile/energy/BarrierTable.hpp"
#include <cstdio>
#include <cmath>
using namespace bng::compile::energy;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)

int main() {
    // Symmetry under reversal: a barrier is a transition-state property.
    {
        auto f = ReactionCenterKey::stateChange("A","s","U","P");
        auto r = ReactionCenterKey::stateChange("A","s","P","U");
        CHECK(f == r);
        CHECK(!(f < r) && !(r < f));
        std::printf("  state key = %s\n", f.toString().c_str());
    }
    {
        auto f = ReactionCenterKey::binding("A","x","B","y");
        auto r = ReactionCenterKey::binding("B","y","A","x");
        CHECK(f == r);
        std::printf("  bond key  = %s\n", f.toString().c_str());
    }
    // Binding and state-change centers never collide.
    {
        auto b = ReactionCenterKey::binding("A","s","A","s");
        auto s = ReactionCenterKey::stateChange("A","s","U","P");
        CHECK(!(b == s));
    }
    // Different components / states stay distinct.
    {
        CHECK(!(ReactionCenterKey::stateChange("A","s","U","P") ==
                ReactionCenterKey::stateChange("A","t","U","P")));
        CHECK(!(ReactionCenterKey::stateChange("A","s","U","P") ==
                ReactionCenterKey::stateChange("A","s","U","Q")));
        CHECK(!(ReactionCenterKey::binding("A","x","B","y") ==
                ReactionCenterKey::binding("A","x","B","z")));
    }
    // Contributions accumulate; lookup of an absent center is the neutral 0.
    {
        BarrierTable table; std::string diag;
        auto key = ReactionCenterKey::stateChange("A","s","U","P");
        CHECK(table.empty());
        CHECK(table.lookup(key) == 0.0);
        CHECK(table.add(key, 2.0, "Gbar1", diag));
        CHECK(table.add(ReactionCenterKey::stateChange("A","s","P","U"), 0.5, "Gbar2", diag));
        CHECK(table.size() == 1);
        CHECK(std::fabs(table.lookup(key) - 2.5) < 1e-12);
        const auto* entry = table.find(key);
        CHECK(entry != nullptr);
        if (entry) {
            CHECK(entry->contributingPatterns == 2);
            CHECK(entry->sources.size() == 2 && entry->sources[0] == "Gbar1");
        }
        CHECK(!table.contains(ReactionCenterKey::stateChange("A","s","U","Q")));
    }
    // Non-finite barriers are rejected, not silently dropped.
    {
        BarrierTable table; std::string diag;
        auto key = ReactionCenterKey::stateChange("A","s","U","P");
        CHECK(!table.add(key, std::nan(""), "bad", diag));
        CHECK(!diag.empty());
        CHECK(!table.add(key, INFINITY, "bad2", diag));
        std::printf("  diagnostic: %s\n", diag.c_str());
    }
    // Negative barriers are legal (a catalyst lowers the transition state).
    {
        BarrierTable table; std::string diag;
        auto key = ReactionCenterKey::binding("A","x","B","y");
        CHECK(table.add(key, -1.5, "cat", diag));
        CHECK(std::fabs(table.lookup(key) + 1.5) < 1e-12);
    }
    std::printf(failures ? "BARRIER: %d failure(s)\n" : "BARRIER: all checks passed\n", failures);
    return failures ? 1 : 0;
}
