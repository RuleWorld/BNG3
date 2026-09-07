#pragma once
#include "executable_model.hh"
#include <iosfwd>
#include <string>
namespace NFcore2 {
class ModelImage {
public:
    // Version 2 persists the reciprocal-component bit on MATCH_BOND_TO.
    static const std::uint32_t FORMAT_VERSION = 2;
    static void write(const ExecutableModel& model, std::ostream& out);
    static ExecutableModel read(std::istream& in);
    static void writeFile(const ExecutableModel& model, const std::string& path);
    static ExecutableModel readFile(const std::string& path);
};
}
