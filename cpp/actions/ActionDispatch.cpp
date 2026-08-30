#include "actions/ActionDispatch.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <optional>
#include <iomanip>
#include <set>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "ast/Parameter.hpp"
#include "engine/NetworkGenerator.hpp"
#include "engine/OdeIntegrator.hpp"
#include "engine/PlaSimulator.hpp"
#include "engine/PsaSimulator.hpp"
#include "engine/HybridModelGenerator.hpp"
#include "io/NetWriter.hpp"
#include "io/XmlWriter.hpp"
#include "io/BnglWriter.hpp"
#include "io/NetReader.hpp"
#include "io/SbmlReader.hpp"
#include "io/SbmlWriter.hpp"
#include "io/SbmlMultiWriter.hpp"
#include "io/MatlabWriter.hpp"
#include "io/CppExportWriter.hpp"
#include "io/PythonExportWriter.hpp"
#include "io/ContactMapWriter.hpp"
#include "io/MexWriter.hpp"
#include "io/RegulatoryGraphWriter.hpp"
#include "io/ReactionNetworkGraphWriter.hpp"
#include "io/LatexWriter.hpp"
#include "io/MdlWriter.hpp"
#include "io/SscWriter.hpp"
#include "io/RulevizPatternWriter.hpp"
#include "io/RulevizOperationWriter.hpp"
#include "io/ProcessGraphWriter.hpp"
#include "io/RuleInfluenceGraphWriter.hpp"
#include "parser/BNGAstVisitor.hpp"

// NFsim in-process invocation
#include "nfsim/NFinput/NFinput.hh"
#include "nfsim/NFinput/NFinput_fromAst.hh"
#include "nfsim/NFcore/NFcore.hh"

#if defined(_WIN32) || defined(__WIN32__) || defined(__CYGWIN__)
#include <process.h>
#else
#include <unistd.h>
#include <sys/wait.h>
#endif

namespace bng::actions {

namespace {

std::string trim(std::string value) {
    auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    if (first >= last) {
        return {};
    }
    return std::string(first, last);
}

std::string stripQuotes(const std::string& text) {
    if (text.size() >= 2 &&
        ((text.front() == '"' && text.back() == '"') || (text.front() == '\'' && text.back() == '\''))) {
        return text.substr(1, text.size() - 2);
    }
    return text;
}

std::string lowercase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

double parseScalarValue(const std::string& text, ast::Model& model) {
    std::string value = stripQuotes(trim(text));
    std::replace(value.begin(), value.end(), 'D', 'E');
    std::replace(value.begin(), value.end(), 'd', 'e');

    std::size_t consumed = 0;
    try {
        const double parsed = std::stod(value, &consumed);
        if (consumed == value.size()) {
            return parsed;
        }
    } catch (const std::exception&) {
        // Try parameter name fallback below.
    }

    if (model.getParameters().contains(value)) {
        return model.getParameters().evaluate(value);
    }

    // Try evaluating as expression with parameter resolution
    try {
        // Simple recursive evaluator for expressions like "2e-9*NA*V"
        double result = 1.0;
        std::string token;
        std::istringstream stream(value);
        bool allResolved = true;
        while (std::getline(stream, token, '*')) {
            std::string t = trim(token);
            if (t.empty()) continue;
            std::size_t pos = 0;
            try {
                double val = std::stod(t, &pos);
                if (pos == t.size()) { result *= val; continue; }
            } catch (...) {}
            if (model.getParameters().contains(t)) {
                result *= model.getParameters().evaluate(t);
            } else {
                allResolved = false;
                break;
            }
        }
        if (allResolved) return result;
    } catch (...) {}

    // Fallback: parse as a full expression (handles nested parentheses, division, etc.)
    try {
        auto expr = bng::parser::parseExpression(value);
        return expr.evaluate([&](const std::string& name) {
            return model.getParameters().evaluate(name);
        });
    } catch (...) {}

    throw std::runtime_error("Unsupported scalar action value: '" + text + "'");
}

std::vector<double> parseSampleTimes(const std::string& text, ast::Model& model) {
    std::string value = trim(stripQuotes(text));
    if (value.size() < 2 || value.front() != '[' || value.back() != ']') {
        throw std::runtime_error(
            "sample_times must be a comma-separated list enclosed in square brackets");
    }
    value = value.substr(1, value.size() - 2);
    std::vector<double> times;
    std::size_t start = 0;
    while (start <= value.size()) {
        const auto comma = value.find(',', start);
        const auto token = trim(value.substr(start, comma == std::string::npos
                                                       ? std::string::npos
                                                       : comma - start));
        if (token.empty()) {
            throw std::runtime_error("sample_times must not contain empty entries");
        }
        const double time = parseScalarValue(token, model);
        if (!std::isfinite(time)) {
            throw std::runtime_error("sample_times must contain only finite values");
        }
        times.push_back(time);
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    if (times.empty()) {
        throw std::runtime_error("sample_times must not be empty");
    }
    for (std::size_t i = 1; i < times.size(); ++i) {
        if (times[i] <= times[i - 1]) {
            throw std::runtime_error(
                "sample_times must be strictly increasing");
        }
    }
    return times;
}

std::vector<double> parseScalarList(const std::string& text,
                                    ast::Model& model,
                                    const std::string& name) {
    std::string value = trim(stripQuotes(text));
    if (value.size() < 2 || value.front() != '[' || value.back() != ']') {
        throw std::runtime_error(
            name + " must be a comma-separated list enclosed in square brackets");
    }

    value = value.substr(1, value.size() - 2);
    std::vector<double> values;
    std::size_t tokenStart = 0;
    int parentheses = 0;
    int brackets = 0;
    char quote = '\0';

    const auto appendToken = [&](std::size_t tokenEnd) {
        const auto token = trim(value.substr(tokenStart, tokenEnd - tokenStart));
        if (token.empty()) {
            throw std::runtime_error(name + " must not contain empty entries");
        }
        const double parsed = parseScalarValue(token, model);
        if (!std::isfinite(parsed)) {
            throw std::runtime_error(name + " must contain only finite values");
        }
        values.push_back(parsed);
    };

    for (std::size_t i = 0; i < value.size(); ++i) {
        const char current = value[i];
        if (quote != '\0') {
            if (current == quote && (i == 0 || value[i - 1] != '\\')) {
                quote = '\0';
            }
            continue;
        }
        if (current == '\'' || current == '"') {
            quote = current;
        } else if (current == '(') {
            ++parentheses;
        } else if (current == ')') {
            if (--parentheses < 0) {
                throw std::runtime_error(name + " contains unbalanced parentheses");
            }
        } else if (current == '[') {
            ++brackets;
        } else if (current == ']') {
            if (--brackets < 0) {
                throw std::runtime_error(name + " contains unbalanced brackets");
            }
        } else if (current == ',' && parentheses == 0 && brackets == 0) {
            appendToken(i);
            tokenStart = i + 1;
        }
    }

    if (quote != '\0' || parentheses != 0 || brackets != 0) {
        throw std::runtime_error(name + " contains an unbalanced expression");
    }
    if (tokenStart < value.size() || !value.empty()) {
        appendToken(value.size());
    }
    if (values.empty()) {
        throw std::runtime_error(name + " must not be empty");
    }
    return values;
}

std::size_t parseNonNegativeCount(const std::string& text,
                                  ast::Model& model,
                                  const std::string& name) {
    const double value = parseScalarValue(text, model);
    if (!std::isfinite(value) || value < 0.0 || std::floor(value) != value ||
        value > static_cast<double>(std::numeric_limits<std::size_t>::max())) {
        throw std::runtime_error(name + " must be a non-negative integer");
    }
    return static_cast<std::size_t>(value);
}

bool parseBoolean(const std::string& text, bool defaultValue = false) {
    const auto value = lowercase(stripQuotes(trim(text)));
    if (value.empty()) {
        return defaultValue;
    }
    if (value == "1" || value == "true" || value == "yes" || value == "on") {
        return true;
    }
    if (value == "0" || value == "false" || value == "no" || value == "off") {
        return false;
    }
    throw std::runtime_error("Expected a boolean value, got '" + text + "'");
}

struct ScanData {
    std::vector<std::string> columns;
    std::vector<double> values;
};

struct TrajectoryData {
    std::vector<std::string> columns;
    std::vector<std::vector<double>> rows;
};

TrajectoryData readDat(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("sensitivity could not open data file: " + path.string());
    }

    TrajectoryData data;
    std::string line;
    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty()) {
            continue;
        }
        if (line.front() == '#') {
            std::istringstream header(line.substr(1));
            header >> std::ws;
            std::string column;
            while (header >> column) {
                data.columns.push_back(column);
            }
            continue;
        }

        std::istringstream rowStream(line);
        std::vector<double> row;
        double value = 0.0;
        while (rowStream >> value) {
            if (!std::isfinite(value)) {
                throw std::runtime_error(
                    "sensitivity found a non-finite value in " + path.string());
            }
            row.push_back(value);
        }
        if (!row.empty()) {
            data.rows.push_back(std::move(row));
        }
    }

    if (data.columns.size() < 2 || data.rows.empty()) {
        throw std::runtime_error("sensitivity found an invalid data file: " + path.string());
    }
    for (const auto& row : data.rows) {
        if (row.size() != data.columns.size()) {
            throw std::runtime_error(
                "sensitivity found an inconsistent row in " + path.string());
        }
    }
    return data;
}

void writeSensitivityFile(const std::filesystem::path& baselinePath,
                          const std::filesystem::path& perturbedPath,
                          const std::filesystem::path& outputPath,
                          double parameterDelta) {
    const auto baseline = readDat(baselinePath);
    const auto perturbed = readDat(perturbedPath);
    if (baseline.columns != perturbed.columns ||
        baseline.rows.size() != perturbed.rows.size()) {
        throw std::runtime_error(
            "sensitivity baseline and perturbed trajectories have different shapes");
    }
    for (std::size_t row = 0; row < baseline.rows.size(); ++row) {
        if (std::abs(baseline.rows[row][0] - perturbed.rows[row][0]) >
            1e-12 * std::max({1.0, std::abs(baseline.rows[row][0]),
                              std::abs(perturbed.rows[row][0])})) {
            throw std::runtime_error(
                "sensitivity baseline and perturbed trajectories use different time grids");
        }
    }

    std::ofstream output(outputPath);
    if (!output) {
        throw std::runtime_error("sensitivity could not open output file: " + outputPath.string());
    }
    output << std::setw(16) << "# time";
    for (const auto& row : baseline.rows) {
        output << " " << std::setw(16) << std::setprecision(8) << std::scientific
               << row[0];
    }
    output << '\n';

    for (std::size_t column = 1; column < baseline.columns.size(); ++column) {
        output << std::setw(16) << baseline.columns[column];
        for (std::size_t row = 0; row < baseline.rows.size(); ++row) {
            const double sensitivity = parameterDelta == 0.0
                ? 0.0
                : (perturbed.rows[row][column] - baseline.rows[row][column]) /
                      parameterDelta;
            output << " " << std::setw(16) << std::setprecision(8)
                   << std::scientific << sensitivity;
        }
        output << '\n';
    }
}

ScanData readLastGdat(const std::filesystem::path& path, const ast::Model& model) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("parameter_scan could not open observable file: " + path.string());
    }

    std::vector<std::string> columns;
    std::vector<double> lastValues;
    std::string line;
    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty()) {
            continue;
        }
        if (line.front() == '#') {
            std::istringstream header(line.substr(1));
            header >> std::ws;
            std::string column;
            while (header >> column) {
                columns.push_back(column);
            }
            continue;
        }

        std::istringstream data(line);
        std::vector<double> values;
        double value = 0.0;
        while (data >> value) {
            if (!std::isfinite(value)) {
                throw std::runtime_error(
                    "parameter_scan found a non-finite value in " + path.string());
            }
            values.push_back(value);
        }
        if (!values.empty()) {
            lastValues = std::move(values);
        }
    }

    // Native NFsim output is intentionally headerless.  Recover the stable
    // column contract from the model rather than inventing names or dropping
    // the data from an NF parameter scan.
    if (columns.empty()) {
        columns.push_back("time");
        for (const auto& observable : model.getObservables()) {
            columns.push_back(observable.getName());
        }
    }
    if (columns.size() < 2 || lastValues.size() != columns.size()) {
        throw std::runtime_error(
            "parameter_scan found an invalid observable file: " + path.string());
    }
    columns.erase(columns.begin()); // drop the time column
    lastValues.erase(lastValues.begin());
    return {std::move(columns), std::move(lastValues)};
}

void writeScanFile(const std::filesystem::path& path,
                   const std::string& parameterName,
                   const std::vector<double>& parameterValues,
                   const std::vector<ScanData>& data) {
    if (parameterValues.size() != data.size() || data.empty()) {
        throw std::runtime_error("parameter_scan has no complete scan data");
    }
    for (std::size_t i = 1; i < data.size(); ++i) {
        if (data[i].columns != data[0].columns ||
            data[i].values.size() != data[0].values.size()) {
            throw std::runtime_error(
                "parameter_scan observable columns changed between scan points");
        }
    }

    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("parameter_scan could not open output file: " + path.string());
    }
    output << "#" << std::setw(15) << parameterName;
    for (const auto& column : data[0].columns) {
        output << " " << std::setw(16) << column;
    }
    output << '\n';
    for (std::size_t i = 0; i < parameterValues.size(); ++i) {
        output << std::setw(16) << std::setprecision(8) << std::scientific
               << parameterValues[i];
        for (const auto value : data[i].values) {
            output << " " << std::setw(16) << std::setprecision(8) << std::scientific
                   << value;
        }
        output << '\n';
    }
}

std::string formatScalar(double value) {
    std::ostringstream output;
    output << std::setprecision(17) << value;
    return output.str();
}

std::string readArgument(const ast::Action& action, const std::string& key, const std::string& fallback = {}) {
    const auto found = action.arguments.find(key);
    if (found == action.arguments.end()) {
        return fallback;
    }
    return found->second;
}

engine::GeneratedNetwork networkFromParsedData(
    const io::NetReader::ParseResult& parseResult, ast::Model& model) {
    engine::GeneratedNetwork loadedNetwork;
    for (const auto& [pattern, concStr] : parseResult.species) {
        bool isConstant = false;
        std::string cleanPattern = pattern;
        if (!cleanPattern.empty() && cleanPattern[0] == '$') {
            isConstant = true;
            cleanPattern = cleanPattern.substr(1);
        }
        BNGcore::PatternGraph pg;
        pg.set_raw_string(cleanPattern);
        ast::SpeciesGraph sg(std::move(pg));
        double concentration = 0.0;
        try {
            concentration = std::stod(concStr);
        } catch (...) {
            try {
                concentration = model.getParameters().evaluate(concStr);
            } catch (...) {
                concentration = 0.0;
            }
        }
        ast::Species sp(std::move(sg), concentration, isConstant);
        loadedNetwork.species.add(std::move(sp));
    }

    for (const auto& rxnLine : parseResult.reactions) {
        std::istringstream iss(rxnLine);
        std::string idxStr, reactantsStr, productsStr, rateStr;
        iss >> idxStr >> reactantsStr >> productsStr;
        std::getline(iss, rateStr);
        auto rateStart = rateStr.find_first_not_of(" \t");
        if (rateStart != std::string::npos) {
            rateStr = rateStr.substr(rateStart);
        }
        const auto commentPos = rateStr.find('#');
        if (commentPos != std::string::npos) {
            rateStr = rateStr.substr(0, commentPos);
        }
        while (!rateStr.empty() && std::isspace(rateStr.back())) {
            rateStr.pop_back();
        }

        std::vector<std::size_t> reactants;
        if (reactantsStr != "0") {
            std::istringstream rss(reactantsStr);
            std::string token;
            while (std::getline(rss, token, ',')) {
                reactants.push_back(std::stoul(token) - 1);
            }
        }
        std::vector<std::size_t> products;
        if (productsStr != "0") {
            std::istringstream pss(productsStr);
            std::string token;
            while (std::getline(pss, token, ',')) {
                products.push_back(std::stoul(token) - 1);
            }
        }
        loadedNetwork.reactions.add(
            ast::Rxn(idxStr, reactants, products, rateStr));
    }
    return loadedNetwork;
}

std::string resolveSimulationMethod(const ast::Action& action) {
    std::string name = lowercase(action.name);
    if (name == "simulate_ode") {
        return "cvode";
    }
    if (name == "simulate_ssa") {
        return "ssa";
    }

    std::string method = lowercase(stripQuotes(readArgument(action, "method", "ode")));
    if (method == "ode") {
        return "cvode";
    }
    if (method == "pla") {
        return "pla";
    }
    if (method == "nf") {
        return "nf";
    }
    if (method == "cvode" || method == "ssa" || method == "euler" ||
        method == "rk4" || method == "psa") {
        return method;
    }
    throw std::runtime_error("simulate: unsupported simulation method: " + method);
}

std::optional<std::size_t> findSpeciesIndex(const engine::GeneratedNetwork& network, const std::string& target) {
    const std::string needle = stripQuotes(trim(target));
    // Pass 1: exact match on canonical string or full string (with compartment/constant prefix)
    for (std::size_t i = 0; i < network.species.size(); ++i) {
        const auto& species = network.species.get(i);
        const auto canonical = species.getSpeciesGraph().toString();
        // Build two full-string variants:
        //   @comp::pattern  (internal .net format, double colon)
        //   @comp:pattern   (BNGL action format, single colon used by Perl)
        std::string fullDouble, fullSingle;
        if (!species.getCompartment().empty()) {
            fullDouble += "@" + species.getCompartment() + "::";
            fullSingle += "@" + species.getCompartment() + ":";
        }
        if (species.isConstant()) {
            fullDouble += "$";
            fullSingle += "$";
        }
        fullDouble += canonical;
        fullSingle += canonical;

        if (needle == canonical || needle == fullDouble || needle == fullSingle) {
            return i;
        }
    }
    // Pass 2: Perl BNG2 compatibility — match by molecule name prefix
    // e.g., "EGF" matches "EGF(R)" or "EGF(R,Y~U)"
    for (std::size_t i = 0; i < network.species.size(); ++i) {
        const auto& species = network.species.get(i);
        const auto canonical = species.getSpeciesGraph().toString();
        // Check if canonical starts with needle followed by '(' or is exactly needle
        if (canonical.rfind(needle, 0) == 0) {
            if (canonical.size() == needle.size() ||
                canonical[needle.size()] == '(' ||
                canonical[needle.size()] == '.') {
                return i;
            }
        }
    }
    return std::nullopt;
}

std::vector<double> snapshotConcentrations(const engine::GeneratedNetwork& network) {
    std::vector<double> values;
    values.reserve(network.species.size());
    for (const auto& species : network.species.all()) {
        values.push_back(species.getAmount());
    }
    return values;
}

void restoreConcentrations(engine::GeneratedNetwork& network, const std::vector<double>& values) {
    const auto count = std::min(network.species.size(), values.size());
    for (std::size_t i = 0; i < count; ++i) {
        network.species.get(i).setAmount(values[i]);
    }
}

struct TfunFileReference {
    std::string key;
    std::string path;
    std::string method;
};

void collectTfunFiles(const ast::Expression& expr,
                      std::vector<TfunFileReference>& references) {
    if (expr.kind() == ast::ExpressionKind::TableFunction &&
        !expr.tableFilePath().empty()) {
        references.push_back({expr.tableFileKey(), expr.tableFilePath(), expr.tableMethod()});
    } else if (expr.kind() == ast::ExpressionKind::Function &&
               lowercase(expr.name()) == "tfun") {
        // Preserve support for hand-built legacy AST nodes while parsed BNGL
        // now uses the explicit TableFunction node.
        std::string name;
        if (expr.args().size() == 1 &&
            expr.args()[0].kind() == ast::ExpressionKind::Identifier) {
            name = expr.args()[0].name();
        } else if (expr.args().size() >= 2 &&
                   expr.args()[1].kind() == ast::ExpressionKind::Identifier) {
            name = expr.args()[1].name();
        }
        if (!name.empty()) references.push_back({name, name + ".tfun", "linear"});
    }
    for (const auto& child : expr.args()) {
        collectTfunFiles(child, references);
    }
}

std::vector<TfunFileReference> findTfunReferences(const ast::Model& model) {
    std::vector<TfunFileReference> references;
    for (const auto& fn : model.getFunctions()) {
        collectTfunFiles(fn.getExpression(), references);
    }
    for (const auto& param : model.getParameters().all()) {
        collectTfunFiles(param.getExpression(), references);
    }
    return references;
}

void loadTfunFiles(engine::OdeIntegrator& integrator, const ast::Model& model, const std::filesystem::path& sourcePath) {
    const auto references = findTfunReferences(model);
    std::set<std::string> loaded;
    for (const auto& reference : references) {
        const std::filesystem::path source(reference.path);
        const auto tfunPath = source.is_absolute() ? source : sourcePath.parent_path() / source;
        if (!loaded.insert(reference.key).second) continue;
        if (std::filesystem::exists(tfunPath)) {
            integrator.loadTfun(reference.key, tfunPath.string(), reference.method);
        }
    }
}

std::string simulationPrefix(const ast::Action& action, const std::filesystem::path& sourcePath, std::optional<std::size_t> scanIndex = std::nullopt) {
    std::string prefix = stripQuotes(readArgument(action, "prefix", sourcePath.stem().string()));
    const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
    if (!suffix.empty()) {
        prefix += "_" + suffix;
    }
    if (scanIndex.has_value()) {
        prefix += "_scan" + std::to_string(*scanIndex + 1);
    }
    return prefix;
}

void runSimulation(
    ast::Model& model,
    const ast::Action& actionOrig,
    const std::filesystem::path& sourcePath,
    engine::GeneratedNetwork& network,
    bool verbose,
    std::vector<double>& lastSimulationState,
    double& lastSimulationEndTime) {

    // Handle argfile: read arguments from file (file args have lower priority than inline args)
    ast::Action action = actionOrig;
    {
        const auto argfileText = stripQuotes(readArgument(action, "argfile", ""));
        if (!argfileText.empty()) {
            std::filesystem::path argfilePath(argfileText);
            if (!argfilePath.is_absolute()) {
                argfilePath = sourcePath.parent_path() / argfileText;
            }
            std::ifstream argfile(argfilePath);
            if (!argfile) {
                throw std::runtime_error("Could not open argfile: " + argfilePath.string());
            }
            std::string line;
            while (std::getline(argfile, line)) {
                line = trim(line);
                if (line.empty() || line[0] == '#') continue; // skip comments/blanks
                // Parse "key value" or "key=value"
                std::string key, value;
                auto eqPos = line.find('=');
                if (eqPos != std::string::npos) {
                    key = trim(line.substr(0, eqPos));
                    value = trim(line.substr(eqPos + 1));
                } else {
                    std::istringstream iss(line);
                    iss >> key;
                    std::getline(iss, value);
                    value = trim(value);
                }
                // File args have lower priority: only insert if not already present
                if (!key.empty() && action.arguments.find(key) == action.arguments.end()) {
                    action.arguments[key] = value;
                }
            }
            if (verbose) {
                std::cerr << "[bng_cpp] Loaded arguments from argfile: " << argfilePath.string() << "\n";
            }
        }
    }

    const auto method = resolveSimulationMethod(action);
    const auto tEnd = stripQuotes(readArgument(action, "t_end", ""));
    const auto nSteps = stripQuotes(readArgument(action, "n_steps", stripQuotes(readArgument(action, "n_output_steps", ""))));
    const auto sampleTimesText = readArgument(action, "sample_times", "");
    const bool hasSampleTimes = !trim(stripQuotes(sampleTimesText)).empty();
    const bool hasStepCount = !nSteps.empty();
    if (tEnd.empty() && (!hasSampleTimes || hasStepCount)) {
        throw std::runtime_error(
            "simulate requires t_end, or sample_times when n_steps is omitted");
    }
    if (hasStepCount && tEnd.empty()) {
        throw std::runtime_error("simulate requires t_end when n_steps is provided");
    }

    // Parse simulation options
    engine::OdeOptions opts;
    if (!tEnd.empty()) {
        opts.tEnd = parseScalarValue(tEnd, model);
    }
    if (!nSteps.empty()) {
        opts.nSteps = parseNonNegativeCount(nSteps, model, "n_steps");
        if (opts.nSteps == 0) {
            throw std::runtime_error("n_steps must be positive");
        }
    }

    // Parse t_start (BNG2 parity)
    const auto tStartText = readArgument(action, "t_start", "");
    if (!tStartText.empty()) {
        opts.tStart = parseScalarValue(tStartText, model);
    }

    if (hasSampleTimes && hasStepCount) {
        std::cerr << "WARNING: n_steps and sample_times both defined. "
                     "n_steps takes precedence.\n";
    } else if (hasSampleTimes) {
        opts.sampleTimes = parseSampleTimes(sampleTimesText, model);
        if (tEnd.empty()) {
            opts.tEnd = opts.sampleTimes.back();
        } else if (opts.sampleTimes.back() > opts.tEnd) {
            throw std::runtime_error(
                "sample_times cannot extend beyond t_end");
        } else if (opts.sampleTimes.back() < opts.tEnd) {
            opts.sampleTimes.push_back(opts.tEnd);
        }
        if (opts.sampleTimes.front() < opts.tStart) {
            throw std::runtime_error(
                "sample_times cannot occur before t_start");
        }
        opts.nSteps = opts.sampleTimes.size() > 1
            ? opts.sampleTimes.size() - 1
            : 1;
    }

    // Parse method (match BNG2 defaults)
    if (method == "cvode" || method == "ode") {
        opts.method = "cvode";
    } else if (method == "ssa") {
        opts.method = "ssa";
    } else if (method == "euler") {
        opts.method = "euler";
    } else if (method == "rk4") {
        opts.method = "rk4";
    } else if (method == "pla") {
        opts.method = "pla";
    } else {
        opts.method = "cvode";  // Default to CVODE (matches BNG2)
    }

    // Parse seed for SSA/PLA
    if (opts.method == "ssa" || opts.method == "pla") {
        const auto seedText = readArgument(action, "seed", "");
        if (!seedText.empty()) {
            opts.seed = static_cast<unsigned int>(parseScalarValue(seedText, model));
        }
    }

    // Parse tolerances if provided
    const auto atolText = readArgument(action, "atol", "");
    if (!atolText.empty()) {
        opts.atol = parseScalarValue(atolText, model);
    }
    const auto rtolText = readArgument(action, "rtol", "");
    if (!rtolText.empty()) {
        opts.rtol = parseScalarValue(rtolText, model);
    }

    const auto maxStepText = readArgument(action, "max_step", "");
    if (!maxStepText.empty()) {
        opts.maxStep = parseScalarValue(maxStepText, model);
        if (!std::isfinite(opts.maxStep) || opts.maxStep < 0.0) {
            throw std::runtime_error("max_step must be finite and non-negative");
        }
    }

    // Parse steady_state option (BNG2 parity)
    const auto steadyStateText = lowercase(stripQuotes(readArgument(action, "steady_state", "0")));
    opts.steadyState = (steadyStateText == "1" || steadyStateText == "true");
    if (opts.steadyState) {
        opts.steadyStateTol = opts.atol;  // Use atol for steady-state check
    }
    const auto steadyStateTolText = readArgument(action, "steady_state_tol", "");
    if (!steadyStateTolText.empty()) {
        opts.steadyStateTol = parseScalarValue(steadyStateTolText, model);
        if (!std::isfinite(opts.steadyStateTol) || opts.steadyStateTol <= 0.0) {
            throw std::runtime_error(
                "steady_state_tol must be finite and positive");
        }
    }

    // Parse stop_if expression (BNG2 parity)
    opts.stopIf = stripQuotes(readArgument(action, "stop_if", ""));

    // Parse print_CDAT flag (BNG2 parity)
    const auto printCDATText = lowercase(stripQuotes(readArgument(action, "print_CDAT", readArgument(action, "print_cdat", "1"))));
    opts.printCDAT = (printCDATText != "0" && printCDATText != "false");

    // Parse print_functions flag (BNG2 parity: include function values in .gdat)
    const auto printFunctionsText = lowercase(stripQuotes(readArgument(action, "print_functions", "0")));
    opts.printFunctions = (printFunctionsText == "1" || printFunctionsText == "true");

    // Parse binary_output flag (BNG2 parity: write .cdat/.gdat in binary format)
    const auto binaryOutputText = lowercase(stripQuotes(readArgument(action, "binary_output", "0")));
    opts.binaryOutput = (binaryOutputText == "1" || binaryOutputText == "true");

    // Parse continue flag (BNG2 parity)
    const auto continueText = lowercase(stripQuotes(readArgument(action, "continue", "0")));
    bool continueSimulation = (continueText == "1" || continueText == "true");

    // When continue=1 and no explicit t_start, use the previous simulation's end time
    if (continueSimulation && tStartText.empty() && lastSimulationEndTime > 0.0) {
        opts.tStart = lastSimulationEndTime;
    }

    // Parse save_progress flag (BNG2 parity: write .net checkpoint at each output step)
    const auto saveProgressText = lowercase(stripQuotes(readArgument(action, "save_progress", "0")));
    opts.saveProgress = (saveProgressText == "1" || saveProgressText == "true");

    // Parse print_net flag (BNG2 parity: write .net file after simulation with final concentrations)
    const auto printNetText = lowercase(stripQuotes(readArgument(action, "print_net", "0")));
    opts.printNet = (printNetText == "1" || printNetText == "true");

    // Parse print_end flag (BNG2 parity: output final state when simulation stops early)
    const auto printEndText = lowercase(stripQuotes(readArgument(action, "print_end", "0")));
    opts.printEnd = (printEndText == "1" || printEndText == "true");

    // Parse netfile option (BNG2 parity: use custom .net file instead of auto-generating)
    opts.netfile = stripQuotes(readArgument(action, "netfile", ""));

    // Parse output_step_interval (BNG2 parity: output every N internal steps, mainly for SSA/PLA)
    const auto outputStepIntervalText = readArgument(action, "output_step_interval", "");
    if (!outputStepIntervalText.empty()) {
        opts.outputStepInterval = parseNonNegativeCount(
            outputStepIntervalText, model, "output_step_interval");
    }

    const auto maxSimStepsText = readArgument(action, "max_sim_steps", "");
    if (!maxSimStepsText.empty()) {
        opts.maxSimSteps = parseNonNegativeCount(
            maxSimStepsText, model, "max_sim_steps");
    }

    // Parse sparse option (request sparse Jacobian for large networks)
    const auto sparseText = lowercase(stripQuotes(readArgument(action, "sparse", "0")));
    opts.sparse = (sparseText == "1" || sparseText == "true");

    // Parse evaluate_expressions option (BNG2: keep symbolic expressions in .net)
    const auto evalExprText = lowercase(stripQuotes(readArgument(action, "evaluate_expressions", "1")));
    opts.evaluateExpressions = (evalExprText != "0" && evalExprText != "false");

    // Parse check_product_scale option (validate product concentrations)
    const auto checkProdScaleText = readArgument(action, "check_product_scale", "");
    if (!checkProdScaleText.empty()) {
        opts.checkProductScale = parseScalarValue(checkProdScaleText, model);
        if (!std::isfinite(opts.checkProductScale) || opts.checkProductScale < 0.0) {
            throw std::runtime_error(
                "check_product_scale must be finite and non-negative");
        }
    }

    const bool isOdeMethod = opts.method == "cvode" || opts.method == "euler" ||
        opts.method == "rk4";
    if (!isOdeMethod && (opts.maxStep > 0.0 || opts.steadyState || opts.sparse)) {
        throw std::runtime_error(
            "max_step, steady_state, and sparse require an ODE simulation method");
    }
    if (!isOdeMethod && opts.method != "ssa" && !opts.stopIf.empty()) {
        throw std::runtime_error("stop_if requires an ODE or SSA simulation method");
    }
    if (!isOdeMethod && opts.method != "ssa" && hasSampleTimes) {
        throw std::runtime_error(
            "sample_times requires an ODE or SSA simulation method");
    }
    if (opts.method != "ssa" && opts.outputStepInterval > 0) {
        throw std::runtime_error(
            "output_step_interval requires an SSA simulation method");
    }
    if (opts.method != "ssa" && opts.method != "psa" && opts.maxSimSteps > 0) {
        throw std::runtime_error(
            "max_sim_steps requires an SSA or PSA simulation method");
    }
    if (!isOdeMethod && opts.method != "psa" && opts.checkProductScale > 0.0) {
        throw std::runtime_error(
            "check_product_scale requires an ODE or PSA simulation method");
    }

    if (verbose) {
        std::cerr << "[bng_cpp] Simulating with method=" << opts.method
                  << " t_end=" << opts.tEnd
                  << " n_steps=" << opts.nSteps
                  << " atol=" << opts.atol
                  << " rtol=" << opts.rtol;
        if (opts.steadyState) {
            std::cerr << " steady_state=1";
        }
        if (!opts.stopIf.empty()) {
            std::cerr << " stop_if=\"" << opts.stopIf << "\"";
        }
        if (continueSimulation) {
            std::cerr << " continue=1";
        }
        if (opts.saveProgress) {
            std::cerr << " save_progress=1";
        }
        if (opts.printNet) {
            std::cerr << " print_net=1";
        }
        if (opts.outputStepInterval > 0) {
            std::cerr << " output_step_interval=" << opts.outputStepInterval;
        }
        std::cerr << "\n";
    }

    // If continuing from previous simulation, use current network species amounts.
    // The network already has the correct state from the previous simulate (which updated
    // species amounts) plus any inter-phase modifications via setConcentration/addConcentration.
    // We intentionally do NOT restore from lastSimulationState, as that would overwrite
    // inter-phase concentration changes.
    if (continueSimulation && !lastSimulationState.empty()) {
        if (verbose) {
            std::cerr << "[bng_cpp] Continuing from current network state (continue=1)\n";
        }
    }

    // Run simulation
    engine::OdeResult result;
    if (opts.method == "pla") {
        // PLA simulation
        const auto plaConfigStr = stripQuotes(readArgument(action, "pla_config", "fEuler|pre-neg:sb|eps=0.03"));
        auto plaConfig = engine::PlaConfig::parse(plaConfigStr);
        engine::PlaSimulator simulator(model, network);
        result = simulator.simulate(opts, plaConfig);
    } else if (opts.method == "psa") {
        const auto poplevelText = readArgument(action, "poplevel", "0");
        const double poplevel = parseScalarValue(poplevelText, model);
        if (!std::isfinite(poplevel) || poplevel < 0.0) {
            throw std::runtime_error("poplevel must be finite and non-negative");
        }
        engine::PsaSimulator simulator(model, network);
        result = simulator.simulate(opts, poplevel);
    } else {
        // ODE/SSA integration
        engine::OdeIntegrator integrator(model, network);
        loadTfunFiles(integrator, model, sourcePath);
        result = integrator.integrate(opts);
    }

    // Save final state for potential continue
    if (!result.concentrations.empty()) {
        lastSimulationState = result.concentrations.back();
        // Update network species amounts to reflect final simulation state.
        // This ensures that continue=1 and setConcentration/addConcentration
        // between phases work correctly without needing to restore from lastSimulationState.
        for (std::size_t i = 0; i < network.species.size() && i < lastSimulationState.size(); ++i) {
            network.species.get(i).setAmount(lastSimulationState[i]);
        }
    }
    // Save end time for potential continue (used as tStart for next phase)
    lastSimulationEndTime = opts.tEnd;

    // Write output files
    const auto prefix = simulationPrefix(action, sourcePath);
    const auto outputPrefix = sourcePath.parent_path() / prefix;
    engine::OdeIntegrator integrator(model, network);
    if (opts.binaryOutput) {
        integrator.writeBinaryOutputFiles(outputPrefix.string(), result, opts.printCDAT);
    } else {
        integrator.writeOutputFiles(outputPrefix.string(), result, opts.printCDAT, opts.printFunctions, continueSimulation);
    }

    if (verbose) {
        if (opts.printCDAT) {
            std::cerr << "[bng_cpp] Wrote " << outputPrefix.string() << ".cdat and "
                      << outputPrefix.string() << ".gdat\n";
        } else {
            std::cerr << "[bng_cpp] Wrote " << outputPrefix.string() << ".gdat (print_CDAT=0)\n";
        }
    }

    // save_progress: write .net checkpoint files at each output step with species concentrations
    if (opts.saveProgress && !result.concentrations.empty()) {
        for (std::size_t step = 0; step < result.timePoints.size(); ++step) {
            // Update network species with concentrations at this time step
            for (std::size_t i = 0; i < network.species.size() && i < result.concentrations[step].size(); ++i) {
                network.species.get(i).setAmount(result.concentrations[step][i]);
            }
            // Write checkpoint .net file: prefix_t{time}.net
            std::ostringstream timeTag;
            timeTag << std::setprecision(15) << result.timePoints[step];
            const auto checkpointPath = sourcePath.parent_path() / (prefix + "_t" + timeTag.str() + ".net");
            io::NetWriter::write(checkpointPath, model, network);
            if (verbose) {
                std::cerr << "[bng_cpp] save_progress: wrote " << checkpointPath.string() << "\n";
            }
        }
        // Restore final state concentrations
        if (!result.concentrations.empty()) {
            for (std::size_t i = 0; i < network.species.size() && i < result.concentrations.back().size(); ++i) {
                network.species.get(i).setAmount(result.concentrations.back()[i]);
            }
        }
    }

    // print_net: write .net file after simulation with final concentrations
    if (opts.printNet && !result.concentrations.empty()) {
        for (std::size_t i = 0; i < network.species.size() && i < result.concentrations.back().size(); ++i) {
            network.species.get(i).setAmount(result.concentrations.back()[i]);
        }
        const auto netPath = sourcePath.parent_path() / (sourcePath.stem().string() + ".net");
        io::NetWriter::write(netPath, model, network);
        if (verbose) {
            std::cerr << "[bng_cpp] print_net: wrote " << netPath.string() << "\n";
        }
    }
}

} // namespace

void ActionDispatch::execute(ast::Model& model, const std::filesystem::path& sourcePath, bool verbose) {
    engine::NetworkGenerator generator(model);
    std::optional<engine::GeneratedNetwork> network;
    std::unordered_map<std::string, std::vector<double>> savedConcentrations;
    std::unordered_map<std::string, std::unordered_map<std::string, double>> savedParameters;

    // For continue simulation: track last simulation state
    std::vector<double> lastSimulationState;
    double lastSimulationEndTime = 0.0;

    // Store loaded .net data for passthrough writing (readFile)
    std::optional<io::NetReader::ParseResult> loadedNetData;

    const auto ensureNetwork = [&]() {
        if (!network.has_value()) {
            network = generator.generate(sourcePath);
        }
    };

    const auto writeNetworkAt = [&](const std::filesystem::path& outputPath,
                                    const io::NetWriterOptions& options = {}) {
        if (loadedNetData.has_value()) {
            // Write loaded .net data with updated species concentrations
            std::ofstream out(outputPath);
            if (!out) throw std::runtime_error("Could not open output file: " + outputPath.string());
            out << "# Created by bng_cpp\n";
            // Parameters
            out << "begin parameters\n";
            std::size_t pidx = 1;
            for (const auto& param : model.getParameters().all()) {
                if (!options.evaluateExpressions) {
                    out << "    " << pidx++ << " " << param.getName() << " " << param.getExpression().toString() << '\n';
                } else {
                    std::ostringstream valStr;
                    valStr << std::setprecision(15) << param.getValue();
                    out << "    " << pidx++ << " " << param.getName() << " " << valStr.str() << '\n';
                }
            }
            out << "end parameters\n";
            // Functions (passthrough from loaded .net)
            if (!loadedNetData->rawFunctionLines.empty()) {
                out << "begin functions\n";
                for (const auto& line : loadedNetData->rawFunctionLines) {
                    out << "    " << line << '\n';
                }
                out << "end functions\n";
            }
            // Species (with updated concentrations from network)
            out << "begin species\n";
            for (std::size_t i = 0; i < network->species.size(); ++i) {
                const auto& sp = network->species.get(i);
                std::string prefix;
                if (sp.isConstant()) prefix = "$";
                out << "    " << (i + 1) << " " << prefix << sp.getSpeciesGraph().toString() << " ";
                // Write concentration - use scientific notation for consistency
                std::ostringstream concStr;
                concStr << std::setprecision(15) << sp.getAmount();
                out << concStr.str() << '\n';
            }
            out << "end species\n";
            // Reactions (passthrough from loaded .net)
            out << "begin reactions\n";
            for (const auto& line : loadedNetData->reactions) {
                out << "    " << line << '\n';
            }
            out << "end reactions\n";
            // Groups (passthrough from loaded .net)
            if (!loadedNetData->rawGroupLines.empty()) {
                out << "begin groups\n";
                for (const auto& line : loadedNetData->rawGroupLines) {
                    out << "    " << line << '\n';
                }
                out << "end groups\n";
            }
            return outputPath;
        }
        io::NetWriter::write(outputPath, model, *network, options);
        return outputPath;
    };

    const auto writeCurrentNetwork = [&](const io::NetWriterOptions& options = {}) {
        return writeNetworkAt(
            sourcePath.parent_path() / (sourcePath.stem().string() + ".net"), options);
    };

    const auto runNfSimulation = [&](const ast::Action& action) {
        const auto prefix = simulationPrefix(action, sourcePath);
        const auto xmlPath = sourcePath.parent_path() / (prefix + ".xml");

        if (parseBoolean(readArgument(action, "continue", "0"))) {
            throw std::runtime_error("NFsim does not support 'continue' option");
        }

        // Parse simulation parameters using the same defaults as the
        // standalone simulate_nf action.
        const auto tEnd = stripQuotes(readArgument(action, "t_end", "10"));
        const auto nSteps = stripQuotes(readArgument(action, "n_steps", "20"));
        const auto gdatPath = sourcePath.parent_path() / (prefix + ".gdat");
        const auto seedText = stripQuotes(readArgument(action, "seed", ""));
        const auto utlText = stripQuotes(readArgument(action, "utl", "3"));
        const auto verboseFlag = lowercase(stripQuotes(readArgument(action, "verbose", "0")));
        const auto complexFlag = lowercase(stripQuotes(readArgument(action, "complex", "1")));
        const auto getFinalState = lowercase(stripQuotes(readArgument(action, "get_final_state", "1")));
        const bool nfVerbose = verboseFlag == "1" || verboseFlag == "true";
        const bool useComplex = complexFlag == "1" || complexFlag == "true";
        const bool evalCSLF = lowercase(stripQuotes(readArgument(action, "nocslf", "0"))) != "1";
        const bool connectivityFlag = lowercase(stripQuotes(readArgument(action, "pcg", "0"))) == "1";

        int globalMoleculeLimit = 200000;
        const auto gmlText = stripQuotes(readArgument(action, "gml", ""));
        if (!gmlText.empty()) {
            globalMoleculeLimit = std::stoi(gmlText);
        }
        int suggestedTraversalLimit = utlText.empty() ? 3 : std::stoi(utlText);

        if (verbose) {
            std::cerr << "[bng_cpp] Running NFSim in-process from AST model\n";
        }

        // Direct construction is the default.  XML remains an explicit
        // compatibility bridge while the direct adapter is being qualified.
        NFcore::System *nfSystem = NFinput::buildSystemFromAst(
            model,
            useComplex,
            globalMoleculeLimit,
            nfVerbose,
            suggestedTraversalLimit,
            sourcePath);

        if (!nfSystem) {
            if (std::getenv("BNG_NFSIM_REQUIRE_DIRECT") != nullptr) {
                throw std::runtime_error(
                    "NFsim direct AST initialization required but unavailable");
            }
            if (verbose) {
                std::cerr << "[bng_cpp] AST adapter returned nullptr; using in-memory XML fallback...\n";
            }
            nfSystem = NFinput::initializeFromModel(
                &model,
                useComplex,
                globalMoleculeLimit,
                nfVerbose,
                suggestedTraversalLimit);
        }

        if (!nfSystem) {
            if (verbose) {
                std::cerr << "[bng_cpp] In-memory XML fallback failed; writing XML fallback...\n";
            }
            const auto xmlContent = io::XmlWriter::write(
                model, network.has_value() ? &(*network) : nullptr);
            std::ofstream xmlOut(xmlPath);
            if (!xmlOut) {
                throw std::runtime_error("Failed to write XML for NFSim: " + xmlPath.string());
            }
            xmlOut << xmlContent;
            if (!xmlOut) {
                throw std::runtime_error("Failed to write XML for NFSim: " + xmlPath.string());
            }
            nfSystem = NFinput::initializeFromXML(
                xmlPath.string(), useComplex, globalMoleculeLimit, nfVerbose,
                suggestedTraversalLimit, evalCSLF, connectivityFlag);
        }

        if (!nfSystem) {
            throw std::runtime_error("NFSim: Failed to initialize system: " + prefix);
        }

        // The legacy initializer applies these switches while reading XML.
        // Apply the same runtime policy to a directly-built System.
        nfSystem->setEvaluateComplexScopedLocalFunctions(evalCSLF);
        nfSystem->useConnectivityFlag(connectivityFlag);
        nfSystem->setUniversalTraversalLimit(suggestedTraversalLimit);

        if (!seedText.empty()) {
            nfSystem->seedRNG(std::stoul(seedText));
        }

        nfSystem->registerOutputFileLocation(gdatPath.string());
        nfSystem->prepareForSimulation();
        nfSystem->sim(std::stod(tEnd), std::stol(nSteps), nfVerbose);

        if (getFinalState == "1" || getFinalState == "true") {
            const auto speciesPath = sourcePath.parent_path() / (prefix + ".species");
            nfSystem->saveSpecies(speciesPath.string());
        }

        if (verbose) {
            std::cerr << "[bng_cpp] NFSim completed. Output: " << gdatPath << "\n";
        }
        delete nfSystem;
    };

    // Execute protocol actions through the same stateful dispatcher used by
    // the standalone simulate_protocol action.  Parameter scans need a
    // per-point prefix, so keeping this as one helper prevents protocol
    // scans from silently taking a different simulation path.
    const auto runProtocol = [&](const std::optional<std::filesystem::path>& prefixOverride) {
        const auto& protocol = model.getSimulationProtocol();
        if (protocol.empty()) {
            throw std::runtime_error("simulate_protocol requires a non-empty protocol block");
        }

        for (const auto& protoAction : protocol) {
            const auto protoName = lowercase(protoAction.name);
            if (protoName == "simulate_nf" ||
                (protoName == "simulate" &&
                 resolveSimulationMethod(protoAction) == "nf")) {
                ast::Action actualAction = protoAction;
                if (prefixOverride.has_value()) {
                    actualAction.arguments["prefix"] = prefixOverride->string();
                    actualAction.arguments.erase("suffix");
                }
                runNfSimulation(actualAction);
                continue;
            }

            if (protoName == "simulate" || protoName == "simulate_ode" ||
                protoName == "simulate_ssa" || protoName == "simulate_pla" ||
                protoName == "simulate_psa") {
                ensureNetwork();
                ast::Action actualAction = protoAction;
                if (protoName == "simulate_pla" || protoName == "simulate_psa") {
                    actualAction.arguments["method"] =
                        protoName == "simulate_pla" ? "pla" : "psa";
                }
                if (prefixOverride.has_value()) {
                    actualAction.arguments["prefix"] = prefixOverride->string();
                    actualAction.arguments.erase("suffix");
                }
                if (!lastSimulationState.empty()) {
                    actualAction.arguments["continue"] = "1";
                }
                runSimulation(model, actualAction, sourcePath, *network, verbose,
                              lastSimulationState, lastSimulationEndTime);
                continue;
            }

            if (protoName == "setparameter") {
                const auto target = stripQuotes(readArgument(protoAction, "target", ""));
                const auto valueText = readArgument(protoAction, "value", "");
                if (target.empty() || trim(valueText).empty()) {
                    throw std::runtime_error(
                        "setParameter in a protocol requires target and value");
                }
                if (!model.getParameters().contains(target)) {
                    throw std::runtime_error("setParameter: unknown parameter: " + target);
                }
                const double value = parseScalarValue(valueText, model);
                model.getParameters().add(
                    ast::Parameter(target, ast::Expression::number(value)));
                model.getParameters().evaluateAll();
                if (network.has_value()) {
                    const auto savedAmounts = snapshotConcentrations(*network);
                    network = generator.generate(sourcePath);
                    restoreConcentrations(*network, savedAmounts);
                }
                continue;
            }

            if (protoName == "setconcentration" || protoName == "addconcentration" ||
                protoName == "add_concentration") {
                ensureNetwork();
                const auto target = readArgument(protoAction, "target", "");
                const auto valueText = readArgument(protoAction, "value", "");
                if (trim(target).empty() || trim(valueText).empty()) {
                    throw std::runtime_error(
                        protoName == "setconcentration"
                            ? "setConcentration in a protocol requires target and value"
                            : "addConcentration in a protocol requires target and value");
                }
                const auto found = findSpeciesIndex(*network, target);
                if (!found.has_value()) {
                    throw std::runtime_error(
                        "Protocol concentration target species not found: " +
                        stripQuotes(target));
                }
                const double value = parseScalarValue(valueText, model);
                if (protoName == "setconcentration") {
                    network->species.get(*found).setAmount(value);
                } else {
                    network->species.get(*found).setAmount(
                        network->species.get(*found).getAmount() + value);
                }
                continue;
            }

            if (protoName == "saveparameters" || protoName == "save_parameters") {
                const auto label = stripQuotes(readArgument(protoAction, "value", "default"));
                std::unordered_map<std::string, double> snapshot;
                for (const auto& param : model.getParameters().all()) {
                    snapshot[param.getName()] = param.getValue();
                }
                savedParameters[label] = std::move(snapshot);
                continue;
            }

            if (protoName == "resetparameters" || protoName == "reset_parameters") {
                const auto label = stripQuotes(readArgument(protoAction, "value", "default"));
                const auto found = savedParameters.find(label);
                if (found == savedParameters.end()) {
                    throw std::runtime_error("resetParameters label not found: " + label);
                }
                for (const auto& [name, value] : found->second) {
                    model.getParameters().add(
                        ast::Parameter(name, ast::Expression::number(value)));
                }
                model.getParameters().evaluateAll();
                if (network.has_value()) {
                    const auto savedAmounts = snapshotConcentrations(*network);
                    network = generator.generate(sourcePath);
                    restoreConcentrations(*network, savedAmounts);
                }
                continue;
            }

            if (protoName == "saveconcentrations" || protoName == "save_concentrations") {
                ensureNetwork();
                const auto label = stripQuotes(readArgument(protoAction, "value", "default"));
                savedConcentrations[label] = snapshotConcentrations(*network);
                continue;
            }

            if (protoName == "resetconcentrations" || protoName == "reset_concentrations") {
                ensureNetwork();
                const auto label = stripQuotes(readArgument(protoAction, "value", "default"));
                const auto found = savedConcentrations.find(label);
                if (found != savedConcentrations.end()) {
                    restoreConcentrations(*network, found->second);
                } else if (label != "default") {
                    throw std::runtime_error("resetConcentrations label not found: " + label);
                } else {
                    const auto& seeds = model.getSeedSpecies();
                    for (std::size_t i = 0; i < network->species.size(); ++i) {
                        if (i < seeds.size()) {
                            try {
                                network->species.get(i).setAmount(
                                    seeds[i].getAmount().evaluate([&](const std::string& name) {
                                        return model.getParameters().evaluate(name);
                                    }));
                            } catch (const std::exception& error) {
                                throw std::runtime_error(
                                    "resetConcentrations could not evaluate seed species "
                                    + std::to_string(i + 1) + ": " + error.what());
                            }
                        } else {
                            network->species.get(i).setAmount(0.0);
                        }
                    }
                }
                continue;
            }

            throw std::runtime_error(
                "Unsupported action in protocol: " + protoAction.name);
        }
    };

    for (const auto& action : model.getActions()) {
        // Normalize action name to lowercase for case-insensitive matching
        std::string actionName = lowercase(action.name);

        // BNG2 exposes readNetwork and readModel as aliases for readFile.
        // Normalize here too so programmatically constructed actions get the
        // same semantics as parsed BNGL sources.
        if (actionName == "readnetwork" || actionName == "readmodel") {
            actionName = "readfile";
        }

        if (actionName == "readfile") {
            const auto filepath = stripQuotes(readArgument(action, "file", ""));
            if (filepath.empty()) {
                throw std::runtime_error("readFile requires 'file' argument");
            }

            // Determine file type
            std::filesystem::path path(filepath);
            if (!path.is_absolute()) {
                path = sourcePath.parent_path() / filepath;
            }

            const auto extension = lowercase(path.extension().string());
            if (extension == ".net") {
                // Parse .net file
                auto parseResult = io::NetReader::parse(path);
                if (!parseResult.success) {
                    throw std::runtime_error("Failed to read .net file: " + parseResult.error);
                }

                // Merge parsed parameters into current model
                for (const auto& [name, value] : parseResult.parameters) {
                    model.getParameters().add(ast::Parameter(name, ast::Expression::number(value)));
                }
                model.getParameters().evaluateAll();

                // Reconstruct network from parsed species and reactions
                engine::GeneratedNetwork loadedNetwork;
                for (const auto& [pattern, concStr] : parseResult.species) {
                    // Check for constant species ($ prefix)
                    bool isConstant = false;
                    std::string cleanPattern = pattern;
                    if (!cleanPattern.empty() && cleanPattern[0] == '$') {
                        isConstant = true;
                        cleanPattern = cleanPattern.substr(1);
                    }
                    // Create a PatternGraph with raw string (no full graph construction needed)
                    BNGcore::PatternGraph pg;
                    pg.set_raw_string(cleanPattern);
                    ast::SpeciesGraph sg(std::move(pg));
                    // Resolve concentration: can be a number or a parameter name
                    double concentration = 0.0;
                    try {
                        concentration = std::stod(concStr);
                    } catch (...) {
                        // Try resolving as parameter name
                        try {
                            concentration = model.getParameters().evaluate(concStr);
                        } catch (...) {
                            concentration = 0.0;
                        }
                    }
                    ast::Species sp(std::move(sg), concentration, isConstant);
                    loadedNetwork.species.add(std::move(sp));
                }

                // Store reactions as-is (raw lines for passthrough writing)
                // Also create Rxn objects for ODE integration
                for (const auto& rxnLine : parseResult.reactions) {
                    // Parse reaction line: <index> <reactants> <products> <rate>
                    std::istringstream iss(rxnLine);
                    std::string idxStr, reactantsStr, productsStr, rateStr;
                    iss >> idxStr >> reactantsStr >> productsStr;
                    std::getline(iss, rateStr);
                    // Trim leading whitespace from rate
                    auto rateStart = rateStr.find_first_not_of(" \t");
                    if (rateStart != std::string::npos) rateStr = rateStr.substr(rateStart);
                    // Strip #comment from rate
                    auto commentPos = rateStr.find('#');
                    if (commentPos != std::string::npos) rateStr = rateStr.substr(0, commentPos);
                    // Trim trailing whitespace
                    while (!rateStr.empty() && std::isspace(rateStr.back())) rateStr.pop_back();

                    // Parse reactant indices (comma-separated, 1-based)
                    std::vector<std::size_t> reactants;
                    if (reactantsStr != "0") {
                        std::istringstream rss(reactantsStr);
                        std::string tok;
                        while (std::getline(rss, tok, ',')) {
                            reactants.push_back(std::stoul(tok) - 1);
                        }
                    }
                    // Parse product indices
                    std::vector<std::size_t> products;
                    if (productsStr != "0") {
                        std::istringstream pss(productsStr);
                        std::string tok;
                        while (std::getline(pss, tok, ',')) {
                            products.push_back(std::stoul(tok) - 1);
                        }
                    }

                    loadedNetwork.reactions.add(ast::Rxn(
                        idxStr, reactants, products, rateStr));
                }

                network = std::move(loadedNetwork);
                loadedNetData = std::move(parseResult);

                if (verbose) {
                    std::cerr << "[bng_cpp] Read .net file: " << path << "\n";
                    std::cerr << "[bng_cpp]   Parameters: " << loadedNetData->parameters.size() << "\n";
                    std::cerr << "[bng_cpp]   Species: " << network->species.size() << "\n";
                    std::cerr << "[bng_cpp]   Reactions: " << network->reactions.size() << "\n";
                }
            } else if (extension == ".bngl") {
                auto includedModel = bng::parser::parseModelFromFile(path.string());
                model.merge(*includedModel);
                model.getParameters().evaluateAll();
                if (verbose) {
                    std::cerr << "[bng_cpp] Read .bngl file: " << path << "\n";
                    std::cerr << "[bng_cpp]   Parameters: " << includedModel->getParameters().size() << "\n";
                    std::cerr << "[bng_cpp]   Molecule types: " << includedModel->getMoleculeTypes().size() << "\n";
                    std::cerr << "[bng_cpp]   Seed species: " << includedModel->getSeedSpecies().size() << "\n";
                    std::cerr << "[bng_cpp]   Observables: " << includedModel->getObservables().size() << "\n";
                    std::cerr << "[bng_cpp]   Reaction rules: " << includedModel->getReactionRules().size() << "\n";
                    std::cerr << "[bng_cpp]   Functions: " << includedModel->getFunctions().size() << "\n";
                }
            } else if (extension == ".xml") {
                const auto atomizeText = lowercase(
                    trim(stripQuotes(readArgument(action, "atomize", "0"))));
                const bool atomize = atomizeText == "1" || atomizeText == "true" ||
                    atomizeText == "yes" || atomizeText == "on";
                auto parseResult = io::SbmlReader::parse(path, atomize);
                if (!parseResult.success) {
                    throw std::runtime_error(
                        "Failed to read SBML file: " + parseResult.error);
                }
                for (const auto& [name, value] : parseResult.parameters) {
                    model.getParameters().add(
                        ast::Parameter(name, ast::Expression::number(value)));
                }
                for (const auto& [name, expression] : parseResult.functions) {
                    model.addFunction(ast::Function(
                        name, {}, bng::parser::parseExpression(expression)));
                }
                model.getParameters().evaluateAll();
                network = networkFromParsedData(parseResult, model);
                loadedNetData = std::move(parseResult);
                if (verbose) {
                    std::cerr << "[bng_cpp] Read flat SBML file: " << path << "\n";
                    std::cerr << "[bng_cpp]   Parameters: "
                              << loadedNetData->parameters.size() << "\n";
                    std::cerr << "[bng_cpp]   Species: " << network->species.size() << "\n";
                    std::cerr << "[bng_cpp]   Reactions: " << network->reactions.size() << "\n";
                }
            } else {
                throw std::runtime_error("readFile: unsupported file type: " + path.extension().string());
            }

            continue;
        }

        if (actionName == "include_model") {
            const auto filepath = stripQuotes(readArgument(action, "file",
                stripQuotes(readArgument(action, "value", ""))));
            if (filepath.empty()) {
                throw std::runtime_error("include_model requires a 'file' argument");
            }
            std::filesystem::path incPath(filepath);
            if (!incPath.is_absolute()) {
                incPath = sourcePath.parent_path() / filepath;
            }
            auto includedModel = bng::parser::parseModelFromFile(incPath.string());
            model.merge(*includedModel);
            model.getParameters().evaluateAll();
            if (verbose) {
                std::cerr << "[bng_cpp] include_model: " << incPath << "\n";
                std::cerr << "[bng_cpp]   Merged parameters: " << includedModel->getParameters().size()
                          << ", molecule types: " << includedModel->getMoleculeTypes().size()
                          << ", seed species: " << includedModel->getSeedSpecies().size()
                          << ", observables: " << includedModel->getObservables().size()
                          << ", rules: " << includedModel->getReactionRules().size()
                          << ", functions: " << includedModel->getFunctions().size() << "\n";
            }
            continue;
        }

        if (actionName == "include_network") {
            const auto filepath = stripQuotes(readArgument(action, "file",
                stripQuotes(readArgument(action, "value", ""))));
            if (filepath.empty()) {
                throw std::runtime_error("include_network requires a 'file' argument");
            }
            std::filesystem::path incPath(filepath);
            if (!incPath.is_absolute()) {
                incPath = sourcePath.parent_path() / filepath;
            }
            auto parseResult = io::NetReader::parse(incPath);
            if (!parseResult.success) {
                throw std::runtime_error("Failed to read .net file for include_network: " + parseResult.error);
            }
            for (const auto& [name, value] : parseResult.parameters) {
                model.getParameters().add(ast::Parameter(name, ast::Expression::number(value)));
            }
            model.getParameters().evaluateAll();
            engine::GeneratedNetwork loadedNetwork;
            for (const auto& [pattern, concStr] : parseResult.species) {
                bool isConstant = false;
                std::string cleanPattern = pattern;
                if (!cleanPattern.empty() && cleanPattern[0] == '$') {
                    isConstant = true;
                    cleanPattern = cleanPattern.substr(1);
                }
                BNGcore::PatternGraph pg;
                pg.set_raw_string(cleanPattern);
                ast::SpeciesGraph sg(std::move(pg));
                double concentration = 0.0;
                try { concentration = std::stod(concStr); }
                catch (...) {
                    try { concentration = model.getParameters().evaluate(concStr); }
                    catch (...) { concentration = 0.0; }
                }
                ast::Species sp(std::move(sg), concentration, isConstant);
                loadedNetwork.species.add(std::move(sp));
            }
            for (const auto& rxnLine : parseResult.reactions) {
                std::istringstream iss(rxnLine);
                std::string idxStr, reactantsStr, productsStr, rateStr;
                iss >> idxStr >> reactantsStr >> productsStr;
                std::getline(iss, rateStr);
                auto rateStart = rateStr.find_first_not_of(" \t");
                if (rateStart != std::string::npos) rateStr = rateStr.substr(rateStart);
                auto commentPos = rateStr.find('#');
                if (commentPos != std::string::npos) rateStr = rateStr.substr(0, commentPos);
                while (!rateStr.empty() && std::isspace(rateStr.back())) rateStr.pop_back();
                std::vector<std::size_t> reactants;
                if (reactantsStr != "0") {
                    std::istringstream rss(reactantsStr);
                    std::string tok;
                    while (std::getline(rss, tok, ',')) reactants.push_back(std::stoul(tok) - 1);
                }
                std::vector<std::size_t> products;
                if (productsStr != "0") {
                    std::istringstream pss(productsStr);
                    std::string tok;
                    while (std::getline(pss, tok, ',')) products.push_back(std::stoul(tok) - 1);
                }
                loadedNetwork.reactions.add(ast::Rxn(idxStr, reactants, products, rateStr));
            }
            network = std::move(loadedNetwork);
            loadedNetData = std::move(parseResult);
            if (verbose) {
                std::cerr << "[bng_cpp] include_network: " << incPath << "\n";
                std::cerr << "[bng_cpp]   Parameters: " << loadedNetData->parameters.size() << "\n";
                std::cerr << "[bng_cpp]   Species: " << network->species.size() << "\n";
                std::cerr << "[bng_cpp]   Reactions: " << network->reactions.size() << "\n";
            }
            continue;
        }

        if (actionName == "generate_network") {
            // Parse overwrite option (default: true = always regenerate)
            const auto overwriteText = readArgument(action, "overwrite", "1");
            bool overwrite = true;
            {
                std::string ov = lowercase(trim(stripQuotes(overwriteText)));
                overwrite = (ov == "1" || ov == "true" || ov == "yes" || ov == "on");
            }

            if (!overwrite) {
                // Check if .net file already exists; if so, read it instead of regenerating
                auto netPath = sourcePath.parent_path() / (sourcePath.stem().string() + ".net");
                if (std::filesystem::exists(netPath)) {
                    auto parseResult = io::NetReader::parse(netPath);
                    if (parseResult.success) {
                        // Merge parsed parameters into current model
                        for (const auto& [name, value] : parseResult.parameters) {
                            model.getParameters().add(ast::Parameter(name, ast::Expression::number(value)));
                        }
                        model.getParameters().evaluateAll();

                        // Reconstruct network from parsed species and reactions
                        engine::GeneratedNetwork loadedNetwork;
                        for (const auto& [pattern, concStr] : parseResult.species) {
                            bool isConstant = false;
                            std::string cleanPattern = pattern;
                            if (!cleanPattern.empty() && cleanPattern[0] == '$') {
                                isConstant = true;
                                cleanPattern = cleanPattern.substr(1);
                            }
                            BNGcore::PatternGraph pg;
                            pg.set_raw_string(cleanPattern);
                            ast::SpeciesGraph sg(std::move(pg));
                            double concentration = 0.0;
                            try {
                                concentration = std::stod(concStr);
                            } catch (...) {
                                try {
                                    concentration = model.getParameters().evaluate(concStr);
                                } catch (...) {
                                    concentration = 0.0;
                                }
                            }
                            ast::Species sp(std::move(sg), concentration, isConstant);
                            loadedNetwork.species.add(std::move(sp));
                        }

                        for (const auto& rxnLine : parseResult.reactions) {
                            std::istringstream iss(rxnLine);
                            std::string idxStr, reactantsStr, productsStr, rateStr;
                            iss >> idxStr >> reactantsStr >> productsStr;
                            std::getline(iss, rateStr);
                            auto rateStart = rateStr.find_first_not_of(" \t");
                            if (rateStart != std::string::npos) rateStr = rateStr.substr(rateStart);
                            auto commentPos = rateStr.find('#');
                            if (commentPos != std::string::npos) rateStr = rateStr.substr(0, commentPos);
                            while (!rateStr.empty() && std::isspace(rateStr.back())) rateStr.pop_back();

                            std::vector<std::size_t> reactants;
                            if (reactantsStr != "0") {
                                std::istringstream rss(reactantsStr);
                                std::string tok;
                                while (std::getline(rss, tok, ',')) {
                                    reactants.push_back(std::stoul(tok) - 1);
                                }
                            }
                            std::vector<std::size_t> products;
                            if (productsStr != "0") {
                                std::istringstream pss(productsStr);
                                std::string tok;
                                while (std::getline(pss, tok, ',')) {
                                    products.push_back(std::stoul(tok) - 1);
                                }
                            }

                            loadedNetwork.reactions.add(ast::Rxn(
                                idxStr, reactants, products, rateStr));
                        }

                        network = std::move(loadedNetwork);
                        loadedNetData = std::move(parseResult);

                        if (verbose) {
                            std::cerr << "[bng_cpp] Loaded existing .net file (overwrite=0): " << netPath << "\n";
                            std::cerr << "[bng_cpp]   Species: " << network->species.size() << "\n";
                            std::cerr << "[bng_cpp]   Reactions: " << network->reactions.size() << "\n";
                        }
                        continue;
                    }
                    // If parse failed, fall through to regeneration
                }
            }

            const auto evalExprText = readArgument(action, "evaluate_expressions", "1");
            bool evalExpr = true;
            {
                std::string ee = lowercase(trim(stripQuotes(evalExprText)));
                evalExpr = (ee == "1" || ee == "true" || ee == "yes" || ee == "on");
            }
            io::NetWriterOptions writerOptions;
            writerOptions.evaluateExpressions = evalExpr;
            if (loadedNetData.has_value() && network.has_value()) {
                // readFile(.net/.xml) already supplied a concrete network.  Keep
                // that network when the following generate_network action is
                // explicitly requested with overwrite=1; regenerating from the
                // action-only model would silently discard the imported graph.
                writeCurrentNetwork(writerOptions);
                continue;
            }
            network = generator.generate(sourcePath);
            writeCurrentNetwork(writerOptions);  // Triggers NetWriter::buildDerivedRateParams
            continue;
        }

        if (actionName == "setparameter") {
            const auto target = stripQuotes(readArgument(action, "target", ""));
            const auto valueText = readArgument(action, "value", "");
            if (target.empty()) {
                throw std::runtime_error("setParameter requires a target parameter name");
            }

            const double value = parseScalarValue(valueText, model);
            model.getParameters().add(ast::Parameter(target, ast::Expression::number(value)));
            model.getParameters().evaluateAll();

            if (network.has_value()) {
                // Preserve species amounts before regeneration so that
                // a subsequent continue=>1 simulation starts from the
                // correct state rather than the initial seed species amounts.
                std::vector<double> savedAmounts;
                if (!lastSimulationState.empty()) {
                    savedAmounts = lastSimulationState;
                }

                network = generator.generate(sourcePath);

                // Restore species amounts from the previous simulation state.
                // Parameter changes affect rate constants but should not reset
                // species concentrations that evolved during prior simulation.
                if (!savedAmounts.empty()) {
                    for (std::size_t i = 0; i < network->species.size() && i < savedAmounts.size(); ++i) {
                        network->species.get(i).setAmount(savedAmounts[i]);
                    }
                }
            }
            continue;
        }

        if (actionName == "setmodelname") {
            const auto value = stripQuotes(readArgument(action, "value", ""));
            if (value.empty()) {
                throw std::runtime_error("setModelName requires a 'value' argument");
            }
            model.setModelName(value);
            if (verbose) {
                std::cerr << "[bng_cpp] Set model name to '" << value << "'\n";
            }
            continue;
        }

        if (actionName == "setoption") {
            // setOption("option_name","value") — sets model-level options
            // Arguments can come as positional (target/value) or from the
            // parser's key=>value map.  The parser stores the first quoted
            // string argument under "target" and the second under "value".
            const auto optionName = stripQuotes(readArgument(action, "target",
                stripQuotes(readArgument(action, "option", ""))));
            const auto optionValue = stripQuotes(readArgument(action, "value", ""));
            if (optionName.empty()) {
                throw std::runtime_error("setOption requires an option name");
            }
            model.setOption(optionName, optionValue);
            if (verbose) {
                std::cerr << "[bng_cpp] setOption(\"" << optionName << "\",\"" << optionValue << "\")\n";
            }
            continue;
        }

        if (actionName == "substanceunits") {
            // substanceUnits("Concentration") or substanceUnits("Number")
            const auto value = stripQuotes(readArgument(action, "value",
                stripQuotes(readArgument(action, "target", ""))));
            if (!value.empty()) {
                model.setOption("substanceUnits", value);
                if (verbose) {
                    std::cerr << "[bng_cpp] substanceUnits set to '" << value << "'\n";
                }
            }
            continue;
        }

        if (actionName == "quit") {
            // quit() — stop processing further actions (BNG2 interpreter exit)
            if (verbose) {
                std::cerr << "[bng_cpp] quit() — stopping action processing\n";
            }
            return;
        }

        if (actionName == "setvolume") {
            const auto target = stripQuotes(readArgument(action, "target", ""));
            const auto valueText = readArgument(action, "value", "");
            if (target.empty()) {
                throw std::runtime_error("setVolume requires a 'target' compartment name");
            }
            const double value = parseScalarValue(valueText, model);
            bool found = false;
            for (auto& comp : model.getCompartments()) {
                if (comp.getName() == target) {
                    comp.setVolume(value);
                    found = true;
                    break;
                }
            }
            if (!found) {
                throw std::runtime_error("setVolume: compartment not found: " + target);
            }
            // Regenerate network if one exists, since volume affects rate constants
            if (network.has_value()) {
                std::vector<double> savedAmounts;
                if (!lastSimulationState.empty()) {
                    savedAmounts = lastSimulationState;
                }
                network = generator.generate(sourcePath);
                if (!savedAmounts.empty()) {
                    for (std::size_t i = 0; i < network->species.size() && i < savedAmounts.size(); ++i) {
                        network->species.get(i).setAmount(savedAmounts[i]);
                    }
                }
            }
            if (verbose) {
                std::cerr << "[bng_cpp] Set volume of compartment '" << target << "' to " << value << "\n";
            }
            continue;
        }

        if (actionName == "saveparameters") {
            const auto label = stripQuotes(readArgument(action, "value", "default"));
            std::unordered_map<std::string, double> snapshot;
            for (const auto& param : model.getParameters().all()) {
                snapshot[param.getName()] = param.getValue();
            }
            savedParameters[label] = snapshot;
            if (verbose) {
                std::cerr << "[bng_cpp] Saved parameters with label '" << label << "'\n";
            }
            continue;
        }

        if (actionName == "resetparameters") {
            const auto label = stripQuotes(readArgument(action, "value", "default"));
            const auto found = savedParameters.find(label);
            if (found == savedParameters.end()) {
                throw std::runtime_error("resetParameters label not found: " + label);
            }
            for (const auto& [name, value] : found->second) {
                model.getParameters().add(ast::Parameter(name, ast::Expression::number(value)));
            }
            model.getParameters().evaluateAll();
            if (network.has_value()) {
                std::vector<double> savedAmounts;
                if (!lastSimulationState.empty()) {
                    savedAmounts = lastSimulationState;
                }
                network = generator.generate(sourcePath);
                if (!savedAmounts.empty()) {
                    for (std::size_t i = 0; i < network->species.size() && i < savedAmounts.size(); ++i) {
                        network->species.get(i).setAmount(savedAmounts[i]);
                    }
                }
            }
            if (verbose) {
                std::cerr << "[bng_cpp] Reset parameters from label '" << label << "'\n";
            }
            continue;
        }

        if (actionName == "setconcentration") {
            ensureNetwork();
            const auto target = readArgument(action, "target", "");
            const auto valueText = readArgument(action, "value", "");
            const double value = parseScalarValue(valueText, model);
            const auto found = findSpeciesIndex(*network, target);
            if (!found.has_value()) {
                throw std::runtime_error("setConcentration target species not found: " + stripQuotes(target));
            }
            network->species.get(*found).setAmount(value);
            writeCurrentNetwork();
            continue;
        }

        if (actionName == "saveconcentrations") {
            ensureNetwork();
            const auto label = stripQuotes(readArgument(action, "value", "default"));
            savedConcentrations[label] = snapshotConcentrations(*network);
            continue;
        }

        if (actionName == "resetconcentrations") {
            ensureNetwork();
            const auto label = stripQuotes(readArgument(action, "value", "default"));
            const auto found = savedConcentrations.find(label);
            if (found != savedConcentrations.end()) {
                restoreConcentrations(*network, found->second);
            } else {
                // Perl BNG2 behavior: reset to initial seed species concentrations
                const auto& seeds = model.getSeedSpecies();
                for (std::size_t i = 0; i < network->species.size(); ++i) {
                    if (i < seeds.size()) {
                        try {
                            const double amount = seeds[i].getAmount().evaluate(
                                [&](const std::string& name) { return model.getParameters().evaluate(name); });
                            network->species.get(i).setAmount(amount);
                        } catch (...) {
                            network->species.get(i).setAmount(0.0);
                        }
                    } else {
                        network->species.get(i).setAmount(0.0);
                    }
                }
            }
            writeCurrentNetwork();
            continue;
        }

        if (actionName == "addconcentration") {
            ensureNetwork();
            const auto target = readArgument(action, "target", "");
            const auto valueText = readArgument(action, "value", "");
            const double value = parseScalarValue(valueText, model);
            const auto found = findSpeciesIndex(*network, target);
            if (!found.has_value()) {
                throw std::runtime_error("addConcentration target species not found: " + stripQuotes(target));
            }
            network->species.get(*found).setAmount(network->species.get(*found).getAmount() + value);
            writeCurrentNetwork();
            continue;
        }

        if (actionName == "simulate_pla") {
            ensureNetwork();
            const auto tEnd = stripQuotes(readArgument(action, "t_end", ""));
            const auto nSteps = stripQuotes(readArgument(action, "n_steps", stripQuotes(readArgument(action, "n_output_steps", ""))));
            if (tEnd.empty() || nSteps.empty()) {
                throw std::runtime_error("simulate_pla requires t_end and n_steps");
            }

            engine::OdeOptions opts;
            opts.tEnd = parseScalarValue(tEnd, model);
            opts.nSteps = static_cast<std::size_t>(parseScalarValue(nSteps, model));
            opts.method = "pla";

            const auto seedText = readArgument(action, "seed", "");
            if (!seedText.empty()) {
                opts.seed = static_cast<unsigned int>(parseScalarValue(seedText, model));
            }

            // Parse PLA config
            const auto plaConfigStr = stripQuotes(readArgument(action, "pla_config", "fEuler|pre-neg:sb|eps=0.03"));
            auto plaConfig = engine::PlaConfig::parse(plaConfigStr);

            if (verbose) {
                std::cerr << "[bng_cpp] Simulating PLA with config: " << plaConfigStr
                          << " t_end=" << opts.tEnd << " n_steps=" << opts.nSteps << "\n";
            }

            // Run PLA simulation
            engine::PlaSimulator simulator(model, *network);
            auto result = simulator.simulate(opts, plaConfig);

            // Write output files using OdeIntegrator's writer
            const auto prefix = simulationPrefix(action, sourcePath);
            const auto outputPrefix = sourcePath.parent_path() / prefix;
            engine::OdeIntegrator integrator(model, *network);
            integrator.writeOutputFiles(outputPrefix.string(), result);

            if (verbose) {
                std::cerr << "[bng_cpp] Wrote PLA output: " << outputPrefix.string() << ".cdat, .gdat\n";
            }
            continue;
        }

        if (actionName == "simulate_psa") {
            ensureNetwork();
            const auto tEnd = stripQuotes(readArgument(action, "t_end", ""));
            const auto nSteps = stripQuotes(readArgument(action, "n_steps", stripQuotes(readArgument(action, "n_output_steps", ""))));
            if (tEnd.empty() || nSteps.empty()) {
                throw std::runtime_error("simulate_psa requires t_end and n_steps");
            }

            engine::OdeOptions opts;
            opts.tEnd = parseScalarValue(tEnd, model);
            opts.nSteps = static_cast<std::size_t>(parseScalarValue(nSteps, model));

            const auto seedText = readArgument(action, "seed", "");
            if (!seedText.empty()) {
                opts.seed = static_cast<unsigned int>(parseScalarValue(seedText, model));
            }

            // Parse poplevel: threshold for population (ODE) vs particle (SSA)
            // Default 0 means pure SSA
            double poplevel = 0.0;
            const auto poplevelText = readArgument(action, "poplevel", "");
            if (!poplevelText.empty()) {
                poplevel = parseScalarValue(poplevelText, model);
            }

            if (verbose) {
                std::cerr << "[bng_cpp] Simulating PSA (hybrid particle/population) with"
                          << " poplevel=" << poplevel
                          << " t_end=" << opts.tEnd << " n_steps=" << opts.nSteps << "\n";
            }

            // Run PSA simulation
            engine::PsaSimulator simulator(model, *network);
            auto result = simulator.simulate(opts, poplevel);

            // Write output files
            const auto prefix = simulationPrefix(action, sourcePath);
            const auto outputPrefix = sourcePath.parent_path() / prefix;
            engine::OdeIntegrator integrator(model, *network);
            integrator.writeOutputFiles(outputPrefix.string(), result);

            if (verbose) {
                std::cerr << "[bng_cpp] Wrote PSA output: " << outputPrefix.string() << ".cdat, .gdat\n";
            }
            continue;
        }

        if (actionName == "simulate_nf" ||
            (actionName == "simulate" && resolveSimulationMethod(action) == "nf")) {
            runNfSimulation(action);
            continue;
        }

        if (actionName == "simulate" || action.name == "simulate_ode" || action.name == "simulate_ssa") {
            ensureNetwork();
            // Don't re-write .net file - already written by generate_network
            // Re-writing would cause duplicate parameters and corrupt stat factors
            runSimulation(model, action, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
            continue;
        }

        if (actionName == "parameter_scan") {
            const auto parameterName = stripQuotes(readArgument(action, "parameter", ""));
            if (parameterName.empty()) {
                throw std::runtime_error("parameter_scan requires parameter argument");
            }

            if (!model.getParameters().contains(parameterName)) {
                throw std::runtime_error("parameter_scan: unknown parameter: " + parameterName);
            }

            const auto minText = readArgument(action, "par_min", "");
            const auto maxText = readArgument(action, "par_max", "");
            const auto pointsText = readArgument(action, "n_scan_pts", "");
            const bool hasMin = !trim(stripQuotes(minText)).empty();
            const bool hasMax = !trim(stripQuotes(maxText)).empty();
            const bool hasPoints = !trim(stripQuotes(pointsText)).empty();
            const auto explicitValuesText = readArgument(
                action, "par_scan_vals", readArgument(action, "values", ""));
            const bool hasExplicitValues =
                !trim(stripQuotes(explicitValuesText)).empty();

            // BNG2 gives min/max/n_scan_pts precedence over an explicit list.
            std::vector<double> scanValues;
            if (hasMin || hasMax || hasPoints) {
                if (!hasMin || !hasMax || !hasPoints) {
                    throw std::runtime_error(
                        "parameter_scan requires par_min, par_max, and n_scan_pts "
                        "together");
                }
                const double minValue = parseScalarValue(minText, model);
                const double maxValue = parseScalarValue(maxText, model);
                const auto points = parseNonNegativeCount(
                    pointsText, model, "n_scan_pts");
                if (minValue == maxValue) {
                    if (points < 1) {
                        throw std::runtime_error(
                            "n_scan_pts must be at least one when par_min equals par_max");
                    }
                } else if (points <= 1) {
                    throw std::runtime_error(
                        "n_scan_pts must be greater than one when par_min differs from par_max");
                }
                const bool logScale = parseBoolean(
                    readArgument(action, "log_scale", "0"));
                if (logScale && (minValue <= 0.0 || maxValue <= 0.0)) {
                    throw std::runtime_error(
                        "parameter_scan with log_scale requires positive par_min and par_max");
                }
                scanValues.reserve(points);
                for (std::size_t i = 0; i < points; ++i) {
                    const double alpha = points == 1
                        ? 0.0
                        : static_cast<double>(i) / static_cast<double>(points - 1);
                    if (logScale) {
                        scanValues.push_back(std::exp(
                            std::log(minValue) +
                            alpha * (std::log(maxValue) - std::log(minValue))));
                    } else {
                        scanValues.push_back(
                            minValue + alpha * (maxValue - minValue));
                    }
                }
            } else if (hasExplicitValues) {
                scanValues = parseScalarList(
                    explicitValuesText, model, "par_scan_vals");
            } else {
                throw std::runtime_error(
                    "parameter_scan requires par_scan_vals or par_min, par_max, and n_scan_pts");
            }

            const auto method = lowercase(stripQuotes(
                readArgument(action, "method", "ode")));
            const bool nfScan = method == "nf";
            const auto parallelText = readArgument(action, "parallel", "");
            if (!trim(stripQuotes(parallelText)).empty() &&
                parseNonNegativeCount(parallelText, model, "parallel") > 0) {
                throw std::runtime_error(
                    "parameter_scan parallel execution is not implemented");
            }
            const bool resetConcentrations = parseBoolean(
                readArgument(action, "reset_conc", "1"), true);

            ensureNetwork();
            const auto scanInitialConcentrations = snapshotConcentrations(*network);
            const auto originalLastState = lastSimulationState;
            const double originalLastEndTime = lastSimulationEndTime;
            std::vector<ast::Parameter> originalParameters;
            for (const auto& parameter : model.getParameters().all()) {
                originalParameters.push_back(parameter);
            }
            const auto savedConcentrationsBeforeScan = savedConcentrations;
            const auto savedParametersBeforeScan = savedParameters;

            std::filesystem::path scanBase = stripQuotes(
                readArgument(action, "prefix", sourcePath.stem().string()));
            if (!scanBase.is_absolute()) {
                scanBase = sourcePath.parent_path() / scanBase;
            }
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            if (!suffix.empty()) {
                scanBase += "_" + suffix;
            } else {
                scanBase += "_" + parameterName;
            }
            const auto workdir = scanBase;
            std::filesystem::create_directories(workdir);
            const auto localStem = scanBase.filename().string();

            const auto restoreScanContext = [&]() {
                for (const auto& parameter : originalParameters) {
                    model.getParameters().add(parameter);
                }
                model.getParameters().evaluateAll();
                network = generator.generate(sourcePath);
                restoreConcentrations(*network, scanInitialConcentrations);
                lastSimulationState = originalLastState;
                lastSimulationEndTime = originalLastEndTime;
                savedConcentrations = savedConcentrationsBeforeScan;
                savedParameters = savedParametersBeforeScan;
            };

            std::vector<ScanData> scanData;
            try {
                if (method == "protocol" && model.getSimulationProtocol().empty()) {
                    throw std::runtime_error(
                        "parameter_scan method='protocol' requires a protocol block");
                }
                for (std::size_t i = 0; i < scanValues.size(); ++i) {
                    const auto priorConcentrations = snapshotConcentrations(*network);
                    model.getParameters().add(ast::Parameter(
                        parameterName, ast::Expression::number(scanValues[i])));
                    model.getParameters().evaluateAll();
                    network = generator.generate(sourcePath);
                    restoreConcentrations(
                        *network,
                        resetConcentrations ? scanInitialConcentrations
                                            : priorConcentrations);
                    lastSimulationState.clear();
                    lastSimulationEndTime = 0.0;
                    savedConcentrations.clear();
                    savedParameters.clear();

                    std::ostringstream localName;
                    localName << localStem << "_" << std::setfill('0')
                              << std::setw(5) << (i + 1);
                    const auto localPrefix = workdir / localName.str();
                    if (method == "protocol") {
                        runProtocol(localPrefix);
                    } else if (nfScan) {
                        ast::Action nfAction = action;
                        nfAction.name = "simulate_nf";
                        nfAction.arguments["prefix"] = localPrefix.string();
                        nfAction.arguments.erase("suffix");
                        runNfSimulation(nfAction);
                    } else {
                        ast::Action simulateAction = action;
                        simulateAction.name = "simulate";
                        simulateAction.arguments["prefix"] = localPrefix.string();
                        simulateAction.arguments.erase("suffix");
                        runSimulation(model, simulateAction, sourcePath, *network,
                                      verbose, lastSimulationState,
                                      lastSimulationEndTime);
                    }
                    scanData.push_back(
                        readLastGdat(localPrefix.string() + ".gdat", model));
                }
                writeScanFile(scanBase.string() + ".scan", parameterName,
                              scanValues, scanData);
            } catch (...) {
                restoreScanContext();
                throw;
            }
            restoreScanContext();
            continue;
        }

        if (actionName == "linearparametersensitivity") {
            ensureNetwork();

            // Required parameter: t_end
            const auto tEndText = readArgument(action, "t_end", "");
            if (tEndText.empty()) {
                throw std::runtime_error("LinearParameterSensitivity requires t_end");
            }

            // Optional parameters (Perl BNG2 defaults)
            const double bump = parseScalarValue(readArgument(action, "bump", "5"), model);
            const double atol = parseScalarValue(readArgument(action, "atol", "1e-8"), model);
            const double rtol = parseScalarValue(readArgument(action, "rtol", "1e-8"), model);
            const auto nSteps = static_cast<std::size_t>(parseScalarValue(readArgument(action, "n_steps", "50"), model));
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto initEquilText = lowercase(stripQuotes(readArgument(action, "init_equil", "1")));
            const bool initEquil = (initEquilText == "1" || initEquilText == "true");
            const auto reEquilText = lowercase(stripQuotes(readArgument(action, "re_equil", "1")));
            const bool reEquil = (reEquilText == "1" || reEquilText == "true");
            const double tEquil = parseScalarValue(readArgument(action, "t_equil", "1e6"), model);

            const auto prefix = stripQuotes(readArgument(action, "prefix", sourcePath.stem().string()));
            const auto outputDir = sourcePath.parent_path();

            // Save original parameter values
            std::vector<std::pair<std::string, double>> originalParamValues;
            for (const auto& param : model.getParameters().all()) {
                originalParamValues.emplace_back(param.getName(), param.getValue());
            }

            // Save initial species concentrations
            const auto initialConc = snapshotConcentrations(*network);

            // Helper to build a simulate action with given prefix
            auto makeSimulateAction = [&](const std::string& simPrefix, double tEnd, bool steadyState) -> ast::Action {
                ast::Action simAction;
                simAction.name = "simulate";
                simAction.arguments["method"] = "ode";
                simAction.arguments["t_end"] = formatScalar(tEnd);
                simAction.arguments["n_steps"] = std::to_string(nSteps);
                simAction.arguments["atol"] = formatScalar(atol);
                simAction.arguments["rtol"] = formatScalar(rtol);
                simAction.arguments["prefix"] = simPrefix;
                if (steadyState) {
                    simAction.arguments["steady_state"] = "1";
                }
                return simAction;
            };

            // Initial equilibration of the base model if requested
            if (initEquil) {
                std::string equilPrefix = prefix + "_baseequil_" + suffix;
                auto equilAction = makeSimulateAction(equilPrefix, tEquil, true);
                runSimulation(model, equilAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
            }

            // Run base case simulation
            {
                std::string basePrefix = prefix + "_basecase_" + suffix;
                auto baseAction = makeSimulateAction(basePrefix, parseScalarValue(tEndText, model), false);
                runSimulation(model, baseAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
            }

            if (verbose) {
                std::cerr << "[bng_cpp] LinearParameterSensitivity: base case complete\n";
            }

            // For each parameter, bump and re-simulate
            for (const auto& [paramName, paramValue] : originalParamValues) {
                if (paramValue == 0.0) {
                    if (verbose) {
                        std::cerr << "[bng_cpp] LinearParameterSensitivity: skipping zero-valued parameter '" << paramName << "'\n";
                    }
                    continue;
                }

                const double newValue = paramValue * (1.0 + bump / 100.0);

                // Restore initial concentrations
                restoreConcentrations(*network, initialConc);

                // Bump the parameter
                model.getParameters().add(ast::Parameter(paramName, ast::Expression::number(newValue)));
                model.getParameters().evaluateAll();
                network = generator.generate(sourcePath);

                // Re-equilibrate if requested
                if (reEquil) {
                    std::string equilPrefix = prefix + "_equil_" + paramName + "_" + suffix;
                    auto equilAction = makeSimulateAction(equilPrefix, tEquil, true);
                    runSimulation(model, equilAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
                }

                // Run bumped simulation
                std::string bumpPrefix = prefix + "_" + paramName + "_" + suffix;
                auto bumpAction = makeSimulateAction(bumpPrefix, parseScalarValue(tEndText, model), false);
                runSimulation(model, bumpAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);

                const double parameterDelta = newValue - paramValue;
                writeSensitivityFile(
                    outputDir / (prefix + "_basecase_" + suffix + ".cdat"),
                    outputDir / (bumpPrefix + ".cdat"),
                    outputDir / (bumpPrefix + ".csc"), parameterDelta);
                writeSensitivityFile(
                    outputDir / (prefix + "_basecase_" + suffix + ".gdat"),
                    outputDir / (bumpPrefix + ".gdat"),
                    outputDir / (bumpPrefix + ".gsc"), parameterDelta);

                if (verbose) {
                    std::cerr << "[bng_cpp] LinearParameterSensitivity: completed bump for '" << paramName
                              << "' (" << paramValue << " -> " << newValue << ")\n";
                }

                // Restore the parameter
                model.getParameters().add(ast::Parameter(paramName, ast::Expression::number(paramValue)));
            }

            // Restore all parameters and regenerate network
            for (const auto& [paramName, paramValue] : originalParamValues) {
                model.getParameters().add(ast::Parameter(paramName, ast::Expression::number(paramValue)));
            }
            model.getParameters().evaluateAll();
            network = generator.generate(sourcePath);
            restoreConcentrations(*network, initialConc);

            if (verbose) {
                std::cerr << "[bng_cpp] LinearParameterSensitivity: complete ("
                          << originalParamValues.size() << " parameters)\n";
            }
            continue;
        }

        if (actionName == "bifurcate") {
            ensureNetwork();
            const auto parameterName = stripQuotes(readArgument(action, "parameter", ""));
            if (parameterName.empty()) {
                throw std::runtime_error("bifurcate requires parameter argument");
            }

            const auto minValue = parseScalarValue(readArgument(action, "par_min", ""), model);
            const auto maxValue = parseScalarValue(readArgument(action, "par_max", ""), model);
            const auto points = static_cast<std::size_t>(std::max(1.0, parseScalarValue(readArgument(action, "n_scan_pts", "1"), model)));
            const auto logScale = lowercase(stripQuotes(readArgument(action, "log_scale", "0"))) == "1"
                || lowercase(stripQuotes(readArgument(action, "log_scale", "0"))) == "true";

            // Build a simulate action from the bifurcate arguments
            ast::Action simulateAction = action;
            simulateAction.name = "simulate";
            simulateAction.arguments["method"] = readArgument(action, "method", "ode");

            const auto baseSuffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto prefix = simulationPrefix(action, sourcePath);
            const auto outputDir = sourcePath.parent_path();

            // Helper: compute parameter value at scan point i
            auto computeParamValue = [&](std::size_t i, double pMin, double pMax) -> double {
                const double alpha = points == 1 ? 0.0 : static_cast<double>(i) / static_cast<double>(points - 1);
                if (logScale) {
                    if (pMin <= 0.0 || pMax <= 0.0) {
                        throw std::runtime_error("bifurcate with log_scale requires positive par_min and par_max");
                    }
                    return std::exp(std::log(pMin) + alpha * (std::log(pMax) - std::log(pMin)));
                }
                return pMin + alpha * (pMax - pMin);
            };

            // Save initial concentrations
            const auto initialConc = snapshotConcentrations(*network);

            // === Forward scan (min -> max) ===
            if (verbose) {
                std::cerr << "[bng_cpp] Bifurcate: forward scan (" << points << " points)\n";
            }

            std::vector<std::string> forwardGdatFiles;
            for (std::size_t i = 0; i < points; ++i) {
                const double value = computeParamValue(i, minValue, maxValue);

                model.getParameters().add(ast::Parameter(parameterName, ast::Expression::number(value)));
                model.getParameters().evaluateAll();
                network = generator.generate(sourcePath);
                writeCurrentNetwork();

                std::string scanPrefix = prefix + "_forward_scan" + std::to_string(i + 1);
                simulateAction.arguments["prefix"] = scanPrefix;
                runSimulation(model, simulateAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
                forwardGdatFiles.push_back((outputDir / (scanPrefix + ".gdat")).string());
            }

            // === Backward scan (max -> min) ===
            // Restore initial concentrations before backward scan
            restoreConcentrations(*network, initialConc);

            if (verbose) {
                std::cerr << "[bng_cpp] Bifurcate: backward scan (" << points << " points)\n";
            }

            std::vector<std::string> backwardGdatFiles;
            for (std::size_t i = 0; i < points; ++i) {
                // Backward: scan from max to min
                const double value = computeParamValue(i, maxValue, minValue);

                model.getParameters().add(ast::Parameter(parameterName, ast::Expression::number(value)));
                model.getParameters().evaluateAll();
                network = generator.generate(sourcePath);
                writeCurrentNetwork();

                std::string scanPrefix = prefix + "_backward_scan" + std::to_string(i + 1);
                simulateAction.arguments["prefix"] = scanPrefix;
                runSimulation(model, simulateAction, sourcePath, *network, verbose, lastSimulationState, lastSimulationEndTime);
                backwardGdatFiles.push_back((outputDir / (scanPrefix + ".gdat")).string());
            }

            // === Merge forward and backward .gdat files into bifurcation diagram ===
            // For each scan point, extract the final time point from the .gdat file
            // and write them into a combined bifurcation .gdat file
            const auto bifurcationPath = outputDir / (prefix + "_bifurcation.gdat");
            std::ofstream bifOut(bifurcationPath);
            if (!bifOut) {
                throw std::runtime_error("Failed to open " + bifurcationPath.string() + " for writing");
            }

            // Read header from first forward .gdat file (if available)
            std::string headerLine;
            if (!forwardGdatFiles.empty()) {
                std::ifstream firstFile(forwardGdatFiles[0]);
                if (firstFile && std::getline(firstFile, headerLine)) {
                    // Replace "time" with parameter name in the header
                    bifOut << "#" << std::setw(17) << parameterName;
                    // Copy observable column headers from the original header
                    std::istringstream hss(headerLine);
                    std::string tok;
                    bool first = true;
                    while (hss >> tok) {
                        if (first) { first = false; continue; }  // Skip "#time" or first token
                        bifOut << " " << std::setw(18) << tok;
                    }
                    bifOut << " " << std::setw(18) << "direction";
                    bifOut << "\n";
                }
            }

            // Helper: read the last data line from a .gdat file
            auto readLastLine = [](const std::string& path) -> std::string {
                std::ifstream in(path);
                std::string line, lastLine;
                while (std::getline(in, line)) {
                    if (!line.empty() && line[0] != '#') {
                        lastLine = line;
                    }
                }
                return lastLine;
            };

            // Write forward scan final states
            for (std::size_t i = 0; i < points; ++i) {
                const double value = computeParamValue(i, minValue, maxValue);
                const auto lastLine = readLastLine(forwardGdatFiles[i]);
                if (!lastLine.empty()) {
                    // Replace time column with parameter value, keep observable columns
                    std::istringstream lss(lastLine);
                    std::string timeTok;
                    lss >> timeTok;  // Skip time value
                    bifOut << std::setw(18) << std::setprecision(12) << std::scientific << value;
                    std::string tok;
                    while (lss >> tok) {
                        bifOut << " " << std::setw(18) << tok;
                    }
                    bifOut << " " << std::setw(18) << 1;  // direction = 1 (forward)
                    bifOut << "\n";
                }
            }

            // Write backward scan final states
            for (std::size_t i = 0; i < points; ++i) {
                const double value = computeParamValue(i, maxValue, minValue);
                const auto lastLine = readLastLine(backwardGdatFiles[i]);
                if (!lastLine.empty()) {
                    std::istringstream lss(lastLine);
                    std::string timeTok;
                    lss >> timeTok;  // Skip time value
                    bifOut << std::setw(18) << std::setprecision(12) << std::scientific << value;
                    std::string tok;
                    while (lss >> tok) {
                        bifOut << " " << std::setw(18) << tok;
                    }
                    bifOut << " " << std::setw(18) << -1;  // direction = -1 (backward)
                    bifOut << "\n";
                }
            }

            if (verbose) {
                std::cerr << "[bng_cpp] Wrote bifurcation diagram to " << bifurcationPath << "\n";
            }

            continue;
        }

        if (actionName == "generate_hybrid_model") {
            ensureNetwork();

            engine::HybridModelGenerator::Options hppOpts;

            const auto safeText = lowercase(stripQuotes(readArgument(action, "safe", "0")));
            hppOpts.safe = (safeText == "1" || safeText == "true");

            const auto executeText = lowercase(stripQuotes(readArgument(action, "execute", "0")));
            hppOpts.execute = (executeText == "1" || executeText == "true");

            const auto overwriteText = lowercase(stripQuotes(readArgument(action, "overwrite", "0")));
            hppOpts.overwrite = (overwriteText == "1" || overwriteText == "true");

            const auto verboseText = lowercase(stripQuotes(readArgument(action, "verbose", "0")));
            hppOpts.verbose = (verboseText == "1" || verboseText == "true");

            const auto prefixText = stripQuotes(readArgument(action, "prefix", ""));
            if (!prefixText.empty()) {
                hppOpts.prefix = prefixText;
            }

            const auto suffixText = stripQuotes(readArgument(action, "suffix", ""));
            if (!suffixText.empty()) {
                hppOpts.suffix = suffixText;
            }

            const auto tEndText = readArgument(action, "t_end", "");
            if (!tEndText.empty()) {
                hppOpts.tEnd = parseScalarValue(tEndText, model);
            }
            const auto nStepsText = readArgument(action, "n_steps", "");
            if (!nStepsText.empty()) {
                hppOpts.nSteps = static_cast<std::size_t>(parseScalarValue(nStepsText, model));
            }

            engine::HybridModelGenerator gen(model, *network);
            auto genResult = gen.generate(sourcePath, hppOpts);

            if (verbose) {
                std::cerr << "[bng_cpp] generate_hybrid_model: "
                          << genResult.nMoleculeTypes << " molecule types, "
                          << genResult.nPopulationTypes << " population types, "
                          << genResult.nSeedSpecies << " seed species, "
                          << genResult.nRules << " rules\n";
                std::cerr << "[bng_cpp] Wrote hybrid model: " << genResult.hybridBnglPath << "\n";
            }

            // Optionally execute the hybrid model
            if (hppOpts.execute) {
                if (verbose) {
                    std::cerr << "[bng_cpp] generate_hybrid_model: execute=1, running ODE on full network\n";
                }
                engine::OdeOptions odeOpts;
                odeOpts.tEnd = hppOpts.tEnd;
                odeOpts.nSteps = hppOpts.nSteps;
                odeOpts.method = "cvode";
                engine::OdeIntegrator integrator(model, *network);
                auto odeResult = integrator.integrate(odeOpts);
                const auto prefix = sourcePath.stem().string();
                const auto outputPrefix = sourcePath.parent_path() / (prefix + "_" + hppOpts.suffix);
                integrator.writeOutputFiles(outputPrefix.string(), odeResult);
                if (verbose) {
                    std::cerr << "[bng_cpp] Wrote hybrid simulation output: "
                              << outputPrefix.string() << ".cdat, .gdat\n";
                }
            }
            continue;
        }

        if (actionName == "writefile") {
            ensureNetwork();
            auto format = lowercase(stripQuotes(readArgument(action, "format", "")));
            if (format.empty()) format = "net";

            std::string extension;
            if (format == "net") {
                extension = ".net";
            } else if (format == "xml" || format == "sbml") {
                extension = ".xml";
            } else if (format == "bngl") {
                extension = ".bngl";
            } else if (format == "ssc") {
                extension = ".rxn";
            } else {
                throw std::runtime_error("writeFile: unknown format '" + format + "'");
            }

            auto prefixText = stripQuotes(
                readArgument(action, "prefix", sourcePath.stem().string()));
            if (prefixText.empty()) {
                prefixText = sourcePath.stem().string();
            }
            std::filesystem::path outputPrefix(prefixText);
            if (!outputPrefix.is_absolute()) {
                outputPrefix = sourcePath.parent_path() / outputPrefix;
            }
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            if (!suffix.empty()) {
                outputPrefix += "_" + suffix;
            }
            const auto outputPath = outputPrefix.string() + extension;
            const bool overwrite = parseBoolean(
                readArgument(action, "overwrite", "0"));
            if (!overwrite && std::filesystem::exists(outputPath)) {
                throw std::runtime_error(
                    "writeFile: file exists: " + outputPath +
                    "; set overwrite=>1 to replace it");
            }

            const bool evaluateExpressions = parseBoolean(
                readArgument(action, "evaluate_expressions", "0"));
            if (format == "net") {
                io::NetWriterOptions options;
                options.evaluateExpressions = evaluateExpressions;
                writeNetworkAt(outputPath, options);
            } else {
                std::string content;
                if (format == "xml") {
                    content = io::XmlWriter::write(model, &(*network));
                } else if (format == "sbml") {
                    io::SbmlWriter::Options options;
                    options.level = 2;
                    options.version = 3;
                    options.networksExport = true;
                    content = io::SbmlWriter::write(model, &(*network), options);
                } else if (format == "bngl") {
                    io::BnglWriter::Options options;
                    options.evaluateExpressions = evaluateExpressions;
                    content = io::BnglWriter::write(model, &(*network), options);
                } else {
                    content = io::SscWriter::write(model, *network);
                }

                std::ofstream outFile(outputPath);
                if (!outFile) {
                    throw std::runtime_error(
                        "writeFile: failed to open output file: " + outputPath);
                }
                outFile << content;
                if (!outFile) {
                    throw std::runtime_error(
                        "writeFile: failed to write output file: " + outputPath);
                }
            }
            if (verbose) {
                std::cerr << "[bng_cpp] writeFile format=" << format
                          << " path=" << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writexml") {
            // Write XML without network (NFsim XML format doesn't require generated network)
            const auto xmlContent = io::XmlWriter::write(model, network.has_value() ? &(*network) : nullptr);
            const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + ".xml");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << xmlContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote XML to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writebngl" || action.name == "writemodel") {
            ensureNetwork();
            io::BnglWriter::Options opts;
            opts.includeComments = true;
            opts.includeActions = false;
            const auto bnglContent = io::BnglWriter::write(model, &(*network), opts);
            const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + "_out.bngl");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << bnglContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote BNGL to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writesbml") {
            ensureNetwork();
            io::SbmlWriter::Options sbmlOpts;
            sbmlOpts.level = 2;
            sbmlOpts.version = 3;  // Perl default: L2V3
            sbmlOpts.networksExport = true;

            const auto suffix = stripQuotes(readArgument(action, "suffix", "sbml"));
            const auto sbmlContent = io::SbmlWriter::write(model, &(*network), sbmlOpts);
            const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + "_" + suffix + ".xml");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << sbmlContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote SBML to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writesbmlmulti") {
            const auto suffix = stripQuotes(readArgument(action, "suffix", "sbml_multi"));
            io::SbmlMultiWriter::Options multiOpts;
            const auto multiContent = io::SbmlMultiWriter::write(model, multiOpts);
            const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + "_" + suffix + ".xml");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << multiContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote SBML Multi to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writemfile") {
            ensureNetwork();
            io::MatlabWriter::Options mOpts;
            // Parse action arguments for writeMfile options
            const auto tStartText = readArgument(action, "t_start", "");
            if (!tStartText.empty()) mOpts.tStart = parseScalarValue(tStartText, model);
            const auto tEndText = readArgument(action, "t_end", "");
            if (!tEndText.empty()) mOpts.tEnd = parseScalarValue(tEndText, model);
            const auto nStepsText = readArgument(action, "n_steps", "");
            if (!nStepsText.empty()) mOpts.nSteps = static_cast<std::size_t>(parseScalarValue(nStepsText, model));
            const auto atolText2 = readArgument(action, "atol", "");
            if (!atolText2.empty()) mOpts.atol = parseScalarValue(atolText2, model);
            const auto rtolText2 = readArgument(action, "rtol", "");
            if (!rtolText2.empty()) mOpts.rtol = parseScalarValue(rtolText2, model);
            const auto maxOrderText = readArgument(action, "max_order", readArgument(action, "maxOrder", ""));
            if (!maxOrderText.empty()) mOpts.maxOrder = static_cast<int>(parseScalarValue(maxOrderText, model));
            const auto statsText = lowercase(stripQuotes(readArgument(action, "stats", "0")));
            mOpts.stats = (statsText == "1" || statsText == "on" || statsText == "true");
            const auto bdfText = lowercase(stripQuotes(readArgument(action, "bdf", "0")));
            mOpts.bdf = (bdfText == "1" || bdfText == "on" || bdfText == "true");
            const auto maxStepText = readArgument(action, "max_step", "");
            if (!maxStepText.empty()) mOpts.maxStep = parseScalarValue(maxStepText, model);

            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto mContent = io::MatlabWriter::write(model, *network, mOpts);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            const auto outputPath = sourcePath.parent_path() / (outName + ".m");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << mContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote MATLAB to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writecppfile") {
            ensureNetwork();
            io::CppExportWriter::Options cppOpts;
            const auto tStartText = readArgument(action, "t_start", "");
            if (!tStartText.empty()) cppOpts.tStart = parseScalarValue(tStartText, model);
            const auto tEndText = readArgument(action, "t_end", "");
            if (!tEndText.empty()) cppOpts.tEnd = parseScalarValue(tEndText, model);
            const auto nStepsText = readArgument(action, "n_steps", "");
            if (!nStepsText.empty()) cppOpts.nSteps = static_cast<std::size_t>(parseScalarValue(nStepsText, model));
            const auto atolText3 = readArgument(action, "atol", "");
            if (!atolText3.empty()) cppOpts.atol = parseScalarValue(atolText3, model);
            const auto rtolText3 = readArgument(action, "rtol", "");
            if (!rtolText3.empty()) cppOpts.rtol = parseScalarValue(rtolText3, model);
            const auto maxNumStepsText = readArgument(action, "max_num_steps", "");
            if (!maxNumStepsText.empty()) cppOpts.maxNumSteps = static_cast<int>(parseScalarValue(maxNumStepsText, model));
            const auto maxErrText = readArgument(action, "max_err_test_fails", "");
            if (!maxErrText.empty()) cppOpts.maxErrTestFails = static_cast<int>(parseScalarValue(maxErrText, model));
            const auto maxConvText = readArgument(action, "max_conv_fails", "");
            if (!maxConvText.empty()) cppOpts.maxConvFails = static_cast<int>(parseScalarValue(maxConvText, model));
            const auto maxStepText3 = readArgument(action, "max_step", "");
            if (!maxStepText3.empty()) cppOpts.maxStep = parseScalarValue(maxStepText3, model);
            const auto stiffText = lowercase(stripQuotes(readArgument(action, "stiff", "1")));
            cppOpts.stiff = (stiffText != "0" && stiffText != "false" && stiffText != "off");
            const auto sparseText = lowercase(stripQuotes(readArgument(action, "sparse", "0")));
            cppOpts.sparse = (sparseText == "1" || sparseText == "on" || sparseText == "true");

            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto cppContent = io::CppExportWriter::write(model, *network, cppOpts);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            outName += "_cvode";
            const auto outputPath = sourcePath.parent_path() / (outName + ".h");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << cppContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote C++ CVODE header to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writecpyfile") {
            ensureNetwork();
            io::PythonExportWriter::Options pyOpts;
            const auto tStartText = readArgument(action, "t_start", "");
            if (!tStartText.empty()) pyOpts.tStart = parseScalarValue(tStartText, model);
            const auto tEndText = readArgument(action, "t_end", "");
            if (!tEndText.empty()) pyOpts.tEnd = parseScalarValue(tEndText, model);
            const auto nStepsText = readArgument(action, "n_steps", "");
            if (!nStepsText.empty()) pyOpts.nSteps = static_cast<std::size_t>(parseScalarValue(nStepsText, model));
            const auto atolText4 = readArgument(action, "atol", "");
            if (!atolText4.empty()) pyOpts.atol = parseScalarValue(atolText4, model);
            const auto rtolText4 = readArgument(action, "rtol", "");
            if (!rtolText4.empty()) pyOpts.rtol = parseScalarValue(rtolText4, model);

            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto pyContent = io::PythonExportWriter::write(model, *network, pyOpts);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            outName += "_pyode";
            const auto outputPath = sourcePath.parent_path() / (outName + ".py");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << pyContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote Python ODE to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writemexfile") {
            ensureNetwork();
            io::MexWriter::Options mexOpts;
            const auto tStartText = readArgument(action, "t_start", "");
            if (!tStartText.empty()) mexOpts.tStart = parseScalarValue(tStartText, model);
            const auto tEndText = readArgument(action, "t_end", "");
            if (!tEndText.empty()) mexOpts.tEnd = parseScalarValue(tEndText, model);
            const auto nStepsText = readArgument(action, "n_steps", "");
            if (!nStepsText.empty()) mexOpts.nSteps = static_cast<std::size_t>(parseScalarValue(nStepsText, model));
            const auto atolText5 = readArgument(action, "atol", "");
            if (!atolText5.empty()) mexOpts.atol = parseScalarValue(atolText5, model);
            const auto rtolText5 = readArgument(action, "rtol", "");
            if (!rtolText5.empty()) mexOpts.rtol = parseScalarValue(rtolText5, model);
            const auto maxNumStepsText5 = readArgument(action, "max_num_steps", "");
            if (!maxNumStepsText5.empty()) mexOpts.maxNumSteps = static_cast<int>(parseScalarValue(maxNumStepsText5, model));

            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto mexContent = io::MexWriter::write(model, *network, mexOpts);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            outName += "_mex";
            const auto outputPath = sourcePath.parent_path() / (outName + ".c");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << mexContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote MEX file to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "visualize") {
            const auto vizType = lowercase(stripQuotes(readArgument(action, "type", "contactmap")));
            const auto outputFormat = lowercase(stripQuotes(readArgument(action, "format", "gml")));

            std::string content;
            std::string extension;
            std::string fileSuffix;

            if (vizType == "contactmap" || vizType == "contact_map") {
                // Contact map (does not require generated network)
                auto contactMap = io::ContactMapWriter::buildContactMap(model);

                if (outputFormat == "dot") {
                    content = io::ContactMapWriter::toDOT(contactMap);
                    extension = ".dot";
                } else {
                    content = io::ContactMapWriter::toGML(contactMap);
                    extension = ".gml";
                }
                fileSuffix = "_contact";

            } else if (vizType == "regulatory") {
                // Regulatory graph (requires generated network)
                ensureNetwork();
                auto regGraph = io::RegulatoryGraphWriter::build(model, *network);
                content = io::RegulatoryGraphWriter::toGML(regGraph);
                extension = ".gml";
                fileSuffix = "_regulatory";

            } else if (vizType == "reaction_network") {
                // Reaction network graph (requires generated network)
                ensureNetwork();
                auto rxnGraph = io::ReactionNetworkGraphWriter::build(model, *network);
                content = io::ReactionNetworkGraphWriter::toGML(rxnGraph);
                extension = ".gml";
                fileSuffix = "_reaction_network";

            } else if (vizType == "ruleviz_pattern") {
                // Rule pattern visualization (does not require generated network)
                auto patGraph = io::RulevizPatternWriter::build(model);
                content = io::RulevizPatternWriter::toGML(patGraph);
                extension = ".gml";
                fileSuffix = "_ruleviz_pattern";

            } else if (vizType == "ruleviz_operation") {
                // Rule operation visualization (does not require generated network)
                auto opGraph = io::RulevizOperationWriter::build(model);
                content = io::RulevizOperationWriter::toGML(opGraph);
                extension = ".gml";
                fileSuffix = "_ruleviz_operation";

            } else if (vizType == "process") {
                // Bipartite process graph (requires generated network)
                ensureNetwork();
                auto procGraph = io::ProcessGraphWriter::build(model, *network);
                content = io::ProcessGraphWriter::toGML(procGraph);
                extension = ".gml";
                fileSuffix = "_process";

            } else if (vizType == "rinf" || vizType == "rule_influence") {
                // Rule influence graph (requires generated network)
                ensureNetwork();
                auto rinfGraph = io::RuleInfluenceGraphWriter::build(model, *network);
                content = io::RuleInfluenceGraphWriter::toGML(rinfGraph);
                extension = ".gml";
                fileSuffix = "_rinf";

            } else if (vizType == "opts") {
                // Generate visualization options template
                std::ostringstream opts;
                opts << "# BNG2 Visualization Options Template\n";
                opts << "# Generated by bng_cpp\n\n";
                opts << "# Available visualization types:\n";
                opts << "#   contactmap        - Molecule contact map (GML/DOT)\n";
                opts << "#   regulatory         - Regulatory graph (GML)\n";
                opts << "#   reaction_network   - Reaction network graph (GML)\n";
                opts << "#   ruleviz_pattern    - Rule pattern visualization (GML)\n";
                opts << "#   ruleviz_operation  - Rule operation visualization (GML)\n";
                opts << "#   process            - Bipartite process graph (GML)\n";
                opts << "#   rinf               - Rule influence graph (GML)\n";
                opts << "#\n";
                opts << "# Options:\n";
                opts << "#   type => \"contactmap\"    # visualization type\n";
                opts << "#   format => \"gml\"         # output format: gml or dot\n";
                opts << "#   background => \"white\"   # background color\n";
                opts << "#   opts => \"\"              # additional options\n";
                content = opts.str();
                extension = ".txt";
                fileSuffix = "_viz_opts";

            } else {
                throw std::runtime_error(
                    "visualize: unsupported visualization type '" + vizType + "'");
            }

            const auto outputPath = sourcePath.parent_path() / (sourcePath.stem().string() + fileSuffix + extension);
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << content;

            if (verbose) {
                std::cerr << "[bng_cpp] Wrote " << vizType << " visualization to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writelatex") {
            ensureNetwork();
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto latexContent = io::LatexWriter::write(model, *network);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            const auto outputPath = sourcePath.parent_path() / (outName + ".tex");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << latexContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote LaTeX to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writemdl") {
            ensureNetwork();
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto mdlContent = io::MdlWriter::write(model, *network);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            const auto outputPath = sourcePath.parent_path() / (outName + ".mdl");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << mdlContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote MDL to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "writessc" || actionName == "writessccfg") {
            ensureNetwork();
            const auto suffix = stripQuotes(readArgument(action, "suffix", ""));
            const auto sscContent = io::SscWriter::write(model, *network);
            std::string outName = sourcePath.stem().string();
            if (!suffix.empty()) outName += "_" + suffix;
            const auto outputPath = sourcePath.parent_path() / (outName + ".rxn");
            std::ofstream outFile(outputPath);
            if (!outFile) {
                throw std::runtime_error("Failed to open " + outputPath.string() + " for writing");
            }
            outFile << sscContent;
            if (verbose) {
                std::cerr << "[bng_cpp] Wrote SSC to " << outputPath << "\n";
            }
            continue;
        }

        if (actionName == "simulate_protocol") {
            const auto& protocol = model.getSimulationProtocol();
            if (protocol.empty()) {
                throw std::runtime_error(
                    "simulate_protocol requires a non-empty protocol block");
            }
            if (verbose) {
                std::cerr << "[bng_cpp] simulate_protocol: dispatching " << protocol.size() << " protocol actions\n";
            }
            runProtocol(std::nullopt);
            continue;
        }

        if (actionName == "writenetwork" || actionName == "writenet") {
            ensureNetwork();
            writeCurrentNetwork();
            continue;
        }

        if (actionName.rfind("write", 0) == 0) {
            ensureNetwork();
            writeCurrentNetwork();
        }
    }
}

} // namespace bng::actions
