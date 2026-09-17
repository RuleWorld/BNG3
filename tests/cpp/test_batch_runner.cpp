#include <catch2/catch_test_macros.hpp>

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#if defined(_WIN32) || defined(__WIN32__) || defined(__CYGWIN__)
#include <process.h>
#else
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace {

namespace fs = std::filesystem;

struct TemporaryRoot {
    fs::path path;
    explicit TemporaryRoot() {
        const auto stamp = std::chrono::high_resolution_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() / ("bng3-batch-test-" + std::to_string(stamp));
        fs::create_directories(path);
    }
    ~TemporaryRoot() { std::error_code error; fs::remove_all(path, error); }
};

std::string shellQuote(const std::string& value) {
    std::string quoted = "'";
    for (const char character : value) {
        if (character == '\'') quoted += "'\\''";
        else quoted += character;
    }
    quoted += "'";
    return quoted;
}

int runCommand(const fs::path& executable, const std::vector<std::string>& arguments) {
#if defined(_WIN32) || defined(__WIN32__) || defined(__CYGWIN__)
    std::vector<std::string> storage;
    storage.reserve(arguments.size() + 1);
    storage.push_back(executable.string());
    storage.insert(storage.end(), arguments.begin(), arguments.end());
    std::vector<char*> nativeArguments;
    nativeArguments.reserve(storage.size() + 1);
    for (auto& argument : storage) nativeArguments.push_back(argument.data());
    nativeArguments.push_back(nullptr);
    return static_cast<int>(_spawnv(_P_WAIT, storage.front().c_str(), nativeArguments.data()));
#else
    std::string command = shellQuote(executable.string());
    for (const auto& argument : arguments) command += " " + shellQuote(argument);
    return std::system(command.c_str());
#endif
}

void writeModel(const fs::path& path, bool valid) {
    std::ofstream output(path);
    REQUIRE(output.good());
    if (!valid) {
        output << "this is not a BioNetGen model\n";
        return;
    }
    output << "begin model\n"
           << "begin parameters\n"
           << "k 1\n"
           << "end parameters\n"
           << "begin molecule types\n"
           << "A()\n"
           << "B()\n"
           << "end molecule types\n"
           << "begin seed species\n"
           << "A() 1\n"
           << "end seed species\n"
           << "begin reaction rules\n"
           << "A() -> B() k\n"
           << "end reaction rules\n"
           << "end model\n"
           << "generate_network({overwrite=>1})\n";
}

} // namespace

TEST_CASE("bng_cpp parallel mode isolates model outputs", "[batch]") {
    TemporaryRoot root;
    const auto modelOne = root.path / "one.bngl";
    const auto modelTwo = root.path / "two.bngl";
    const auto outputRoot = root.path / "outputs";
    writeModel(modelOne, true);
    writeModel(modelTwo, true);

    const std::vector<std::string> arguments = {
        "--parallel", "2", "--parallel-dir", outputRoot.string(), modelOne.string(), modelTwo.string()};

    REQUIRE(runCommand(fs::path(BNG_CPP_PATH), arguments) == 0);
    REQUIRE(fs::exists(outputRoot / "job_000-one" / "one.bngl"));
    REQUIRE(fs::exists(outputRoot / "job_001-two" / "two.bngl"));
    REQUIRE(fs::exists(outputRoot / "job_000-one" / "one.net"));
    REQUIRE(fs::exists(outputRoot / "job_001-two" / "two.net"));
}

TEST_CASE("bng_cpp parallel mode propagates child failures", "[batch]") {
    TemporaryRoot root;
    const auto validModel = root.path / "valid.bngl";
    const auto invalidModel = root.path / "invalid.bngl";
    const auto outputRoot = root.path / "outputs";
    writeModel(validModel, true);
    writeModel(invalidModel, false);

    const std::vector<std::string> arguments = {
        "--parallel", "2", "--parallel-dir", outputRoot.string(), validModel.string(), invalidModel.string()};

    REQUIRE(runCommand(fs::path(BNG_CPP_PATH), arguments) != 0);
    REQUIRE(fs::exists(outputRoot / "job_000-valid" / "valid.net"));
    REQUIRE(fs::exists(outputRoot / "job_001-invalid" / "invalid.bngl"));
}
