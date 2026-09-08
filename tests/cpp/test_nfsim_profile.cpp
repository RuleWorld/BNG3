#include <catch2/catch_test_macros.hpp>

#include "NFcore/profile.hh"

#include <sstream>
#include <string>

TEST_CASE("NFsim profiler records bounded phase and reaction diagnostics") {
    NFcore::NFsimProfile profile;
    CHECK_FALSE(profile.isEnabled());

    profile.enable("-");
    CHECK(profile.isEnabled());
    profile.recordPhase("parse", 0);
    profile.beginReactionFire(7, "r\tname");
    profile.recordMatchCandidate();
    profile.recordMembershipUpdate();
    profile.recordBind(0.125);
    const NFcore::ProfileConnectivityContext previous =
        profile.beginConnectivityContext(NFcore::PROFILE_CONNECTIVITY_MATCHING);
    profile.recordConnectivity(0.25, 3, 4,
                               NFcore::PROFILE_CONNECTIVITY_MATCHING,
                               11, 15, 7);
    profile.endConnectivityContext(previous);
    profile.recordReactionFire(7, "r\tname", 0, false);

    std::ostringstream output;
    profile.write(output);
    const std::string report = output.str();
    CHECK(report.find("# NFsim opt-in profile v4") != std::string::npos);
    CHECK(report.find("phase\tparse\t") != std::string::npos);
    CHECK(report.find("reaction\t7\tr name\t1\t0\t") != std::string::npos);
    CHECK(report.find("connectivity_context\t7\tr name\tmatching\t1\t3\t4\t")
          != std::string::npos);
}

TEST_CASE("NFsim profiler reset removes prior samples") {
    NFcore::NFsimProfile profile;
    profile.enable("-");
    profile.beginReactionFire(9, "old");
    profile.recordReactionFire(9, "old", 0, true);
    profile.reset();

    std::ostringstream output;
    profile.write(output);
    CHECK(output.str().find("reaction\t9\t") == std::string::npos);
}
