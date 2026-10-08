#include "SbmlUnitWriter.hpp"

#include "compile/CompiledModel.hpp"

#include <cmath>
#include <cctype>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>

namespace bng::io::sbml_units {
namespace {

std::string escapeXml(const std::string& text) {
    std::string result;
    result.reserve(text.size());
    for (const char character : text) {
        switch (character) {
        case '&': result += "&amp;"; break;
        case '<': result += "&lt;"; break;
        case '>': result += "&gt;"; break;
        case '"': result += "&quot;"; break;
        case '\'': result += "&apos;"; break;
        default: result += character; break;
        }
    }
    return result;
}

std::string validId(const std::string& text) {
    std::string result;
    for (const char character : text) {
        if (std::isalnum(static_cast<unsigned char>(character)) || character == '_') {
            result += character;
        } else {
            result += '_';
        }
    }
    if (result.empty() || std::isdigit(static_cast<unsigned char>(result.front()))) {
        result.insert(result.begin(), '_');
    }
    return result;
}

std::string canonicalBuiltin(const std::string& name) {
    if (name == "dimensionless") return "dimensionless";
    if (name == "mol" || name == "mole") return "mole";
    if (name == "item" || name == "molecule") return "item";
    if (name == "metre" || name == "meter") return "metre";
    if (name == "litre" || name == "liter" || name == "L") return "litre";
    if (name == "second" || name == "s") return "second";
    return {};
}

double baseFactor(units::BaseUnit base) {
    switch (base) {
    case units::BaseUnit::Dimensionless:
    case units::BaseUnit::Mole:
    case units::BaseUnit::Item:
    case units::BaseUnit::Metre:
    case units::BaseUnit::Second:
        return 1.0;
    case units::BaseUnit::Litre:
        return 1e-3;
    }
    return 1.0;
}

std::string sbmlKind(units::BaseUnit base) {
    switch (base) {
    case units::BaseUnit::Dimensionless: return "dimensionless";
    case units::BaseUnit::Mole: return "mole";
    case units::BaseUnit::Item: return "item";
    case units::BaseUnit::Metre: return "metre";
    case units::BaseUnit::Litre: return "litre";
    case units::BaseUnit::Second: return "second";
    }
    return "dimensionless";
}

bool isPowerOfTen(double value, int& scale) {
    if (!(value > 0.0) || !std::isfinite(value)) return false;
    const double logarithm = std::log10(value);
    const auto rounded = static_cast<int>(std::llround(logarithm));
    if (std::abs(logarithm - static_cast<double>(rounded)) > 1e-10) return false;
    scale = rounded;
    return true;
}

std::string unitDefinition(const std::string& id, const units::Unit& unit) {
    std::ostringstream xml;
    xml << "      <unitDefinition id=\"" << escapeXml(id) << "\">\n";
    xml << "        <listOfUnits>\n";

    double physicalBaseFactor = 1.0;
    for (const auto& [base, exponent] : unit.baseExponents) {
        physicalBaseFactor *= std::pow(baseFactor(base), exponent);
    }
    const double relativeFactor = unit.factor / physicalBaseFactor;
    if (unit.baseExponents.empty()) {
        int scale = 0;
        if (isPowerOfTen(relativeFactor, scale)) {
            xml << "          <unit kind=\"dimensionless\" exponent=\"1\" multiplier=\"1\" scale=\""
                << scale << "\"/>\n";
        } else {
            xml << std::setprecision(17)
                << "          <unit kind=\"dimensionless\" exponent=\"1\" multiplier=\""
                << relativeFactor << "\"/>\n";
        }
    } else {
        // A multiplier/scale attached to a base term is raised to that term's
        // exponent by SBML.  Put the residual factor on an explicit
        // dimensionless term instead, so inverse and higher-order units retain
        // the exact factor as well (for example M^-1*s^-1).
        if (std::abs(relativeFactor - 1.0) > 1e-15) {
            int scale = 0;
            if (isPowerOfTen(relativeFactor, scale)) {
                xml << "          <unit kind=\"dimensionless\" exponent=\"1\" multiplier=\"1\" scale=\""
                    << scale << "\"/>\n";
            } else {
                xml << std::setprecision(17)
                    << "          <unit kind=\"dimensionless\" exponent=\"1\" multiplier=\""
                    << relativeFactor << "\" scale=\"0\"/>\n";
            }
        }
        for (const auto& [base, exponent] : unit.baseExponents) {
            xml << std::setprecision(17)
                << "          <unit kind=\"" << sbmlKind(base)
                << "\" exponent=\"" << exponent << "\" multiplier=\"1\" scale=\"0\"";
            xml << "/>\n";
        }
    }
    xml << "        </listOfUnits>\n";
    xml << "      </unitDefinition>\n";
    return xml.str();
}

void collect(std::map<std::string, units::Unit>& definitions,
             const compile::CompiledModel& model, const std::string& authored) {
    if (authored.empty()) return;
    const auto canonical = canonicalBuiltin(authored);
    const auto& references = model.metadata().resolvedUnitReferences;
    const auto resolved = references.find(authored);
    if (resolved == references.end()) return;
    if (!canonical.empty()) {
        // SBML Core provides these base units directly.
        if (canonical == "item" && authored == "molecule") return;
        return;
    }
    definitions[reference(model, authored)] = resolved->second.unit;
}

const units::Unit* resolvedUnit(const compile::CompiledModel& model,
                                const std::string& authored) {
    const auto& references = model.metadata().resolvedUnitReferences;
    const auto found = references.find(authored);
    return found == references.end() ? nullptr : &found->second.unit;
}

bool sameUnitSemantics(const units::Unit& lhs, const units::Unit& rhs) {
    const auto conversion = units::conversionFactor(lhs, rhs);
    return conversion && std::abs(*conversion.factor - 1.0) <= 1e-12;
}

void mapLevel2Defaults(std::map<std::string, units::Unit>& definitions,
                       const compile::CompiledModel& model) {
    const auto& defaults = model.metadata().unitDefaults;
    for (const auto& [role, id] : std::map<std::string, std::string>{
             {"timeUnits", "time"}, {"substanceUnits", "substance"},
             {"volumeUnits", "volume"}, {"areaUnits", "area"},
             {"lengthUnits", "length"}}) {
        const auto authored = defaults.find(role);
        if (authored == defaults.end()) continue;
        const auto* unit = resolvedUnit(model, authored->second);
        if (unit == nullptr) {
            throw std::invalid_argument(
                "SBML Level 2 cannot resolve model default " + role + "='" +
                authored->second + "'");
        }
        // In Level 2, these reserved UnitDefinition ids are the model-wide
        // defaults.  Level 2 Model has no corresponding unit attributes.
        definitions[id] = *unit;
    }

    const auto extent = defaults.find("extentUnits");
    if (extent == defaults.end()) return;
    const auto* extentUnit = resolvedUnit(model, extent->second);
    if (extentUnit == nullptr) {
        throw std::invalid_argument(
            "SBML Level 2 cannot resolve model default extentUnits='" +
            extent->second + "'");
    }

    // Level 2 has no extentUnits default: reaction extent uses the model's
    // substance unit.  Use the effective substance UnitDefinition (including
    // the writer's existing count-basis fallback) or SBML's implicit mole
    // default, and fail closed if that changes the requested extent basis.
    units::Unit implicitMole;
    implicitMole.name = "mole";
    implicitMole.dimension.substance = 1;
    implicitMole.baseExponents[units::BaseUnit::Mole] = 1;
    const auto substance = definitions.find("substance");
    const auto& substanceUnit = substance == definitions.end()
        ? implicitMole : substance->second;
    if (!sameUnitSemantics(*extentUnit, substanceUnit)) {
        throw std::invalid_argument(
            "SBML Level 2 cannot preserve extentUnits='" + extent->second +
            "' because reaction extent uses the model substance unit; "
            "extentUnits and substanceUnits must be physically equivalent");
    }
}

} // namespace

bool enabled(const compile::CompiledModel& model) {
    for (const auto& parameter : model.parameters())
        if (parameter.declaredUnit.has_value()) return true;
    for (const auto& compartment : model.compartments())
        if (compartment.declaredUnit.has_value()) return true;
    for (const auto& seed : model.seeds())
        if (seed.declaredUnit.has_value()) return true;
    return !model.metadata().unitDefaults.empty() ||
           !model.metadata().unitDefinitions.empty();
}

std::string reference(const compile::CompiledModel& model, const std::string& authored) {
    const auto canonical = canonicalBuiltin(authored);
    if (!canonical.empty()) return canonical;
    const auto& references = model.metadata().resolvedUnitReferences;
    const auto resolved = references.find(authored);
    if (resolved != references.end() && resolved->second.namedDefinition) {
        return validId(authored);
    }
    return "bng_unit_" + validId(authored);
}

std::string attribute(const compile::CompiledModel& model, const std::string& authored) {
    return authored.empty() ? std::string {} : " units=\"" + escapeXml(reference(model, authored)) + "\"";
}

std::string speciesAttribute(const compile::CompiledModel& model,
                             const std::string& authored, int level) {
    if (authored.empty()) return {};
    const auto name = level == 1 ? "units" : "substanceUnits";
    return " " + std::string(name) + "=\"" + escapeXml(reference(model, authored)) + "\"";
}

std::string modelAttributes(const compile::CompiledModel& model, int level) {
    if (level < 3) return {};
    std::ostringstream result;
    for (const auto& [role, authored] : model.metadata().unitDefaults) {
        if (role != "timeUnits" && role != "substanceUnits" && role != "volumeUnits" &&
            role != "areaUnits" && role != "lengthUnits" && role != "extentUnits") continue;
        result << " " << role << "=\"" << escapeXml(reference(model, authored)) << "\"";
    }
    return result.str();
}

std::string writeUnitDefinitions(const compile::CompiledModel& model, int level) {
    std::ostringstream xml;
    std::map<std::string, units::Unit> definitions;
    if (!enabled(model)) {
        const auto& references = model.metadata().resolvedUnitReferences;
        const auto item = references.find("item");
        if (item != references.end()) definitions["substance"] = item->second.unit;
    } else {
        const auto& references = model.metadata().resolvedUnitReferences;
        const auto item = references.find("item");
        if (item != references.end()) definitions["substance"] = item->second.unit;
        for (const auto& definition : model.metadata().unitDefinitions) {
            definitions[reference(model, definition.id)] = definition.unit;
        }
        for (const auto& [_, authored] : model.metadata().unitDefaults) {
            collect(definitions, model, authored);
        }
        for (const auto& parameter : model.parameters()) {
            if (parameter.declaredUnit.has_value()) collect(definitions, model, parameter.unitName);
        }
        for (const auto& compartment : model.compartments()) {
            if (compartment.declaredUnit.has_value()) {
                collect(definitions, model, compartment.unitName);
            }
        }
        for (const auto& seed : model.seeds()) {
            if (seed.declaredUnit.has_value()) collect(definitions, model, seed.unitName);
        }
    }
    if (level == 2) mapLevel2Defaults(definitions, model);
    xml << "    <listOfUnitDefinitions>\n";
    for (const auto& [id, unit] : definitions) xml << unitDefinition(id, unit);
    xml << "    </listOfUnitDefinitions>\n";
    return xml.str();
}

} // namespace bng::io::sbml_units
