#pragma once

#include "nfnext/nfir.hpp"

#include <memory>
#include <stdexcept>
#include <vector>

namespace nfnext {

// Immutable compiled model shared by many independent trajectories.
class CompiledModel {
public:
    explicit CompiledModel(ModelIR model) : model_(std::make_shared<const ModelIR>(std::move(model))) {}
    explicit CompiledModel(std::shared_ptr<const ModelIR> model) : model_(std::move(model)) {
        if (!model_) throw std::invalid_argument("CompiledModel requires a model");
    }

    const ModelIR& ir() const noexcept { return *model_; }
    std::shared_ptr<const ModelIR> sharedIR() const noexcept { return model_; }
    const RuleFamilyIR& family(FamilyId id) const { return model_->rule_families.at(id); }
    BackendKind backend() const noexcept { return model_->preferred_backend; }
    std::uint64_t fingerprint() const noexcept { return model_->fingerprint(); }

private:
    std::shared_ptr<const ModelIR> model_;
};

} // namespace nfnext
