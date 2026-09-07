#pragma once

#include "nfnext/nfir.hpp"
#include "nfnext/rule_family.hpp"

namespace nfnext {

struct CompileOptions {
    bool collapse_indexed_rules{true};
    bool build_dependency_index{true};
    bool prefer_lattice_when_compatible{true};
};

struct CompileReport {
    FamilyCollapseStats family_stats;
    std::size_t dependency_features{0};
    BackendKind selected_backend{BackendKind::Generic};
};

class ModelCompiler {
public:
    CompileReport compile(ModelIR& model, const CompileOptions& options = {}) const;

    static bool latticeCompatible(const ModelIR& model) noexcept;
    static void buildDependencies(ModelIR& model);
};

} // namespace nfnext
