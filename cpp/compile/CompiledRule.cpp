#include "CompiledRule.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "SymbolTable.hpp"
#include "ast/Model.hpp"
#include "ast/ReactionRule.hpp"

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

void addRuleDiagnostic(std::vector<Diagnostic>* diagnostics,
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
        addRuleDiagnostic(diagnostics, ruleName,
                          "malformed reaction filter modifier '" + modifier + "'");
        return;
    }

    const auto name = lower(trim(modifier.substr(0, open)));
    const bool known = name == "include_reactants" || name == "exclude_reactants" ||
                       name == "include_products" || name == "exclude_products";
    if (!known) return;

    const auto parts = splitTopLevel(modifier.substr(open + 1, close - open - 1));
    if (parts.size() < 2 || parts.front().empty()) {
        addRuleDiagnostic(diagnostics, ruleName,
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
        addRuleDiagnostic(diagnostics, ruleName,
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
            addRuleDiagnostic(diagnostics, ruleName,
                              "reaction filter contains an empty pattern: '" + modifier + "'");
            return;
        }
        try {
            filter.sourcePatterns.push_back(parts[index]);
            filter.patterns.push_back(Pattern::parse(parts[index]));
        } catch (const std::invalid_argument& error) {
            addRuleDiagnostic(diagnostics, ruleName,
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
    case Type::AddBond: return MutationKind::AddBond;
    case Type::DeleteBond: return MutationKind::DeleteBond;
    case Type::ChangeState: return MutationKind::ChangeState;
    case Type::AddMolecule: return MutationKind::AddMolecule;
    case Type::DeleteMolecule: return MutationKind::DeleteMolecule;
    }
    throw std::invalid_argument("unknown AST mutation kind");
}

PatternSiteRef siteRef(const ast::ReactionRule::ComponentRef& ref, PatternSide side) {
    return PatternSiteRef{side, ref.patternIndex, ref.moleculeIndex, ref.componentIndex};
}

PatternMoleculeRef moleculeRef(const ast::ReactionRule::ComponentRef& ref, PatternSide side) {
    return PatternMoleculeRef{side, ref.patternIndex, ref.moleculeIndex};
}

void addAffectedComponent(std::vector<PatternSiteRef>& refs, const PatternSiteRef& ref) {
    if (std::find(refs.begin(), refs.end(), ref) == refs.end()) refs.push_back(ref);
}

std::vector<CompiledLocalScope> collectLocalScopes(const ast::ReactionRule& rule,
                                                       std::vector<Diagnostic>* diagnostics) {
    std::vector<CompiledLocalScope> scopes;
    const auto& reactants = rule.getReactants();
    for (std::size_t patternIndex = 0; patternIndex < reactants.size(); ++patternIndex) {
        const auto& pattern = reactants[patternIndex];
        std::size_t moleculeIndex = 0;
        int depth = 0;
        for (std::size_t cursor = 0; cursor < pattern.size(); ++cursor) {
            const char ch = pattern[cursor];
            if (ch == '(') { ++depth; continue; }
            if (ch == ')') { --depth; continue; }
            if (ch == '.' && depth == 0) { ++moleculeIndex; continue; }
            if (ch != '%') continue;

            const std::size_t begin = cursor + 1;
            if (begin >= pattern.size() ||
                !(std::isalpha(static_cast<unsigned char>(pattern[begin])) ||
                  pattern[begin] == '_')) {
                // Numeric %1/%2 labels are mapping tags, not local-function scopes.
                continue;
            }
            std::size_t end = begin + 1;
            while (end < pattern.size() &&
                   (std::isalnum(static_cast<unsigned char>(pattern[end])) ||
                    pattern[end] == '_')) ++end;
            const std::string name = pattern.substr(begin, end - begin);
            const bool speciesScope = pattern.compare(end, 2, "::") == 0;
            // Named component labels live inside a molecule's component list;
            // local function variables are molecule tags or %x:: species anchors.
            if (!speciesScope && depth != 0) {
                cursor = end - 1;
                continue;
            }
            CompiledLocalScope candidate;
            candidate.name = name;
            candidate.reactantPatternIndex = patternIndex;
            candidate.kind = speciesScope ? LocalScopeKind::Species : LocalScopeKind::Molecule;
            if (!speciesScope) candidate.moleculeOccurrence = moleculeIndex;

            const auto found = std::find_if(scopes.begin(), scopes.end(),
                [&](const auto& scope) { return scope.name == name; });
            if (found == scopes.end()) {
                scopes.push_back(std::move(candidate));
            } else if (found->reactantPatternIndex != candidate.reactantPatternIndex ||
                       found->kind != candidate.kind ||
                       found->moleculeOccurrence != candidate.moleculeOccurrence) {
                addRuleDiagnostic(diagnostics, rule.getRuleName(),
                    "local scope identifier '" + name +
                    "' is ambiguous across reactant patterns/molecules");
            }
            cursor = end - 1;
        }
    }
    return scopes;
}

std::vector<std::string> localScopeNames(const std::vector<CompiledLocalScope>& scopes) {
    std::vector<std::string> names;
    names.reserve(scopes.size());
    for (const auto& scope : scopes) names.push_back(scope.name);
    return names;
}

std::optional<StateId> resolveStateId(const PatternSiteDescriptor& site,
                                      const std::string& state,
                                      const ast::Model* model) {
    if (model == nullptr || !site.componentType.has_value() || state.empty()) return std::nullopt;
    const auto componentId = *site.componentType;
    if (!componentId.moleculeType.valid() ||
        componentId.moleculeType.value() >= model->getMoleculeTypes().size()) return std::nullopt;
    const auto& molecule = model->getMoleculeTypes()[componentId.moleculeType.value()];
    if (componentId.index >= molecule.getComponents().size()) return std::nullopt;
    const auto& states = molecule.getComponents()[componentId.index].allowedStates;
    const auto found = std::find(states.begin(), states.end(), state);
    if (found == states.end()) return std::nullopt;
    return StateId{componentId,
                   static_cast<std::size_t>(std::distance(states.begin(), found))};
}

const PatternSiteDescriptor* referencedSite(const std::vector<Pattern>& patterns,
                                            const PatternSiteRef& ref) {
    if (ref.patternIndex >= patterns.size()) return nullptr;
    const auto& molecules = patterns[ref.patternIndex].molecules();
    if (ref.moleculeIndex >= molecules.size()) return nullptr;
    if (ref.siteIndex >= molecules[ref.moleculeIndex].sites.size()) return nullptr;
    return &molecules[ref.moleculeIndex].sites[ref.siteIndex];
}

std::string sourceState(const std::vector<Pattern>& patterns, const PatternSiteRef& ref) {
    if (const auto* site = referencedSite(patterns, ref)) return site->stateConstraint;
    return {};
}

std::vector<CompiledFilter> reversedFilters(const std::vector<CompiledFilter>& filters) {
    auto result = filters;
    for (auto& filter : result) filter.products = !filter.products;
    return result;
}

} // namespace

namespace detail {

class RuleCompiler {
public:
    static CompiledRule run(const ast::ReactionRule& rule,
                            const ast::Model* model,
                            const SymbolTable* symbols,
                            std::vector<Diagnostic>* diagnostics) {
        CompiledRule compiled;
        compiled.name_ = rule.getRuleName();
        compiled.label_ = rule.getLabel();
        compiled.conservativeInvalidation_ = rule.getOperations().empty();
        compiled.bidirectional_ = rule.isBidirectional();

        compiled.modifiers_.reserve(rule.getModifiers().size());
        for (const auto& modifier : rule.getModifiers()) {
            compiled.modifiers_.push_back(
                CompiledModifier{translateModifier(modifier), modifier});
        }

        parseFilters(rule, compiled.forward_.filters, diagnostics);
        if (model != nullptr && symbols != nullptr) {
            for (auto& filter : compiled.forward_.filters) {
                for (auto& pattern : filter.patterns) {
                    pattern.resolve(*model, *symbols, diagnostics);
                }
            }
        }

        compiled.forward_.reactantPatterns.reserve(rule.getReactantPatterns().size());
        for (const auto& pattern : rule.getReactantPatterns()) {
            if (model != nullptr && symbols != nullptr) {
                compiled.forward_.reactantPatterns.push_back(
                    Pattern::fromSpeciesGraph(pattern, *model, *symbols, diagnostics));
            } else {
                compiled.forward_.reactantPatterns.push_back(Pattern::fromSpeciesGraph(pattern));
            }
        }
        compiled.forward_.productPatterns.reserve(rule.getProductPatterns().size());
        for (const auto& pattern : rule.getProductPatterns()) {
            if (model != nullptr && symbols != nullptr) {
                compiled.forward_.productPatterns.push_back(
                    Pattern::fromSpeciesGraph(pattern, *model, *symbols, diagnostics));
            } else {
                compiled.forward_.productPatterns.push_back(Pattern::fromSpeciesGraph(pattern));
            }
        }

        compiled.forward_.localScopes = collectLocalScopes(rule, diagnostics);
        const auto rateLocalScopeNames = localScopeNames(compiled.forward_.localScopes);
        compiled.rateLaws_.reserve(rule.getRates().size());
        for (const auto& rate : rule.getRates()) {
            CompiledRateLaw compiledRate = symbols == nullptr
                ? CompiledRateLaw::compile(rate)
                : CompiledRateLaw::compile(rate, *symbols, rateLocalScopeNames);
            if (diagnostics != nullptr) {
                diagnostics->insert(diagnostics->end(),
                                    compiledRate.diagnostics().begin(),
                                    compiledRate.diagnostics().end());
            }
            compiled.rateLaws_.push_back(std::move(compiledRate));
        }
        if (!compiled.rateLaws_.empty()) compiled.forward_.rateLaw = compiled.rateLaws_.front();

        // Preserve resolved product->reactant identity maps. These mappings are
        // part of rule semantics and should not be rediscovered by each backend.
        for (const auto& [product, reactant] : rule.getMoleculeMappings()) {
            compiled.moleculeMappings_.push_back({
                moleculeRef(product, PatternSide::Product),
                moleculeRef(reactant, PatternSide::Reactant)});
        }
        for (const auto& [product, reactant] : rule.getComponentMappings()) {
            compiled.componentMappings_.push_back({
                siteRef(product, PatternSide::Product),
                siteRef(reactant, PatternSide::Reactant)});
        }

        compiled.forward_.mutations.reserve(rule.getOperations().size());
        for (const auto& operation : rule.getOperations()) {
            MutationSignature mutation;
            mutation.kind = translateMutationKind(operation.type);
            mutation.source = siteRef(operation.source, PatternSide::Reactant);
            mutation.partner = siteRef(operation.partner, PatternSide::Reactant);
            mutation.molecule = PatternMoleculeRef{
                operation.type == ast::ReactionRule::TransformOp::Type::AddMolecule
                    ? PatternSide::Product : PatternSide::Reactant,
                operation.patternIndex,
                operation.moleculeIndex};
            mutation.newState = operation.newState;
            if (mutation.kind == MutationKind::ChangeState) {
                if (const auto* site = referencedSite(compiled.forward_.reactantPatterns,
                                                      mutation.source)) {
                    mutation.newStateId = resolveStateId(*site, mutation.newState, model);
                }
            }
            compiled.forward_.mutations.push_back(std::move(mutation));

            using Type = ast::ReactionRule::TransformOp::Type;
            switch (operation.type) {
            case Type::AddBond:
            case Type::DeleteBond:
                addAffectedComponent(compiled.affectedComponents_,
                                     siteRef(operation.source, PatternSide::Reactant));
                addAffectedComponent(compiled.affectedComponents_,
                                     siteRef(operation.partner, PatternSide::Reactant));
                break;
            case Type::ChangeState:
                addAffectedComponent(compiled.affectedComponents_,
                                     siteRef(operation.source, PatternSide::Reactant));
                break;
            case Type::AddMolecule:
            case Type::DeleteMolecule:
                compiled.conservativeInvalidation_ = true;
                break;
            }
        }
        compiled.forward_.transformationsComplete = true;
        // The legacy execution engine has a small class of product-only edits
        // that are not exposed through ReactionRule::getOperations(): setting a
        // state when the reactant site was unconstrained, or forcing an
        // otherwise-unconstrained site free. Detect those cases here so strict
        // compiled backends never assume the mutation program is complete.
        for (const auto& [productRefRaw, reactantRefRaw] : compiled.componentMappings_) {
            const PatternSiteRef productRef{PatternSide::Product,
                                            productRefRaw.patternIndex,
                                            productRefRaw.moleculeIndex,
                                            productRefRaw.siteIndex};
            const PatternSiteRef reactantRef{PatternSide::Reactant,
                                             reactantRefRaw.patternIndex,
                                             reactantRefRaw.moleculeIndex,
                                             reactantRefRaw.siteIndex};
            const auto* productSite = referencedSite(compiled.forward_.productPatterns,
                                                     productRef);
            const auto* reactantSite = referencedSite(compiled.forward_.reactantPatterns,
                                                      reactantRef);
            if (productSite == nullptr || reactantSite == nullptr) {
                compiled.forward_.transformationsComplete = false;
                continue;
            }

            const bool hasStateMutation = std::any_of(
                compiled.forward_.mutations.begin(), compiled.forward_.mutations.end(),
                [&](const auto& mutation) {
                    return mutation.kind == MutationKind::ChangeState &&
                           mutation.source == reactantRef;
                });
            if (productSite->stateConstraintResolved.kind == StateConstraintKind::Exact) {
                const bool sameExactState =
                    reactantSite->stateConstraintResolved.kind == StateConstraintKind::Exact &&
                    reactantSite->stateConstraintResolved.exact ==
                        productSite->stateConstraintResolved.exact;
                if (!sameExactState && !hasStateMutation)
                    compiled.forward_.transformationsComplete = false;
            }

            const bool productForcesFree = [&]() {
                if (!productSite->bondConstraints.empty()) {
                    return std::any_of(productSite->bondConstraints.begin(),
                                       productSite->bondConstraints.end(),
                                       [](const auto& bond) {
                                           return bond.kind == BondConstraintKind::Unbound;
                                       });
                }
                return productSite->bondKind == BondConstraintKind::Unbound;
            }();
            const bool reactantAlreadyFree = [&]() {
                if (!reactantSite->bondConstraints.empty()) {
                    return std::any_of(reactantSite->bondConstraints.begin(),
                                       reactantSite->bondConstraints.end(),
                                       [](const auto& bond) {
                                           return bond.kind == BondConstraintKind::Unbound;
                                       });
                }
                return reactantSite->bondKind == BondConstraintKind::Unbound;
            }();
            const bool hasDeleteBondMutation = std::any_of(
                compiled.forward_.mutations.begin(), compiled.forward_.mutations.end(),
                [&](const auto& mutation) {
                    return mutation.kind == MutationKind::DeleteBond &&
                           (mutation.source == reactantRef || mutation.partner == reactantRef);
                });
            if (productForcesFree && !reactantAlreadyFree && !hasDeleteBondMutation)
                compiled.forward_.transformationsComplete = false;
        }
        std::sort(compiled.affectedComponents_.begin(), compiled.affectedComponents_.end());

        if (compiled.bidirectional_) {
            CompiledRuleDirection reverse;
            reverse.reactantPatterns = compiled.forward_.productPatterns;
            reverse.productPatterns = compiled.forward_.reactantPatterns;
            reverse.filters = reversedFilters(compiled.forward_.filters);
            // Local scope identifiers are meaningful only when present on the
            // active reactant side. Product-side scope prefixes are uncommon and
            // are not inferred from forward bindings. A reverse local-rate
            // direction therefore fails closed unless no local references occur.
            reverse.localScopes.clear();
            if (compiled.rateLaws_.size() >= 2) reverse.rateLaw = compiled.rateLaws_[1];
            reverse.transformationsComplete = true;

            auto productSiteForReactant = [&](const PatternSiteRef& reactantRef)
                -> std::optional<PatternSiteRef> {
                for (const auto& [product, reactant] : compiled.componentMappings_) {
                    if (reactant.patternIndex == reactantRef.patternIndex &&
                        reactant.moleculeIndex == reactantRef.moleculeIndex &&
                        reactant.siteIndex == reactantRef.siteIndex) {
                        return PatternSiteRef{PatternSide::Reactant,
                                              product.patternIndex,
                                              product.moleculeIndex,
                                              product.siteIndex};
                    }
                }
                return std::nullopt;
            };

            for (const auto& forwardMutation : compiled.forward_.mutations) {
                MutationSignature inverse;
                switch (forwardMutation.kind) {
                case MutationKind::AddBond:
                case MutationKind::DeleteBond: {
                    const auto source = productSiteForReactant(forwardMutation.source);
                    const auto partner = productSiteForReactant(forwardMutation.partner);
                    if (!source.has_value() || !partner.has_value()) {
                        reverse.transformationsComplete = false;
                        continue;
                    }
                    inverse.kind = forwardMutation.kind == MutationKind::AddBond
                        ? MutationKind::DeleteBond : MutationKind::AddBond;
                    inverse.source = *source;
                    inverse.partner = *partner;
                    break;
                }
                case MutationKind::ChangeState: {
                    const auto source = productSiteForReactant(forwardMutation.source);
                    if (!source.has_value()) {
                        reverse.transformationsComplete = false;
                        continue;
                    }
                    inverse.kind = MutationKind::ChangeState;
                    inverse.source = *source;
                    inverse.newState = sourceState(compiled.forward_.reactantPatterns,
                                                   forwardMutation.source);
                    if (const auto* site = referencedSite(reverse.reactantPatterns,
                                                          inverse.source)) {
                        inverse.newStateId = resolveStateId(*site, inverse.newState, model);
                    }
                    if (inverse.newState.empty()) reverse.transformationsComplete = false;
                    break;
                }
                case MutationKind::AddMolecule:
                    inverse.kind = MutationKind::DeleteMolecule;
                    inverse.molecule = PatternMoleculeRef{
                        PatternSide::Reactant,
                        forwardMutation.molecule.patternIndex,
                        forwardMutation.molecule.moleculeIndex};
                    break;
                case MutationKind::DeleteMolecule:
                    inverse.kind = MutationKind::AddMolecule;
                    inverse.molecule = PatternMoleculeRef{
                        PatternSide::Product,
                        forwardMutation.molecule.patternIndex,
                        forwardMutation.molecule.moleculeIndex};
                    break;
                }
                reverse.mutations.push_back(std::move(inverse));
            }

            for (const auto& modifier : compiled.modifiers_) {
                if (modifier.kind == ModifierKind::Unknown ||
                    modifier.kind == ModifierKind::MoveConnected ||
                    modifier.kind == ModifierKind::DeleteMolecules) {
                    reverse.transformationsComplete = false;
                }
            }
            compiled.reverse_ = std::move(reverse);
        }

        return compiled;
    }
};

} // namespace detail

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule) {
    return detail::RuleCompiler::run(rule, nullptr, nullptr, nullptr);
}

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule,
                                   const SymbolTable& symbols,
                                   std::vector<Diagnostic>* diagnostics) {
    return detail::RuleCompiler::run(rule, nullptr, &symbols, diagnostics);
}

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule,
                                   const ast::Model& model,
                                   const SymbolTable& symbols,
                                   std::vector<Diagnostic>* diagnostics) {
    return detail::RuleCompiler::run(rule, &model, &symbols, diagnostics);
}

} // namespace bng::compile
