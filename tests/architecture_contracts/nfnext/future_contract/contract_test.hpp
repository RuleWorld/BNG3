#pragma once

#include <cmath>
#include <cstdint>
#include <exception>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nfnext_contract {

struct Failure : std::runtime_error {
    Failure(const char* file, int line, const std::string& expr, const std::string& detail = {})
        : std::runtime_error(format(file, line, expr, detail)) {}
private:
    static std::string format(const char* file, int line, const std::string& expr,
                              const std::string& detail) {
        std::ostringstream os;
        os << file << ':' << line << ": contract failed: " << expr;
        if (!detail.empty()) os << " (" << detail << ')';
        return os.str();
    }
};

struct TestCase {
    const char* name;
    void (*fn)();
};

inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> tests;
    return tests;
}

struct Registrar {
    Registrar(const char* name, void (*fn)()) { registry().push_back(TestCase{name, fn}); }
};

inline std::uint64_t& checkCount() {
    static std::uint64_t count = 0;
    return count;
}

inline void require(bool condition, const char* file, int line, const char* expression) {
    ++checkCount();
    if (!condition) throw Failure(file, line, expression);
}

template <class A, class B>
inline void requireEq(const A& a, const B& b, const char* file, int line,
                      const char* ea, const char* eb) {
    ++checkCount();
    if (!(a == b)) {
        std::ostringstream os;
        os << ea << " != " << eb;
        throw Failure(file, line, "equality", os.str());
    }
}

template <class A, class B>
inline void requireNe(const A& a, const B& b, const char* file, int line,
                      const char* ea, const char* eb) {
    ++checkCount();
    if (!(a != b)) {
        std::ostringstream os;
        os << ea << " == " << eb;
        throw Failure(file, line, "inequality", os.str());
    }
}

inline void requireNear(double a, double b, double tolerance, const char* file, int line,
                        const char* ea, const char* eb) {
    ++checkCount();
    if (!(std::isfinite(a) && std::isfinite(b) && std::abs(a - b) <= tolerance)) {
        std::ostringstream os;
        os << ea << '=' << a << ", " << eb << '=' << b << ", tol=" << tolerance;
        throw Failure(file, line, "near", os.str());
    }
}

template <class Exception, class Fn>
inline void requireThrows(Fn&& fn, const char* file, int line, const char* expression) {
    ++checkCount();
    bool threw_expected = false;
    try {
        fn();
    } catch (const Exception&) {
        threw_expected = true;
    } catch (...) {
        throw Failure(file, line, expression, "threw wrong exception type");
    }
    if (!threw_expected) throw Failure(file, line, expression, "did not throw");
}

template <class Fn>
inline void requireNoThrow(Fn&& fn, const char* file, int line, const char* expression) {
    ++checkCount();
    try {
        fn();
    } catch (const std::exception& e) {
        throw Failure(file, line, expression, std::string("unexpected exception: ") + e.what());
    } catch (...) {
        throw Failure(file, line, expression, "unexpected non-std exception");
    }
}

inline int runAll(const char* suite) {
    std::size_t passed = 0;
    std::cerr << "[NFnext contract] " << suite << ": " << registry().size() << " cases\n";
    for (const auto& test : registry()) {
        try {
            test.fn();
            ++passed;
        } catch (const std::exception& e) {
            std::cerr << "FAIL " << test.name << "\n  " << e.what() << '\n';
        } catch (...) {
            std::cerr << "FAIL " << test.name << "\n  unknown exception\n";
        }
    }
    std::cerr << "[NFnext contract] passed=" << passed
              << " failed=" << (registry().size() - passed)
              << " checks=" << checkCount() << '\n';
    return passed == registry().size() ? 0 : 1;
}

} // namespace nfnext_contract

#define NFNEXT_JOIN2(a,b) a##b
#define NFNEXT_JOIN(a,b) NFNEXT_JOIN2(a,b)
#define CONTRACT_CASE(name) \
    static void NFNEXT_JOIN(contract_case_, __LINE__)(); \
    static ::nfnext_contract::Registrar NFNEXT_JOIN(contract_reg_, __LINE__)( \
        name, &NFNEXT_JOIN(contract_case_, __LINE__)); \
    static void NFNEXT_JOIN(contract_case_, __LINE__)()

#define REQUIRE(x) ::nfnext_contract::require(!!(x), __FILE__, __LINE__, #x)
#define REQUIRE_EQ(a,b) ::nfnext_contract::requireEq((a),(b),__FILE__,__LINE__,#a,#b)
#define REQUIRE_NE(a,b) ::nfnext_contract::requireNe((a),(b),__FILE__,__LINE__,#a,#b)
#define REQUIRE_NEAR(a,b,t) ::nfnext_contract::requireNear((a),(b),(t),__FILE__,__LINE__,#a,#b)
#define REQUIRE_THROWS_AS(expr, ex) \
    ::nfnext_contract::requireThrows<ex>([&](){ (void)(expr); },__FILE__,__LINE__,#expr)
#define REQUIRE_NO_THROW(...) \
    ::nfnext_contract::requireNoThrow([&](){ (void)(__VA_ARGS__); },__FILE__,__LINE__,#__VA_ARGS__)

#define CONTRACT_MAIN(suite_name) \
    int main() { return ::nfnext_contract::runAll(suite_name); }
