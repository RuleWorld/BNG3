#pragma once

#include <memory>
#include <unordered_map>

#include "CompiledModel.hpp"
#include "Pattern.hpp"
#include "core/BNGcore.hpp"

namespace bng::ast { class Model; }

namespace bng::compile {

// Backend-owned type storage for lowering semantic patterns into legacy
// BNGcore graphs. This removes the historical requirement that an ast::Model
// stay alive merely to own BNGcore EntityType/StateType pointers.
class BNGcoreLoweringContext {
public:
    explicit BNGcoreLoweringContext(const CompiledModel& model) : model_(&model) {}
    ~BNGcoreLoweringContext() = default;
    BNGcoreLoweringContext(BNGcoreLoweringContext&&) noexcept = default;
    BNGcoreLoweringContext& operator=(BNGcoreLoweringContext&&) noexcept = default;
    BNGcoreLoweringContext(const BNGcoreLoweringContext&) = delete;
    BNGcoreLoweringContext& operator=(const BNGcoreLoweringContext&) = delete;

    const CompiledModel& model() const noexcept { return *model_; }
    const BNGcore::EntityType& ensureMoleculeType(MoleculeTypeId id);
    const BNGcore::EntityType& ensureComponentType(ComponentTypeId id);

private:
    struct ComponentRuntimeType {
        std::unique_ptr<BNGcore::StateType> stateType;
        std::unique_ptr<BNGcore::EntityType> nodeType;
    };

    struct ComponentKeyHash {
        std::size_t operator()(ComponentTypeId id) const noexcept {
            const auto a = id.moleculeType.value();
            const auto b = id.index;
            // Hash combination only determines bucket placement; equality on
            // ComponentTypeId is still checked by unordered_map, so collisions
            // cannot alias distinct semantic components.
            return a ^ (b + static_cast<std::size_t>(0x9e3779b97f4a7c15ULL) +
                        (a << 6U) + (a >> 2U));
        }
    };

    const CompiledModel* model_;
    std::unordered_map<std::size_t, std::unique_ptr<BNGcore::EntityType>> moleculeTypes_;
    std::unordered_map<ComponentTypeId, ComponentRuntimeType, ComponentKeyHash> componentTypes_;
};

BNGcore::PatternGraph lowerPatternToBNGcore(
    const Pattern& pattern,
    BNGcoreLoweringContext& context,
    bool treatUnspecifiedBondAsWildcard = false);

// Compatibility lowering for callers that still use ast::Model as BNGcore type
// storage. New backend code should use BNGcoreLoweringContext.
BNGcore::PatternGraph lowerPatternToBNGcore(
    const Pattern& pattern,
    ast::Model& model,
    bool treatUnspecifiedBondAsWildcard = false);

} // namespace bng::compile
