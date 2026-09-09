#pragma once
#include "executable_model.hh"
#include <iosfwd>
#include <string>
namespace NFcore2 {
class ModelImage {
public:
    // Version 13 adds graph negation/molecularity and native TFUN metadata.
    static const std::uint32_t FORMAT_VERSION = 13;
    static void write(const ExecutableModel& model, std::ostream& out);
    static ExecutableModel read(std::istream& in);
    static void writeFile(const ExecutableModel& model, const std::string& path);
    static ExecutableModel readFile(const std::string& path);
};
}
