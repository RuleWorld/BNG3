#include "Unit.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <sstream>
#include <utility>

namespace bng::units {
namespace {

Unit makeBase(BaseUnit base, Dimension dimension, double factor,
              std::string name = {}) {
    Unit unit;
    unit.name = std::move(name);
    unit.dimension = dimension;
    unit.baseExponents[base] = 1;
    unit.factor = factor;
    return unit;
}

Unit multiply(Unit lhs, const Unit& rhs, int sign = 1) {
    lhs.name.clear();
    lhs.dimension.substance += sign * rhs.dimension.substance;
    lhs.dimension.length += sign * rhs.dimension.length;
    lhs.dimension.time += sign * rhs.dimension.time;
    for (const auto& [base, exponent] : rhs.baseExponents) {
        lhs.baseExponents[base] += sign * exponent;
        if (lhs.baseExponents[base] == 0) lhs.baseExponents.erase(base);
    }
    if (sign == 1) {
        lhs.factor *= rhs.factor;
    } else {
        lhs.factor /= rhs.factor;
    }
    return lhs;
}

Unit power(Unit unit, int exponent) {
    unit.name.clear();
    unit.dimension.substance *= exponent;
    unit.dimension.length *= exponent;
    unit.dimension.time *= exponent;
    for (auto it = unit.baseExponents.begin(); it != unit.baseExponents.end();) {
        it->second *= exponent;
        if (it->second == 0) {
            it = unit.baseExponents.erase(it);
        } else {
            ++it;
        }
    }
    unit.factor = std::pow(unit.factor, static_cast<double>(exponent));
    return unit;
}

class UnitParser {
public:
    UnitParser(std::string_view source, const UnitSystem& system)
        : source_(source), system_(system) {}

    UnitParseResult parse() {
        skipSpace();
        Unit result;
        result.name = "dimensionless";
        if (atEnd()) return {result, {}};

        // A leading slash is convenient inside an explicit annotation, e.g.
        // [/s], but is not accepted by the ordinary BNGL expression grammar.
        if (peek() == '/') {
            composed_ = true;
            advance();
            auto rhs = parseFactor();
            if (!rhs) return {std::nullopt, error_};
            result = multiply(result, *rhs, -1);
        } else {
            auto first = parseFactor();
            if (!first) return {std::nullopt, error_};
            result = *first;
        }

        while (true) {
            skipSpace();
            if (atEnd()) break;
            const char op = peek();
            composed_ = true;
            if (op != '*' && op != '/') {
                return fail("expected '*' or '/' in unit expression");
            }
            advance();
            auto rhs = parseFactor();
            if (!rhs) return {std::nullopt, error_};
            result = multiply(result, *rhs, op == '*' ? 1 : -1);
        }
        if (composed_) result.name.clear();
        return {result, {}};
    }

private:
    std::string_view source_;
    const UnitSystem& system_;
    std::size_t position_ = 0;
    std::string error_;
    bool composed_ = false;

    bool atEnd() const { return position_ >= source_.size(); }
    char peek() const { return atEnd() ? '\0' : source_[position_]; }

    void advance() {
        if (!atEnd()) ++position_;
    }

    void skipSpace() {
        while (!atEnd() && std::isspace(static_cast<unsigned char>(peek()))) advance();
    }

    UnitParseResult fail(std::string message) {
        if (error_.empty()) {
            error_ = std::move(message);
            error_ += " at character " + std::to_string(position_);
        }
        return {std::nullopt, error_};
    }

    std::optional<int> parseExponent() {
        skipSpace();
        int sign = 1;
        if (peek() == '+' || peek() == '-') {
            if (peek() == '-') sign = -1;
            advance();
        }
        const auto start = position_;
        long value = 0;
        while (!atEnd() && std::isdigit(static_cast<unsigned char>(peek()))) {
            value = value * 10 + (peek() - '0');
            if (value > std::numeric_limits<int>::max()) return std::nullopt;
            advance();
        }
        if (position_ == start) return std::nullopt;
        return sign * static_cast<int>(value);
    }

    std::optional<double> parseNumber() {
        skipSpace();
        const auto start = position_;
        bool sawDigit = false;
        while (!atEnd() && std::isdigit(static_cast<unsigned char>(peek()))) {
            sawDigit = true;
            advance();
        }
        if (!atEnd() && peek() == '.') {
            advance();
            while (!atEnd() && std::isdigit(static_cast<unsigned char>(peek()))) {
                sawDigit = true;
                advance();
            }
        }
        if (!sawDigit) {
            position_ = start;
            return std::nullopt;
        }
        if (!atEnd() && (peek() == 'e' || peek() == 'E')) {
            advance();
            if (!atEnd() && (peek() == '+' || peek() == '-')) advance();
            const auto exponentStart = position_;
            while (!atEnd() && std::isdigit(static_cast<unsigned char>(peek()))) advance();
            if (position_ == exponentStart) return std::nullopt;
        }
        const std::string token(source_.substr(start, position_ - start));
        char* end = nullptr;
        const double value = std::strtod(token.c_str(), &end);
        if (end == token.c_str() || !std::isfinite(value)) return std::nullopt;
        return value;
    }

    std::optional<std::string> parseIdentifier() {
        skipSpace();
        const auto start = position_;
        if (atEnd() || !(std::isalpha(static_cast<unsigned char>(peek())) || peek() == '_')) {
            return std::nullopt;
        }
        advance();
        while (!atEnd() && (std::isalnum(static_cast<unsigned char>(peek())) || peek() == '_')) {
            advance();
        }
        return std::string(source_.substr(start, position_ - start));
    }

    std::optional<Unit> parseFactor() {
        skipSpace();
        Unit result;
        if (peek() == '(') {
            advance();
            auto nested = parseProduct();
            if (!nested) return std::nullopt;
            skipSpace();
            if (peek() != ')') {
                fail("expected ')' in unit expression");
                return std::nullopt;
            }
            advance();
            result = *nested;
        } else if (const auto number = parseNumber()) {
            result.name.clear();
            result.dimension = {};
            result.factor = *number;
        } else if (const auto identifier = parseIdentifier()) {
            const auto* found = system_.find(*identifier);
            if (found == nullptr) {
                fail("unknown unit '" + *identifier + "'");
                return std::nullopt;
            }
            result = *found;
        } else {
            fail("expected a unit name, number, or parenthesized unit");
            return std::nullopt;
        }

        skipSpace();
        if (peek() == '^') {
            composed_ = true;
            advance();
            const auto exponent = parseExponent();
            if (!exponent) {
                fail("unit exponents must be signed integers");
                return std::nullopt;
            }
            result = power(result, *exponent);
        }
        return result;
    }

    std::optional<Unit> parseProduct() {
        auto first = parseFactor();
        if (!first) return std::nullopt;
        Unit result = *first;
        while (true) {
            skipSpace();
            if (peek() != '*' && peek() != '/') break;
            const char op = peek();
            advance();
            auto rhs = parseFactor();
            if (!rhs) return std::nullopt;
            result = multiply(result, *rhs, op == '*' ? 1 : -1);
        }
        return result;
    }
};

void addPrefixedVolume(UnitSystem& system, const std::string& name, double factor,
                       const std::string& expression) {
    Unit unit = makeBase(BaseUnit::Litre, {0, 3, 0}, factor, name);
    system.addBuiltin(name, std::move(unit), expression);
}

void addPrefixedLength(UnitSystem& system, const std::string& name, double factor,
                       const std::string& expression) {
    Unit unit = makeBase(BaseUnit::Metre, {0, 1, 0}, factor, name);
    system.addBuiltin(name, std::move(unit), expression);
}

} // namespace

int Unit::exponent(BaseUnit base) const {
    const auto it = baseExponents.find(base);
    return it == baseExponents.end() ? 0 : it->second;
}

UnitSystem::UnitSystem() {
    addBuiltin("dimensionless", Unit {}, "1");
    addBuiltin("mole", makeBase(BaseUnit::Mole, {1, 0, 0}, 1.0, "mole"), "mole");
    addBuiltin("mol", units_.at("mole"), "mole");
    addBuiltin("item", makeBase(BaseUnit::Item, {1, 0, 0}, 1.0, "item"), "item");
    addBuiltin("molecule", units_.at("item"), "item");
    addBuiltin("metre", makeBase(BaseUnit::Metre, {0, 1, 0}, 1.0, "metre"), "metre");
    addBuiltin("meter", units_.at("metre"), "metre");
    addBuiltin("second", makeBase(BaseUnit::Second, {0, 0, 1}, 1.0, "second"), "second");
    addBuiltin("s", units_.at("second"), "second");
    addBuiltin("min", makeBase(BaseUnit::Second, {0, 0, 1}, 60.0, "min"), "60 second");
    addBuiltin("minute", units_.at("min"), "min");
    addBuiltin("hr", makeBase(BaseUnit::Second, {0, 0, 1}, 3600.0, "hr"), "3600 second");
    addBuiltin("hour", units_.at("hr"), "hr");

    addPrefixedLength(*this, "cm", 1e-2, "metre*1e-2");
    addPrefixedLength(*this, "mm", 1e-3, "metre*1e-3");
    addPrefixedLength(*this, "um", 1e-6, "metre*1e-6");
    addPrefixedLength(*this, "nm", 1e-9, "metre*1e-9");

    addPrefixedVolume(*this, "litre", 1e-3, "litre");
    addBuiltin("liter", units_.at("litre"), "litre");
    addBuiltin("L", units_.at("litre"), "litre");
    addPrefixedVolume(*this, "mL", 1e-6, "litre*1e-3");
    addPrefixedVolume(*this, "uL", 1e-9, "litre*1e-6");
    addPrefixedVolume(*this, "nL", 1e-12, "litre*1e-9");
    addPrefixedVolume(*this, "pL", 1e-15, "litre*1e-12");
    addPrefixedVolume(*this, "fL", 1e-18, "litre*1e-15");

    auto concentration = [&](const std::string& name, double moleScale,
                             const std::string& expression) {
        Unit unit = makeBase(BaseUnit::Mole, {1, 0, 0}, moleScale, name);
        unit = multiply(unit, units_.at("litre"), -1);
        unit.name = name;
        addBuiltin(name, std::move(unit), expression);
    };
    concentration("M", 1.0, "mole/litre");
    concentration("mM", 1e-3, "mole*1e-3/litre");
    concentration("uM", 1e-6, "mole*1e-6/litre");
    concentration("nM", 1e-9, "mole*1e-9/litre");
    concentration("pM", 1e-12, "mole*1e-12/litre");
}

void UnitSystem::addBuiltin(std::string name, Unit unit, std::string expression) {
    unit.name = name;
    units_[name] = unit;
    definitions_.push_back({std::move(name), std::move(expression), std::move(unit), true});
}

const Unit* UnitSystem::find(std::string_view name) const {
    const auto it = units_.find(std::string(name));
    return it == units_.end() ? nullptr : &it->second;
}

UnitParseResult UnitSystem::parse(std::string_view expression) const {
    UnitParser parser(expression, *this);
    return parser.parse();
}

UnitParseResult UnitSystem::define(std::string id, std::string expression) {
    if (id.empty()) return {std::nullopt, "unit name cannot be empty"};
    if (find(id) != nullptr) return {std::nullopt, "unit '" + id + "' is already defined"};
    auto parsed = parse(expression);
    if (!parsed) return parsed;
    parsed.unit->name = id;
    units_[id] = *parsed.unit;
    definitions_.push_back({std::move(id), std::move(expression), *parsed.unit, false});
    return parsed;
}

bool dimensionallyCompatible(const Unit& lhs, const Unit& rhs) {
    return lhs.dimension == rhs.dimension;
}

Unit multiplyUnits(const Unit& lhs, const Unit& rhs) {
    return multiply(lhs, rhs, 1);
}

Unit divideUnits(const Unit& lhs, const Unit& rhs) {
    return multiply(lhs, rhs, -1);
}

Unit powerUnit(const Unit& unit, int exponent) {
    return power(unit, exponent);
}

ConversionResult conversionFactor(const Unit& from, const Unit& to,
                                  const ConversionContext& context) {
    if (!dimensionallyCompatible(from, to)) {
        return {std::nullopt, "units have incompatible dimensions (" + formatUnit(from) +
                                  " versus " + formatUnit(to) + ")"};
    }

    const int fromItem = from.exponent(BaseUnit::Item);
    const int toItem = to.exponent(BaseUnit::Item);
    const int fromMole = from.exponent(BaseUnit::Mole);
    const int toMole = to.exponent(BaseUnit::Mole);
    if (fromItem != toItem || fromMole != toMole) {
        if (!context.numberPerQuantityUnit.has_value() ||
            !std::isfinite(*context.numberPerQuantityUnit) ||
            *context.numberPerQuantityUnit <= 0.0) {
            return {std::nullopt,
                    "conversion between mole and item requires a positive "
                    "NumberPerQuantityUnit"};
        }
        if (fromItem + fromMole != toItem + toMole) {
            return {std::nullopt, "unit conversion changes the substance exponent"};
        }
    }

    const double bridge = context.numberPerQuantityUnit.value_or(1.0);
    const double fromToMole = std::pow(bridge, -static_cast<double>(fromItem));
    const double toToMole = std::pow(bridge, -static_cast<double>(toItem));
    const double factor = (from.factor * fromToMole) / (to.factor * toToMole);
    if (!std::isfinite(factor)) return {std::nullopt, "unit conversion factor is not finite"};
    return {factor, {}};
}

ConversionResult convertValue(double value, const Unit& from, const Unit& to,
                              const ConversionContext& context) {
    if (!std::isfinite(value)) return {std::nullopt, "value to convert is not finite"};
    const auto factor = conversionFactor(from, to, context);
    if (!factor) return factor;
    const double converted = value * *factor.factor;
    if (!std::isfinite(converted)) return {std::nullopt, "converted value is not finite"};
    return {converted, {}};
}

ConversionResult concentrationToItemAmount(double value, const Unit& concentration,
                                            double volume, const Unit& volumeUnit,
                                            const ConversionContext& context) {
    if (!std::isfinite(value) || !std::isfinite(volume) || volume < 0.0) {
        return {std::nullopt, "concentration and volume must be finite and non-negative"};
    }
    if (concentration.dimension.length != -3 || concentration.dimension.time != 0 ||
        volumeUnit.dimension.length != 3 || volumeUnit.dimension.substance != 0 ||
        volumeUnit.dimension.time != 0) {
        return {std::nullopt, "concentration-to-amount conversion requires concentration and volume units"};
    }

    Unit item;
    item.name = "item";
    item.dimension.substance = 1;
    item.baseExponents[BaseUnit::Item] = 1;
    const auto amountUnit = multiplyUnits(concentration, volumeUnit);
    const auto factor = conversionFactor(amountUnit, item, context);
    if (!factor) return factor;
    const double converted = value * volume * *factor.factor;
    if (!std::isfinite(converted)) return {std::nullopt, "converted item amount is not finite"};
    return {converted, {}};
}

ConversionResult stochasticRateFactor(const Unit& rateUnit, std::size_t molecularity,
                                       const ConversionContext& context) {
    if (molecularity > static_cast<std::size_t>(std::numeric_limits<int>::max() - 1)) {
        return {std::nullopt, "reaction molecularity is too large for unit conversion"};
    }

    Unit item;
    item.name = "item";
    item.dimension.substance = 1;
    item.baseExponents[BaseUnit::Item] = 1;
    Unit second;
    second.name = "second";
    second.dimension.time = 1;
    second.baseExponents[BaseUnit::Second] = 1;
    const auto exponent = 1 - static_cast<int>(molecularity);
    const auto target = multiplyUnits(powerUnit(item, exponent), powerUnit(second, -1));

    // A count-based rate unit is already in the backend basis.  A unit with a
    // non-zero spatial exponent is a concentration-rate unit and must be
    // evaluated in the explicit compartment context.  Unit algebra then
    // rejects malformed rate dimensions rather than guessing.
    if (rateUnit.dimension.length == 0) {
        return conversionFactor(rateUnit, target, context);
    }
    if (!context.compartmentVolume.has_value() || !context.volumeUnit.has_value() ||
        !std::isfinite(*context.compartmentVolume) || *context.compartmentVolume <= 0.0 ||
        context.volumeUnit->dimension.length != 3 ||
        context.volumeUnit->dimension.substance != 0 ||
        context.volumeUnit->dimension.time != 0) {
        return {std::nullopt,
                "concentration-rate conversion requires a positive compartment volume"};
    }

    const auto volumeExponent = 1 - static_cast<int>(molecularity);
    const auto adjusted = multiplyUnits(
        rateUnit, powerUnit(*context.volumeUnit, volumeExponent));
    const auto factor = conversionFactor(adjusted, target, context);
    if (!factor) return factor;
    const double numericVolumeFactor = std::pow(
        *context.compartmentVolume, static_cast<double>(volumeExponent));
    const double result = numericVolumeFactor * *factor.factor;
    if (!std::isfinite(result)) return {std::nullopt, "stochastic rate factor is not finite"};
    return {result, {}};
}

std::string baseUnitName(BaseUnit base) {
    switch (base) {
    case BaseUnit::Dimensionless: return "1";
    case BaseUnit::Mole: return "mole";
    case BaseUnit::Item: return "item";
    case BaseUnit::Metre: return "metre";
    case BaseUnit::Litre: return "litre";
    case BaseUnit::Second: return "second";
    }
    return "unknown";
}

std::string formatUnit(const Unit& unit) {
    if (!unit.name.empty()) return unit.name;
    if (unit.baseExponents.empty()) return "1";
    std::ostringstream result;
    bool first = true;
    for (const auto& [base, exponent] : unit.baseExponents) {
        if (!first) result << '*';
        first = false;
        result << baseUnitName(base);
        if (exponent != 1) result << '^' << exponent;
    }
    return result.str();
}

} // namespace bng::units
