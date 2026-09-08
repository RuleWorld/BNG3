#include "CompiledModel.hpp"

#include <stdexcept>
#include <utility>

namespace bng::compile {

CompiledModel::CompiledModel(const ast::Model& model)
    : features_(featuresUsed(model)),
      symbols_(SymbolTable::fromModel(model)),
      diagnostics_(symbols_.diagnostics()) {
    rules_.reserve(model.getReactionRules().size());
    for (std::size_t index = 0; index < model.getReactionRules().size(); ++index) {
        auto compiled = CompiledRule::compile(
            model.getReactionRules()[index], symbols_, &diagnostics_);
        compiled.setId(ReactionRuleId::fromDenseIndex(index));
        rules_.push_back(std::move(compiled));
    }

    functions_.reserve(model.getFunctions().size());
    for (std::size_t index = 0; index < model.getFunctions().size(); ++index) {
        const auto& function = model.getFunctions()[index];
        const auto compiled = CompiledRateLaw::compile(
            function.getExpression(), symbols_, function.getArgs());
        diagnostics_.insert(diagnostics_.end(), compiled.diagnostics().begin(),
                            compiled.diagnostics().end());
        functions_.push_back(CompiledFunction{
            FunctionId::fromDenseIndex(index), function.getName(), function.getArgs(),
            compiled.resolvedExpression()});
    }

    energyFactors_.reserve(model.getEnergyPatterns().size());
    for (std::size_t index = 0; index < model.getEnergyPatterns().size(); ++index) {
        const auto& factor = model.getEnergyPatterns()[index];
        CompiledEnergyFactor compiled;
        compiled.id = EnergyPatternId::fromDenseIndex(index);
        compiled.index = index;
        compiled.label = factor.getLabel();
        compiled.sourcePattern = factor.getPattern();
        compiled.structuralFingerprint = factor.getGraph().fingerprint();
        compiled.energyExpression = factor.getExpression().toString();
        compiled.pattern = Pattern::fromSpeciesGraph(factor.getGraph());
        energyFactors_.push_back(std::move(compiled));
    }

    observables_.reserve(model.getObservables().size());
    for (std::size_t index = 0; index < model.getObservables().size(); ++index) {
        const auto& observable = model.getObservables()[index];
        CompiledObservable compiled;
        compiled.id = ObservableId::fromDenseIndex(index);
        compiled.index = index;
        compiled.name = observable.getName();
        compiled.type = observable.getType();
        compiled.sourcePatterns = observable.getPatterns();
        for (const auto& sourcePattern : compiled.sourcePatterns) {
            try {
                compiled.patterns.push_back(Pattern::parse(sourcePattern));
            } catch (const std::invalid_argument& error) {
                Diagnostic diagnostic;
                diagnostic.code = DiagnosticCode::InvalidModel;
                diagnostic.severity = Severity::Error;
                diagnostic.category = ValidationCategory::Patterns;
                diagnostic.entity = compiled.name;
                diagnostic.message = "invalid observable pattern '" + sourcePattern +
                                     "': " + error.what();
                diagnostics_.push_back(std::move(diagnostic));
            }
        }
        observables_.push_back(std::move(compiled));
    }

    seeds_.reserve(model.getSeedSpecies().size());
    for (std::size_t index = 0; index < model.getSeedSpecies().size(); ++index) {
        const auto& seed = model.getSeedSpecies()[index];
        CompiledSeed compiled;
        compiled.id = SeedSpeciesId::fromDenseIndex(index);
        compiled.index = index;
        compiled.sourcePattern = seed.getPattern();
        compiled.amountExpression = seed.getAmount().toString();
        compiled.constant = seed.isConstant();
        compiled.compartment = seed.getCompartment();
        compiled.structuralFingerprint = seed.getGraph().computeFingerprint();
        compiled.pattern = Pattern::fromSpeciesGraph(
            ast::SpeciesGraph(seed.getGraph(), seed.getCompartment()));
        seeds_.push_back(std::move(compiled));
    }
}

} // namespace bng::compile
