#include "CompiledRule.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>
#include <unordered_set>

#include "SymbolTable.hpp"

namespace bng::compile {

namespace {

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return value;
}

ModifierKind translateModifier(const std::string& rawModifier) {
    const auto modifier = lower(rawModifier);
    if (modifier == "deletemolecules") return ModifierKind::DeleteMolecules;
    if (modifier == "moveconnected") return ModifierKind::MoveConnected;
    if (modifier == "matchonce") return ModifierKind::MatchOnce;
    if (modifier == "totalrate") return ModifierKind::TotalRate;
    if (modifier.rfind("include_reactants(", 0) == 0) return ModifierKind::IncludeReactants;
    if (modifier.rfind("exclude_reactants(", 0) == 0) return ModifierKind::ExcludeReactants;
    if (modifier.rfind("include_products(", 0) == 0) return ModifierKind::IncludeProducts;
    if (modifier.rfind("exclude_products(", 0) == 0) return ModifierKind::ExcludeProducts;
    return ModifierKind::Unknown;
}

std::string trim(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

std::vector<std::string> splitTopLevel(const std::string& text) {
    std::vector<std::string> parts;
    std::size_t start = 0;
    int parentheses = 0;
    int brackets = 0;
    int braces = 0;
    char quote = '\0';
    bool escaped = false;
    for (std::size_t index = 0; index < text.size(); ++index) {
        const char character = text[index];
        if (quote != '\0') {
            if (escaped) {
                escaped = false;
            } else if (character == '\\') {
                escaped = true;
            } else if (character == quote) {
                quote = '\0';
            }
            continue;
        }
        if (character == '\'' || character == '"') {
            quote = character;
        } else if (character == '(') {
            ++parentheses;
        } else if (character == ')') {
            --parentheses;
        } else if (character == '[') {
            ++brackets;
        } else if (character == ']') {
            --brackets;
        } else if (character == '{') {
            ++braces;
        } else if (character == '}') {
            --braces;
        } else if (character == ',' && parentheses == 0 && brackets == 0 && braces == 0) {
            parts.push_back(trim(text.substr(start, index - start)));
            start = index + 1;
        }
    }
    parts.push_back(trim(text.substr(start)));
    return parts;
}

void addFilterDiagnostic(std::vector<Diagnostic>* diagnostics,
                         const std::string& ruleName,
                         const std::string& message) {
    if (diagnostics == nullptr) return;
    Diagnostic diagnostic;
    diagnostic.code = DiagnosticCode::InvalidModel;
    diagnostic.severity = Severity::Error;
    diagnostic.category = ValidationCategory::Rules;
    diagnostic.entity = ruleName;
    diagnostic.message = message;
    diagnostics->push_back(std::move(diagnostic));
}

void parseFilter(const std::string& modifier,
                 const std::string& ruleName,
                 std::vector<CompiledFilter>& filters,
                 std::vector<Diagnostic>* diagnostics) {
    const auto open = modifier.find('(');
    const auto close = modifier.rfind(')');
    if (open == std::string::npos) return;

    if (close <= open || close != modifier.size() - 1) {
        addFilterDiagnostic(diagnostics, ruleName,
                             "malformed reaction filter modifier '" + modifier + "'");
        return;
    }

    const auto name = lower(trim(modifier.substr(0, open)));
    const bool known = name == "include_reactants" || name == "exclude_reactants" ||
                       name == "include_products" || name == "exclude_products";
    if (!known) return;

    const auto parts = splitTopLevel(modifier.substr(open + 1, close - open - 1));
    if (parts.size() < 2 || parts.front().empty()) {
        addFilterDiagnostic(diagnostics, ruleName,
                             "reaction filter modifier needs a pattern index and pattern: '" +
                                 modifier + "'");
        return;
    }

    std::size_t consumed = 0;
    std::size_t patternIndex = 0;
    try {
        const auto rawIndex = std::stoul(parts.front(), &consumed);
        if (consumed != parts.front().size() || rawIndex == 0) throw std::invalid_argument("index");
        patternIndex = rawIndex - 1;
    } catch (const std::exception&) {
        addFilterDiagnostic(diagnostics, ruleName,
                             "reaction filter index must be a positive integer: '" +
                                 modifier + "'");
        return;
    }

    CompiledFilter filter;
    filter.include = name.rfind("include_", 0) == 0;
    filter.products = name.rfind("include_products", 0) == 0 ||
                      name.rfind("exclude_products", 0) == 0;
    filter.patternIndex = patternIndex;
    for (std::size_t index = 1; index < parts.size(); ++index) {
        if (parts[index].empty()) {
            addFilterDiagnostic(diagnostics, ruleName,
                                 "reaction filter contains an empty pattern: '" + modifier + "'");
            return;
        }
        try {
            filter.sourcePatterns.push_back(parts[index]);
            filter.patterns.push_back(Pattern::parse(parts[index]));
        } catch (const std::invalid_argument& error) {
            addFilterDiagnostic(diagnostics, ruleName,
                                 "invalid reaction filter pattern '" + parts[index] + "': " +
                                     error.what());
            return;
        }
    }
    filters.push_back(std::move(filter));
}

void parseFilters(const ast::ReactionRule& rule,
                  std::vector<CompiledFilter>& filters,
                  std::vector<Diagnostic>* diagnostics) {
    filters.clear();
    for (const auto& modifier : rule.getModifiers()) {
        parseFilter(modifier, rule.getRuleName(), filters, diagnostics);
    }
}

MutationKind translateMutationKind(ast::ReactionRule::TransformOp::Type type) {
    using Type = ast::ReactionRule::TransformOp::Type;
    switch (type) {
    case Type::AddBond:
        return MutationKind::AddBond;
    case Type::DeleteBond:
        return MutationKind::DeleteBond;
    case Type::ChangeState:
        return MutationKind::ChangeState;
    case Type::AddMolecule:
        return MutationKind::AddMolecule;
    case Type::DeleteMolecule:
        return MutationKind::DeleteMolecule;
    }
    throw std::invalid_argument("unknown AST mutation kind");
}

void addAffectedComponent(
    std::vector<ast::ReactionRule::ComponentRef>& refs,
    const ast::ReactionRule::ComponentRef& ref) {
    if (std::find(refs.begin(), refs.end(), ref) == refs.end()) refs.push_back(ref);
}

std::vector<std::string> collectLocalScopeNames(
    const ast::ReactionRule& rule) {
    std::unordered_set<std::string> names;
    for (const auto& reactant : rule.getReactants()) {
        std::size_t cursor = 0;
        while ((cursor = reactant.find('%', cursor)) != std::string::npos) {
            const auto scopeEnd = reactant.find("::", cursor + 1);
            if (scopeEnd != std::string::npos) {
                const auto name = reactant.substr(cursor + 1, scopeEnd - cursor - 1);
                if (!name.empty() && std::all_of(
                        name.begin(), name.end(), [](unsigned char character) {
                            return std::isalnum(character) || character == '_';
                        })) {
                    names.insert(name);
                }
            }
            cursor += 1;
        }
    }
    return {names.begin(), names.end()};
}

} // namespace

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule) {
    CompiledRule compiled;
    compiled.name_ = rule.getRuleName();
    compiled.label_ = rule.getLabel();
    // Empty operations include implicit whole-species deletion in the AST.
    // Never interpret absent edit metadata as proof of no dependencies.
    compiled.conservativeInvalidation_ = rule.getOperations().empty();
    compiled.bidirectional_ = rule.isBidirectional();

    compiled.modifiers_.reserve(rule.getModifiers().size());
    for (const auto& modifier : rule.getModifiers()) {
        compiled.modifiers_.push_back(CompiledModifier{translateModifier(modifier), modifier});
    }
    parseFilters(rule, compiled.filters_, nullptr);

    compiled.reactantPatterns_.reserve(rule.getReactantPatterns().size());
    for (const auto& pattern : rule.getReactantPatterns()) {
        compiled.reactantPatterns_.push_back(Pattern::fromSpeciesGraph(pattern));
    }
    compiled.productPatterns_.reserve(rule.getProductPatterns().size());
    for (const auto& pattern : rule.getProductPatterns()) {
        compiled.productPatterns_.push_back(Pattern::fromSpeciesGraph(pattern));
    }

    compiled.rateLaws_.reserve(rule.getRates().size());
    for (const auto& rate : rule.getRates())
        compiled.rateLaws_.push_back(CompiledRateLaw::compile(rate));

    compiled.mutations_.reserve(rule.getOperations().size());
    for (const auto& operation : rule.getOperations()) {
        MutationSignature mutation;
        mutation.kind = translateMutationKind(operation.type);
        mutation.source = operation.source;
        mutation.partner = operation.partner;
        mutation.moleculeIndex = operation.moleculeIndex;
        mutation.patternIndex = operation.patternIndex;
        mutation.newState = operation.newState;
        compiled.mutations_.push_back(std::move(mutation));

        using Type = ast::ReactionRule::TransformOp::Type;
        switch (operation.type) {
        case Type::AddBond:
        case Type::DeleteBond:
            addAffectedComponent(compiled.affectedComponents_, operation.source);
            addAffectedComponent(compiled.affectedComponents_, operation.partner);
            break;
        case Type::ChangeState:
            addAffectedComponent(compiled.affectedComponents_, operation.source);
            break;
        case Type::AddMolecule:
        case Type::DeleteMolecule:
            compiled.conservativeInvalidation_ = true;
            // Molecule creation/deletion may alter arbitrary local pattern
            // membership. The molecule/pattern indices are retained in the
            // mutation signature; there is no sound component-only shortcut.
            break;
        }
    }

    std::sort(compiled.affectedComponents_.begin(), compiled.affectedComponents_.end());
    return compiled;
}

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule,
                                   const SymbolTable& symbols,
                                   std::vector<Diagnostic>* diagnostics) {
    auto compiled = compile(rule);
    parseFilters(rule, compiled.filters_, diagnostics);
    compiled.rateLaws_.clear();
    compiled.rateLaws_.reserve(rule.getRates().size());
    const auto localScopeNames = collectLocalScopeNames(rule);
    for (const auto& rate : rule.getRates()) {
        auto compiledRate = CompiledRateLaw::compile(rate, symbols, localScopeNames);
        if (diagnostics != nullptr) {
            diagnostics->insert(diagnostics->end(),
                                compiledRate.diagnostics().begin(),
                                compiledRate.diagnostics().end());
        }
        compiled.rateLaws_.push_back(std::move(compiledRate));
    }
    return compiled;
}

} // namespace bng::compile
