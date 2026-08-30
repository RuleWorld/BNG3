#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <fstream>
#include <iterator>
#include <memory>
#include <sstream>
#include <string>

#include <antlr4-runtime.h>
#include "BNGLexer.h"
#include "BNGParser.h"
#include "parser/BNGAstVisitor.hpp"
#include "ast/Model.hpp"

namespace py = pybind11;

namespace {

struct ParseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

std::unique_ptr<bng::ast::Model> do_parse(antlr4::ANTLRInputStream& input, const std::string& source_name) {
    BNGLexer lexer(&input);
    antlr4::CommonTokenStream tokens(&lexer);
    BNGParser parser(&tokens);
    auto* tree = parser.prog();

    if (parser.getNumberOfSyntaxErrors() != 0) {
        throw ParseError("BNGL syntax errors in " + source_name + ": " +
                         std::to_string(parser.getNumberOfSyntaxErrors()) + " error(s)");
    }

    bng::parser::BNGAstVisitor visitor;
    visitor.visit(tree);
    auto model = visitor.takeModel();

    if (!model) {
        throw ParseError("Failed to build model AST from " + source_name);
    }

    return model;
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
        antlr4::ANTLRInputStream input(bng::parser::normalizeBNGLSource(source));
        return do_parse(input, path);
    }, py::arg("path"),
       "Parse a BNGL file and return a Model object");

    m.def("parse_string", [](const std::string& text) {
        py::gil_scoped_release release;
        antlr4::ANTLRInputStream input(bng::parser::normalizeBNGLSource(text));
        return do_parse(input, "<string>");
    }, py::arg("text"),
       "Parse a BNGL string and return a Model object");
}
