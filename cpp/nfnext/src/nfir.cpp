#include "nfnext/nfir.hpp"

#include <iomanip>
#include <sstream>

namespace nfnext {
namespace {

inline void mix(std::uint64_t& h, std::uint64_t v) noexcept {
    h ^= v + 0x9E3779B97F4A7C15ULL + (h << 6) + (h >> 2);
}

inline void mixString(std::uint64_t& h, const std::string& s) noexcept {
    for (unsigned char c : s) mix(h, c);
}

void mixPattern(std::uint64_t& h, const PatternIR& pattern) noexcept {
    mix(h, pattern.nodes.size());
    for (const auto& node : pattern.nodes) {
        mix(h, node.molecule_type);
        mix(h, node.constraints.size());
        for (const auto& constraint : node.constraints) {
            mix(h, static_cast<std::uint8_t>(constraint.kind));
            mix(h, constraint.site);
            mix(h, static_cast<std::uint32_t>(constraint.state));
            mix(h, constraint.states.size());
            for (const auto state : constraint.states) mix(h, static_cast<std::uint32_t>(state));
        }
    }
    mix(h, pattern.bonds.size());
    for (const auto& bond : pattern.bonds) {
        mix(h, bond.first); mix(h, bond.first_site);
        mix(h, bond.second); mix(h, bond.second_site);
    }
    mix(h, pattern.molecularity.size());
    for (const auto& constraint : pattern.molecularity) {
        mix(h, static_cast<std::uint8_t>(constraint.kind));
        mix(h, constraint.left); mix(h, constraint.right);
    }
    mix(h, pattern.aliases.size());
    for (const auto& pair : pattern.aliases) { mix(h, pair.first); mix(h, pair.second); }
    mix(h, pattern.connected_to.size());
    for (const auto& pair : pattern.connected_to) { mix(h, pair.first); mix(h, pair.second); }
    mix(h, pattern.interchangeable.size());
    for (const auto& group : pattern.interchangeable) {
        mix(h, group.size());
        for (const auto node : group) mix(h, node);
    }
}

} // namespace

std::uint64_t encodeFeature(TypeId type, std::uint16_t site, PredicateKind kind, std::int32_t value) noexcept {
    std::uint64_t key = static_cast<std::uint64_t>(type) << 32;
    key |= static_cast<std::uint64_t>(site) << 16;
    key |= static_cast<std::uint64_t>(static_cast<std::uint8_t>(kind)) << 8;
    key ^= static_cast<std::uint32_t>(value) * 0x9E3779B1u;
    return key;
}

std::uint64_t ModelIR::fingerprint() const noexcept {
    std::uint64_t h = 0xCBF29CE484222325ULL;
    mixString(h, model_name);
    mix(h, lattice_length);
    mix(h, static_cast<std::uint8_t>(preferred_backend));
    for (const auto& mt : molecule_types) {
        mix(h, mt.id); mixString(h, mt.name);
        for (const auto& s : mt.sites) { mixString(h, s.name); for (const auto& st : s.states) mixString(h, st); }
    }
    for (const auto& f : rule_families) {
        mix(h, f.id); mixString(h, f.name); mix(h, f.begin_index); mix(h, f.end_index);
        mix(h, f.coordinate_parameterized ? 1 : 0);
        mix(h, static_cast<std::uint8_t>(f.rate_law.kind));
        mixString(h, f.rate_law.expression);
        union { double d; std::uint64_t u; } rate{f.default_rate}; mix(h, rate.u);
        for (double r : f.indexed_rates) { union { double d; std::uint64_t u; } rr{r}; mix(h, rr.u); }
        for (const auto& p : f.predicates) {
            mix(h, static_cast<std::uint8_t>(p.kind)); mix(h, p.molecule_type); mix(h, p.site);
            mix(h, static_cast<std::uint32_t>(p.value)); mix(h, static_cast<std::uint32_t>(p.aux));
            mix(h, p.state_set.size());
            for (const auto state : p.state_set) mix(h, static_cast<std::uint32_t>(state));
        }
        for (const auto& a : f.actions) {
            mix(h, static_cast<std::uint8_t>(a.kind)); mix(h, a.molecule_type); mix(h, a.site);
            mix(h, static_cast<std::uint32_t>(a.value)); mix(h, static_cast<std::uint32_t>(a.aux));
        }
        mixPattern(h, f.pattern);
        for (RuleId r : f.source_rules) mix(h, r);
    }
    return h;
}

std::string ModelIR::summary() const {
    std::ostringstream out;
    out << "ModelIR(name=" << model_name
        << ", molecule_types=" << molecule_types.size()
        << ", expanded_rules=" << expanded_rules.size()
        << ", rule_families=" << rule_families.size()
        << ", dependency_features=" << dependencies.feature_to_families.size()
        << ", backend=" << static_cast<int>(preferred_backend)
        << ", lattice_length=" << lattice_length
        << ", fingerprint=0x" << std::hex << fingerprint() << std::dec << ")";
    return out.str();
}

} // namespace nfnext
