#pragma once
#include <string>
namespace bng::compile { class CompiledModel; struct ResolvedExpression; }
namespace bng::io {
std::string resolvedExpressionToMathML(const compile::ResolvedExpression& expression,
                                       const compile::CompiledModel& model,
                                       const std::string& indent = {});
}
