// RED CONTRACT: connected reverse/unbinding path evaluates endpoint context exactly.
#include <filesystem>
#include <fstream>
#include <memory>
#include <sstream>
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include "NFcore/NFcore.hh"
#include "NFinput/NFinput_fromAst.hh"
#include "parser/BNGAstVisitor.hpp"

TEST_CASE("bound mixed-context reverse propensity matches materialized oracle") {
    std::ifstream in(std::filesystem::path(BNG_ENERGY_FIXTURE_DIR)/"bound_mixed_reverse.bngl");
    REQUIRE(in.good()); std::ostringstream ss; ss<<in.rdbuf();
    auto build=[&](bool on){
#ifdef _WIN32
        _putenv_s("BNG_NFSIM_GENERAL_ENERGY",on?"1":"");
#else
        if(on)setenv("BNG_NFSIM_GENERAL_ENERGY","1",1);else unsetenv("BNG_NFSIM_GENERAL_ENERGY");
#endif
        auto model=bng::parser::parseModel(ss.str()); REQUIRE(model); int lim=-1;
        std::unique_ptr<NFcore::System> s(NFinput::buildSystemFromAst(*model,false,-1,false,lim,{}));
        REQUIRE(s);s->setUniversalTraversalLimit(lim);s->prepareForSimulation();return s;
    };
    auto legacy=build(false),general=build(true);
    double a0=0,a1=0;for(auto*r:legacy->getAllReactions())a0+=r->get_a();for(auto*r:general->getAllReactions())a1+=r->get_a();
    CHECK(a1==Catch::Approx(a0).epsilon(1e-12));
}
