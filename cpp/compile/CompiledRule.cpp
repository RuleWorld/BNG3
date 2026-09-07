#include "CompiledRule.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace bng::compile {

namespace {

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

} // namespace

CompiledRule CompiledRule::compile(const ast::ReactionRule& rule) {
    CompiledRule compiled;
    compiled.name_ = rule.getRuleName();
    compiled.label_ = rule.getLabel();
    // Empty operations include implicit whole-species deletion in the AST.
    // Never interpret absent edit metadata as proof of no dependencies.
    compiled.conservativeInvalidation_ = rule.getOperations().empty();
    compiled.bidirectional_ = rule.isBidirectional();

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

} // namespace bng::compile
