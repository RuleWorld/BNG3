#pragma once

#include <filesystem>
#include <memory>
#include <string>

#include "ast/RxnList.hpp"
#include "ast/SpeciesList.hpp"
#include "compile/Document.hpp"

namespace bng::ast { class Model; }
namespace bng::compile { class BNGcoreLoweringContext; }

namespace bng::engine {

struct GeneratedNetwork {
    ast::SpeciesList species;
    ast::RxnList reactions;

    // Species and reaction graphs retain pointers to the BNGcore node/state
    // types created during compiled lowering. Keep that storage alive for the
    // lifetime of the generated network rather than the generator call.
    std::shared_ptr<compile::BNGcoreLoweringContext> loweringContext;
};

class NetworkGenerator {
public:
    // Compatibility constructor for parser-facing callers. The model is
    // compiled immediately; generation itself consumes compile::Document.
    explicit NetworkGenerator(ast::Model& model);
    explicit NetworkGenerator(const compile::Document& document);

    GeneratedNetwork generate(const std::filesystem::path& sourcePath);
    GeneratedNetwork generateNative(std::size_t maxIter = 32);

    const compile::Document& document() const noexcept { return document_; }

private:
    ast::Model* sourceModel_ = nullptr; // source-preserving NetWriter bridge only
    compile::Document document_;
};

} // namespace bng::engine
