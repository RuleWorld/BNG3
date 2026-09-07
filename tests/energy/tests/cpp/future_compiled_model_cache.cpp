// RED CONTRACT: immutable compile-once cache, including concurrency.
#include <atomic>
#include <future>
#include <stdexcept>
#include <thread>
#include <vector>
#include <catch2/catch_test_macros.hpp>
#include "compile/cache/CompiledModelCache.hpp"

using namespace bng::compile::cache;

TEST_CASE("same fingerprint compiles exactly once") {
    CompiledModelCache cache;
    std::atomic<int> builds{0};
    auto builder = [&] {
        ++builds;
        return std::make_shared<const FakeCompiledModel>("m");
    };
    auto a = cache.getOrCompile<FakeCompiledModel>("sha256:model", builder);
    auto b = cache.getOrCompile<FakeCompiledModel>("sha256:model", builder);
    CHECK(a.get() == b.get());
    CHECK(builds.load() == 1);
    CHECK(cache.hits() == 1);
    CHECK(cache.misses() == 1);
}

TEST_CASE("concurrent lookup publishes one immutable compiled object") {
    CompiledModelCache cache;
    std::atomic<int> builds{0};
    std::vector<std::shared_ptr<const FakeCompiledModel>> results(32);
    std::vector<std::thread> threads;
    for (int i=0;i<32;++i) threads.emplace_back([&,i]{
        results[i] = cache.getOrCompile<FakeCompiledModel>("same", [&]{
            ++builds;
            return std::make_shared<const FakeCompiledModel>("same");
        });
    });
    for (auto& t : threads) t.join();
    for (const auto& p : results) CHECK(p.get() == results.front().get());
    CHECK(builds.load() == 1);
}

TEST_CASE("different fingerprints never alias compiled objects") {
    CompiledModelCache cache;
    auto a=cache.getOrCompile<FakeCompiledModel>("a",[]{return std::make_shared<const FakeCompiledModel>("a");});
    auto b=cache.getOrCompile<FakeCompiledModel>("b",[]{return std::make_shared<const FakeCompiledModel>("b");});
    REQUIRE(a); REQUIRE(b);
    CHECK(a.get()!=b.get());
}

TEST_CASE("failed builder does not poison cache entry") {
    CompiledModelCache cache;
    int attempts=0;
    CHECK_THROWS(cache.getOrCompile<FakeCompiledModel>("x",[&]()->std::shared_ptr<const FakeCompiledModel>{
        ++attempts; throw std::runtime_error("compile failed");
    }));
    auto ok=cache.getOrCompile<FakeCompiledModel>("x",[&]{++attempts;return std::make_shared<const FakeCompiledModel>("x");});
    REQUIRE(ok);
    CHECK(attempts==2);
}

TEST_CASE("weakly-held expired compiled object can be rebuilt") {
    CompiledModelCache cache;
    int builds=0;
    {
        auto a=cache.getOrCompile<FakeCompiledModel>("x",[&]{++builds;return std::make_shared<const FakeCompiledModel>("x");});
        REQUIRE(a);
    }
    cache.pruneExpired();
    auto b=cache.getOrCompile<FakeCompiledModel>("x",[&]{++builds;return std::make_shared<const FakeCompiledModel>("x");});
    REQUIRE(b);
    CHECK(builds==2);
}

TEST_CASE("parallel compilation of different keys does not serialize all builders") {
    CompiledModelCache cache;
    std::atomic<int> entered{0};
    auto compile=[&](const std::string& key){return cache.getOrCompile<FakeCompiledModel>(key,[&]{
        ++entered; while(entered.load()<2) std::this_thread::yield();
        return std::make_shared<const FakeCompiledModel>(key);
    });};
    auto f1=std::async(std::launch::async,[&]{return compile("a");});
    auto f2=std::async(std::launch::async,[&]{return compile("b");});
    REQUIRE(f1.get()); REQUIRE(f2.get());
}
