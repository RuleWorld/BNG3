#include <catch2/catch_test_macros.hpp>

#include "ast/BarrierPattern.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"
#include "compile/SymbolTable.hpp"

using namespace bng;

TEST_CASE("duplicate barrier labels name their symbol kind") {
    ast::Model model;
    const auto transition = [](const std::string& name) {
        return ast::ReactionRule(name, "", {"A(s~U)"}, {"A(s~P)"},
                                 {ast::Expression::identifier("Gbar")}, {}, false,
                                 {}, {});
    };
    model.addBarrierPattern(ast::BarrierPattern("shared", transition("B1")));
    model.addBarrierPattern(ast::BarrierPattern("shared", transition("B2")));

    const auto symbols = compile::SymbolTable::fromModel(model);
    REQUIRE(symbols.diagnostics().size() == 1);
    CHECK(symbols.diagnostics().front().message ==
          "duplicate barrier pattern declaration: shared");
}
