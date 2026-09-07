#include "CompiledRateLaw.hpp"

#include <algorithm>
#include <cctype>

namespace bng::compile {

namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

RateLawKind classifyFunction(const std::string& rawName) {
    const auto name = lower(rawName);
    if (name == "arrhenius") return RateLawKind::ArrheniusEnergy;
    if (name == "sat") return RateLawKind::Saturation;
    if (name == "mm") return RateLawKind::MichaelisMenten;
    if (name == "hill") return RateLawKind::Hill;
    if (name == "functionproduct") return RateLawKind::FunctionProduct;
    if (name == "hybrid") return RateLawKind::Hybrid;
    return RateLawKind::Expression;
}

} // namespace

CompiledRateLaw CompiledRateLaw::compile(const ast::Expression& expression) {
    CompiledRateLaw compiled;
    compiled.sourceExpression = expression.toString();
    if (expression.kind() == ast::ExpressionKind::Function ||
        expression.kind() == ast::ExpressionKind::ObservableRef) {
        compiled.kind = classifyFunction(expression.name());
        compiled.arguments = expression.args();
    }
    return compiled;
}

} // namespace bng::compile
