// RED CONTRACT: batch trajectory API should be equivalent to repeated scalar NF calls.
#include <catch2/catch_test_macros.hpp>
#include "bindings/NfBatchRunner.hpp"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("batched independent trajectories equal scalar calls for each seed") {
    auto model = bng::parser::parseModel(R"BNG(
begin molecule types
 A(x)
end molecule types
begin seed species
 A(x) 100
end seed species
begin observables
 Molecules A_total A()
end observables
begin reaction rules
 A(x)->0 0.1
end reaction rules
)BNG");
    REQUIRE(model);
    const std::vector<unsigned long> seeds = {1,42,2026,424242};
    auto batch = bng::runtime::simulateNfBatch(*model, 10.0, 10, seeds);
    REQUIRE(batch.size() == seeds.size());
    for (std::size_t i=0;i<seeds.size();++i) {
        auto scalar = bng::runtime::simulateNf(*model,10.0,10,seeds[i]);
        CHECK(batch[i].time == scalar.time);
        CHECK(batch[i].observables == scalar.observables);
    }
}
