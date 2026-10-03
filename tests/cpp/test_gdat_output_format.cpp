// Regression coverage for the byte format of the .gdat/.cdat numeric output
// loop in OdeIntegrator::writeOutputFiles.
//
// Those loops emit every numeric field as the 18-column right-justified form
// of "%.12e". A performance change to how the digits are produced is only
// acceptable while the emitted bytes are unchanged, so this test pins the exact
// bytes for the digit edges a formatter is most likely to break: signed zero,
// denormals, DBL_MIN, DBL_MAX, very large and very small magnitudes, negatives,
// and values whose last printed digit sits on a rounding boundary.
//
// The expected bytes are built here with snprintf("%18.12e"), which states the
// format independently of how production produces it (production uses
// std::to_chars). The two are deliberately different calls, so a drift in the
// writer is caught rather than mirrored. bench evidence recorded in the PR
// establishes that both agree with the original operator<< implementation over
// 8,998,531 doubles; this test is what stops them from drifting apart later.

#include <catch2/catch_test_macros.hpp>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "parser/BNGAstVisitor.hpp"

using namespace bng;

namespace {

std::string readAll(const std::filesystem::path& p) {
    std::ifstream in(p, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

// The established byte form of one field: "%18.12e".
std::string field(double value) {
    char buf[64];
    const int n = std::snprintf(buf, sizeof(buf), "%18.12e", value);
    return std::string(buf, static_cast<std::size_t>(n));
}

std::filesystem::path createUniqueTempDirectory() {
    static std::atomic<unsigned long long> counter{0};
    const auto tick = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto root = std::filesystem::temp_directory_path();

    // create_directory is the cross-process claim: even if clocks have coarse
    // resolution and separate test processes choose the same candidate, only
    // one can create it. The others retry with a new counter value.
    for (unsigned attempt = 0; attempt < 128; ++attempt) {
        const auto candidate =
            root / ("bng3-gdat-format-" + std::to_string(tick) + "-" +
                   std::to_string(counter.fetch_add(1)));
        std::error_code ec;
        if (std::filesystem::create_directory(candidate, ec)) {
            return candidate;
        }
        if (ec && ec != std::errc::file_exists) {
            throw std::filesystem::filesystem_error(
                "create temporary directory for gdat output", candidate, ec);
        }
    }
    throw std::runtime_error("could not claim a unique gdat test directory");
}

struct TempDirectoryGuard {
    std::filesystem::path path;

    ~TempDirectoryGuard() {
        std::error_code ec;
        std::filesystem::remove_all(path, ec);
    }
};

// Drives the real writer over a fixed set of observable values and returns the
// emitted .gdat bytes. Going through OdeIntegrator keeps the test honest about
// the production formatting flags (scientific + precision 12, latched once per
// row) instead of asserting them separately.
std::string gdatRowsFor(const std::vector<double>& observableValues) {
    auto model = parser::parseModel(R"(
begin molecule types
    A()
end molecule types
begin seed species
    A() 1
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    A() -> A() 0.1
end reaction rules
)");

    engine::NetworkGenerator generator(*model);
    auto network = generator.generateNative();

    engine::OdeIntegrator integrator(*model, network);

    // One row per requested value: time in column 0, observable in column 1.
    engine::OdeResult result;
    result.timePoints = observableValues;
    result.observables.assign(observableValues.size(), std::vector<double>(1, 0.0));
    result.concentrations.assign(observableValues.size(), std::vector<double>(1, 0.0));
    for (std::size_t i = 0; i < observableValues.size(); ++i) {
        result.observables[i][0] = observableValues[i];
    }

    // The atomically created directory prevents collisions across both test
    // threads and separate ctest processes. The guard removes output on all
    // exits, including a failed writer or assertion.
    const TempDirectoryGuard tempDir{createUniqueTempDirectory()};
    const auto prefix = (tempDir.path / "output").string();
    integrator.writeOutputFiles(prefix, result, /*printCDAT=*/false,
                                /*printFunctions=*/false);

    std::string bytes = readAll(prefix + ".gdat");

    // Drop the "#<header>" line; keep only the data rows.
    const auto nl = bytes.find('\n');
    return nl == std::string::npos ? std::string{} : bytes.substr(nl + 1);
}

std::string expectedRows(const std::vector<double>& values) {
    std::string out;
    for (const double v : values) {
        out += field(v);      // time column
        out += ' ';
        out += field(v);      // observable column
        out += '\n';
    }
    return out;
}

} // namespace

TEST_CASE("gdat numeric fields keep the %.12e byte format", "[OdeOutput][format]") {
    // Values on formatting boundaries rather than in a benign middle range.
    const std::vector<double> values = {
        0.0,
        -0.0,
        1.0,
        -1.0,
        0.5,
        -0.5,
        0.1,
        150.0,
        1e-300,
        -1e-300,
        1e300,
        -1e300,
        3.14159265358979,
        // Smallest denormal and smallest normal: exponent field and leading
        // zeros are where a digit-count bug shows.
        std::numeric_limits<double>::denorm_min(),
        std::numeric_limits<double>::min(),
        std::numeric_limits<double>::max(),
        -std::numeric_limits<double>::max(),
        // Carries up to 1.000000000000e+23 at 12 fractional digits.
        9.999999999999999e22,
        // Half-way at the last printed digit.
        1.0000000000005e-5,
    };

    const std::string rows = gdatRowsFor(values);
    CHECK(rows == expectedRows(values));

    // Spell out a few literals so a failure names the byte that moved, and so
    // a future edit cannot quietly redefine the format on both sides at once.
    CHECK(rows.find("0.000000000000e+00 0.000000000000e+00\n") == 0u);
    CHECK(rows.find("-0.000000000000e+00 -0.000000000000e+00\n") != std::string::npos);
    CHECK(rows.find("4.940656458412e-324 4.940656458412e-324\n") != std::string::npos);
    CHECK(rows.find("1.797693134862e+308 1.797693134862e+308\n") != std::string::npos);
}

TEST_CASE("gdat rows pad to 18 columns and separate fields with one space",
          "[OdeOutput][format]") {
    const std::vector<double> values = {1.0, 22.0, 333.0};
    const std::string rows = gdatRowsFor(values);
    CHECK(rows == expectedRows(values));

    // A row is 18 (time) + 1 (space) + 18 (observable) + 1 (newline).
    std::size_t lineCount = 0;
    for (const char c : rows) {
        if (c == '\n') {
            ++lineCount;
        }
    }
    CHECK(lineCount == 3u);
    CHECK(rows.size() == 38u * 3u);
}
