// libFuzzer target for EnergyDeltaPlan. Build separately with -fsanitize=fuzzer,address,undefined.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>
#include "compile/energy/EnergyDeltaPlan.hpp"
#include "energy_test_helpers.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    using namespace bng::compile::energy;
    if (size < 4) return 0;
    const std::size_t ncond = 1 + (data[0] % 8);
    const std::size_t nterm = 1 + (data[1] % 24);
    std::vector<EnergyCondition> conditions(ncond);
    for (std::size_t i=0;i<ncond;++i) {
        conditions[i].kind = (i & 1) ? ConditionKind::State : ConditionKind::Bond;
        conditions[i].reactantIndex = int(i & 1);
        conditions[i].moleculeType = (i & 1) ? "B" : "A";
        conditions[i].componentName = "s" + std::to_string(i);
        conditions[i].expectedState = (i & 1) ? "P" : "";
    }
    const std::uint64_t valid = (std::uint64_t{1} << ncond) - 1;
    std::vector<EnergyTerm> terms;
    std::vector<std::pair<double,std::uint64_t>> literal;
    for (std::size_t i=0;i<nterm;++i) {
        const std::uint8_t b = data[(2+i) % size];
        const double energy = (double(int(b)-128))/16.0;
        const std::uint64_t mask = 1 + (std::uint64_t(data[(3+i) % size]) % valid);
        terms.push_back({energy,mask,i}); literal.push_back({energy,mask});
    }
    auto plan = EnergyDeltaPlan::factorized(0.125,conditions,terms);
    if (!plan) std::abort();
    for (std::uint64_t mask=0;mask<=valid;++mask) {
        auto dg=plan->tryDeltaG(mask);
        if (!dg || !bng3_test::nearly_equal(*dg,bng3_test::literal_delta_g(0.125,mask,literal)))
            std::abort();
    }
    return 0;
}
