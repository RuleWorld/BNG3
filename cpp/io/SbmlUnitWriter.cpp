#include "SbmlUnitWriter.hpp"

#include <cmath>
#include <algorithm>
#include <cctype>
#include <iomanip>
#include <map>
#include <sstream>
#include <string_view>

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
             const ast::Model& model, const std::string& authored) {
    if (authored.empty()) return;
    const auto canonical = canonicalBuiltin(authored);
    const auto* resolved = model.getUnitSystem().find(authored);
    if (resolved == nullptr) {
        const auto parsed = model.getUnitSystem().parse(authored);
        if (parsed) definitions[reference(model, authored)] = *parsed.unit;
        return;
    }
    if (!canonical.empty()) {
        // SBML Core provides these base units directly.
        if (canonical == "item" && authored == "molecule") return;
        return;
    }
    definitions[reference(model, authored)] = *resolved;
}

} // namespace

bool enabled(const ast::Model& model) {
    for (const auto& parameter : model.getParameters().all())
        if (parameter.hasUnit()) return true;
    for (const auto& compartment : model.getCompartments())
        if (compartment.hasUnit()) return true;
    for (const auto& seed : model.getSeedSpecies())
        if (seed.hasUnit()) return true;
    return !model.getUnitDefaults().empty() ||
           std::any_of(model.getUnitSystem().definitions().begin(),
                       model.getUnitSystem().definitions().end(),
                       [](const auto& definition) { return !definition.builtin; });
}

std::string reference(const ast::Model& model, const std::string& authored) {
    const auto canonical = canonicalBuiltin(authored);
    if (!canonical.empty()) return canonical;
    if (model.getUnitSystem().find(authored) != nullptr) return validId(authored);
    return "bng_unit_" + validId(authored);
}

std::string attribute(const ast::Model& model, const std::string& authored) {
    return authored.empty() ? std::string {} : " units=\"" + escapeXml(reference(model, authored)) + "\"";
}

std::string modelAttributes(const ast::Model& model) {
    std::ostringstream result;
    for (const auto& [role, authored] : model.getUnitDefaults()) {
        if (role != "timeUnits" && role != "substanceUnits" && role != "volumeUnits" &&
            role != "areaUnits" && role != "lengthUnits" && role != "extentUnits") continue;
        result << " " << role << "=\"" << escapeXml(reference(model, authored)) << "\"";
    }
    return result.str();
}

std::string writeUnitDefinitions(const ast::Model& model) {
    std::ostringstream xml;
    std::map<std::string, units::Unit> definitions;
    if (!enabled(model)) {
        auto item = model.getUnitSystem().parse("item");
        if (item) definitions["substance"] = *item.unit;
    } else {
        auto item = model.getUnitSystem().parse("item");
        if (item) definitions["substance"] = *item.unit;
        for (const auto& definition : model.getUnitSystem().definitions()) {
            if (!definition.builtin) definitions[reference(model, definition.id)] = definition.unit;
        }
        for (const auto& [_, authored] : model.getUnitDefaults()) collect(definitions, model, authored);
        for (const auto& parameter : model.getParameters().all())
            if (parameter.hasUnit()) collect(definitions, model, parameter.getUnitName());
        for (const auto& compartment : model.getCompartments())
            if (compartment.hasUnit()) collect(definitions, model, compartment.getUnitName());
        for (const auto& seed : model.getSeedSpecies())
            if (seed.hasUnit()) collect(definitions, model, seed.getUnitName());
    }
    xml << "    <listOfUnitDefinitions>\n";
    for (const auto& [id, unit] : definitions) xml << unitDefinition(id, unit);
    xml << "    </listOfUnitDefinitions>\n";
    return xml.str();
}

} // namespace bng::io::sbml_units
