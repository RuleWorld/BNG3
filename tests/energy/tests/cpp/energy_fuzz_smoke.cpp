// Deterministic sanitizer driver; this does not claim coverage-guided fuzzing.
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t*, std::size_t);

int main() {
    std::mt19937_64 random(0xB1A3E5);
    for (std::size_t trial = 0; trial < 10000; ++trial) {
        std::vector<std::uint8_t> bytes(trial % 129);
        for (auto& byte : bytes) byte = static_cast<std::uint8_t>(random());
        if (LLVMFuzzerTestOneInput(bytes.data(), bytes.size()) != 0) return 1;
    }
    std::cout << "10000 deterministic energy fuzz inputs passed\n";
}
