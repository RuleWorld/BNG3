#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fstream>
#include <iterator>
#include <memory>
#include <string>

#include "parser/BNGAstVisitor.hpp"
#include "ast/Model.hpp"

namespace py = pybind11;

namespace {

struct ParseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Both bindings route through the single parser pipeline in parseModelSource
// rather than driving BNGAstVisitor here. A second copy of this sequence is
// what let `driven_by()` and `begin barrier patterns` parse cleanly on the
// Python path and then vanish: the post-visit lowering step was present in one
// copy and absent from the other. Syntax errors keep their own exception type
// so `except _cpp.ParseError` still catches them.
std::unique_ptr<bng::ast::Model> do_parse(const std::string& source,
                                           const std::string& source_name) {
    try {
        return bng::parser::parseModelSource(source, source_name);
    } catch (const bng::parser::BNGSyntaxError& error) {
        throw ParseError(error.what());
    }
}

} // namespace

void bind_parser(py::module_& m) {
    py::register_exception<ParseError>(m, "ParseError");

    m.def("parse_file", [](const std::string& path) {
        py::gil_scoped_release release;
        std::ifstream inputStream(path);
        if (!inputStream) {
            throw ParseError("Cannot open file: " + path);
        }
        const std::string source((std::istreambuf_iterator<char>(inputStream)),
                                 std::istreambuf_iterator<char>());
        return do_parse(source, path);
    }, py::arg("path"),
       "Parse a BNGL file and return a Model object");

    m.def("parse_string", [](const std::string& text) {
        py::gil_scoped_release release;
        return do_parse(text, "<string>");
    }, py::arg("text"),
       "Parse a BNGL string and return a Model object");
}
