// RED CONTRACT: experimental backend opt-in must have unambiguous environment parsing.
#include <cstdlib>
#include <catch2/catch_test_macros.hpp>
#include "compile/energy/EnergyFeatureFlags.hpp"

TEST_CASE("general energy backend is disabled when environment variable is absent") {
#ifdef _WIN32
    _putenv_s("BNG_NFSIM_GENERAL_ENERGY","");
#else
    unsetenv("BNG_NFSIM_GENERAL_ENERGY");
#endif
    CHECK_FALSE(bng::compile::energy::generalEnergyEnabled());
}

TEST_CASE("only explicit truthy values enable experimental backend") {
    for(const char* value:{"1","true","TRUE","yes"}){
#ifdef _WIN32
        _putenv_s("BNG_NFSIM_GENERAL_ENERGY",value);
#else
        setenv("BNG_NFSIM_GENERAL_ENERGY",value,1);
#endif
        CHECK(bng::compile::energy::generalEnergyEnabled());
    }
    for(const char* value:{"0","false","FALSE","no",""}){
#ifdef _WIN32
        _putenv_s("BNG_NFSIM_GENERAL_ENERGY",value);
#else
        setenv("BNG_NFSIM_GENERAL_ENERGY",value,1);
#endif
        CHECK_FALSE(bng::compile::energy::generalEnergyEnabled());
    }
}
