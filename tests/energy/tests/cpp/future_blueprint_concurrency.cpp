// RED CONTRACT: immutable blueprint + per-trajectory mutable state must be thread-safe.
#include <future>
#include <vector>
#include <catch2/catch_test_macros.hpp>
#include "compile/CompiledNfBlueprint.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("concurrent trajectory instantiation has no shared mutable simulation state") {
    auto model=bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 1000
end seed species
begin reaction rules
 A(x)->0 0.1
end reaction rules
)BNG");
    REQUIRE(model);
    auto bp=bng::compile::CompiledNfBlueprint::compile(*model);
    std::vector<std::future<int>> jobs;
    for (int seed=1;seed<=16;++seed) jobs.push_back(std::async(std::launch::async,[&,seed]{
        auto s=bp.instantiate(seed); s->stepTo(10.0,true); return s->getGlobalEventCounter();
    }));
    std::vector<int> concurrent; for(auto& j:jobs) concurrent.push_back(j.get());
    std::vector<int> serial;
    for (int seed=1;seed<=16;++seed) { auto s=bp.instantiate(seed); s->stepTo(10.0,true); serial.push_back(s->getGlobalEventCounter()); }
    CHECK(concurrent==serial);
}
