// RED CONTRACT: transactional NFsim reaction construction.
#include <catch2/catch_test_macros.hpp>
#include "NFinput/ReactionBuildBatch.hh"

using namespace NFinput;

TEST_CASE("staged reactions commit together") {
    FakeSystem system;
    ReactionBuildBatch batch(system);
    batch.stage(std::make_unique<FakeReaction>("forward"));
    batch.stage(std::make_unique<FakeReaction>("reverse"));
    CHECK(system.reactionCount() == 0);
    batch.commit();
    CHECK(system.reactionCount() == 2);
}

TEST_CASE("destruction without commit rolls back all staged reactions") {
    FakeSystem system;
    {
        ReactionBuildBatch batch(system);
        batch.stage(std::make_unique<FakeReaction>("forward"));
        CHECK(system.reactionCount() == 0);
    }
    CHECK(system.reactionCount() == 0);
    CHECK(FakeReaction::liveCount() == 0);
}

TEST_CASE("reverse construction failure cannot leave half reversible rule") {
    FakeSystem system;
    const bool ok = buildReversibleTransactionally(system,
        []{ return std::make_unique<FakeReaction>("forward"); },
        []() -> std::unique_ptr<FakeReaction> { return nullptr; });
    CHECK_FALSE(ok);
    CHECK(system.reactionCount() == 0);
}

TEST_CASE("double commit is rejected rather than double-registering reactions") {
    FakeSystem system; ReactionBuildBatch batch(system);
    batch.stage(std::make_unique<FakeReaction>("r")); batch.commit();
    CHECK_THROWS(batch.commit());
    CHECK(system.reactionCount()==1);
}

TEST_CASE("staging after commit is rejected") {
    FakeSystem system; ReactionBuildBatch batch(system); batch.commit();
    CHECK_THROWS(batch.stage(std::make_unique<FakeReaction>("late")));
    CHECK(system.reactionCount()==0);
}
