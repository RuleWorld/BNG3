#include "nfnext/cache.hpp"

#include <fstream>
#include <stdexcept>
#include <type_traits>

namespace nfnext {
namespace {

constexpr char kMagic[8] = {'N','F','I','R','B','I','N','1'};

template<class T>
void writePod(std::ostream& out, const T& value) {
    static_assert(std::is_trivially_copyable<T>::value, "POD required");
    out.write(reinterpret_cast<const char*>(&value), sizeof(T));
    if (!out) throw std::runtime_error("NFIR cache write failed");
}

template<class T>
T readPod(std::istream& in) {
    static_assert(std::is_trivially_copyable<T>::value, "POD required");
    T value{};
    in.read(reinterpret_cast<char*>(&value), sizeof(T));
    if (!in) throw std::runtime_error("NFIR cache truncated");
    return value;
}

void writeString(std::ostream& out, const std::string& s) {
    const std::uint64_t n = s.size(); writePod(out, n); out.write(s.data(), static_cast<std::streamsize>(n));
    if (!out) throw std::runtime_error("NFIR cache write failed");
}

std::string readString(std::istream& in) {
    const std::uint64_t n = readPod<std::uint64_t>(in);
    if (n > (1ULL << 31)) throw std::runtime_error("NFIR cache invalid string length");
    std::string s(static_cast<std::size_t>(n), '\0');
    in.read(&s[0], static_cast<std::streamsize>(n));
    if (!in) throw std::runtime_error("NFIR cache truncated");
    return s;
}

void writePredicate(std::ostream& out, const PredicateIR& p) {
    writePod(out, static_cast<std::uint8_t>(p.kind)); writePod(out, p.molecule_type);
    writePod(out, p.site); writePod(out, p.value); writePod(out, p.aux);
}

PredicateIR readPredicate(std::istream& in) {
    PredicateIR p; p.kind = static_cast<PredicateKind>(readPod<std::uint8_t>(in));
    p.molecule_type = readPod<TypeId>(in); p.site = readPod<std::uint16_t>(in);
    p.value = readPod<std::int32_t>(in); p.aux = readPod<std::int32_t>(in); return p;
}

void writeAction(std::ostream& out, const ActionIR& a) {
    writePod(out, static_cast<std::uint8_t>(a.kind)); writePod(out, a.molecule_type);
    writePod(out, a.site); writePod(out, a.value); writePod(out, a.aux);
}

ActionIR readAction(std::istream& in) {
    ActionIR a; a.kind = static_cast<ActionKind>(readPod<std::uint8_t>(in));
    a.molecule_type = readPod<TypeId>(in); a.site = readPod<std::uint16_t>(in);
    a.value = readPod<std::int32_t>(in); a.aux = readPod<std::int32_t>(in); return a;
}

template<class T, class Writer>
void writeVector(std::ostream& out, const std::vector<T>& v, Writer writer) {
    writePod(out, static_cast<std::uint64_t>(v.size())); for (const auto& x : v) writer(out, x);
}

template<class T, class Reader>
std::vector<T> readVector(std::istream& in, Reader reader) {
    const std::uint64_t n = readPod<std::uint64_t>(in);
    if (n > (1ULL << 30)) throw std::runtime_error("NFIR cache invalid vector length");
    std::vector<T> v; v.reserve(static_cast<std::size_t>(n));
    for (std::uint64_t i = 0; i < n; ++i) v.push_back(reader(in)); return v;
}

} // namespace

void ModelCache::save(const ModelIR& model, const std::string& path) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("cannot open NFIR cache for writing");
    out.write(kMagic, sizeof(kMagic)); writePod(out, ModelIR::kFormatVersion);
    writeString(out, model.model_name); writePod(out, model.lattice_length);
    writePod(out, static_cast<std::uint8_t>(model.preferred_backend));

    writePod(out, static_cast<std::uint64_t>(model.molecule_types.size()));
    for (const auto& mt : model.molecule_types) {
        writePod(out, mt.id); writeString(out, mt.name); writePod(out, static_cast<std::uint64_t>(mt.sites.size()));
        for (const auto& site : mt.sites) {
            writeString(out, site.name); writePod(out, static_cast<std::uint64_t>(site.states.size()));
            for (const auto& state : site.states) writeString(out, state);
        }
    }

    writePod(out, static_cast<std::uint64_t>(model.rule_families.size()));
    for (const auto& f : model.rule_families) {
        writePod(out, f.id); writeString(out, f.name); writePod(out, f.begin_index); writePod(out, f.end_index);
        writePod(out, f.default_rate); writePod(out, static_cast<std::uint8_t>(f.coordinate_parameterized ? 1 : 0));
        writeVector<double>(out, f.indexed_rates, [](std::ostream& o, double x){ writePod(o, x); });
        writeVector<PredicateIR>(out, f.predicates, writePredicate);
        writeVector<ActionIR>(out, f.actions, writeAction);
        writeVector<RuleId>(out, f.source_rules, [](std::ostream& o, RuleId x){ writePod(o, x); });
    }

    writePod(out, static_cast<std::uint64_t>(model.dependencies.feature_to_families.size()));
    for (const auto& kv : model.dependencies.feature_to_families) {
        writePod(out, kv.first);
        writeVector<FamilyId>(out, kv.second, [](std::ostream& o, FamilyId x){ writePod(o, x); });
    }
    writePod(out, model.fingerprint());
}

ModelIR ModelCache::load(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open NFIR cache for reading");
    char magic[8]{}; in.read(magic, sizeof(magic));
    if (!in || !std::equal(std::begin(magic), std::end(magic), std::begin(kMagic))) throw std::runtime_error("invalid NFIR cache magic");
    const auto version = readPod<std::uint32_t>(in);
    if (version != ModelIR::kFormatVersion) throw std::runtime_error("unsupported NFIR cache version");

    ModelIR model; model.model_name = readString(in); model.lattice_length = readPod<std::uint32_t>(in);
    model.preferred_backend = static_cast<BackendKind>(readPod<std::uint8_t>(in));

    const auto ntypes = readPod<std::uint64_t>(in); model.molecule_types.reserve(static_cast<std::size_t>(ntypes));
    for (std::uint64_t i = 0; i < ntypes; ++i) {
        MoleculeTypeIR mt; mt.id = readPod<TypeId>(in); mt.name = readString(in);
        const auto nsites = readPod<std::uint64_t>(in); mt.sites.reserve(static_cast<std::size_t>(nsites));
        for (std::uint64_t j = 0; j < nsites; ++j) {
            SiteSpec site; site.name = readString(in); const auto nstates = readPod<std::uint64_t>(in);
            site.states.reserve(static_cast<std::size_t>(nstates)); for (std::uint64_t k = 0; k < nstates; ++k) site.states.push_back(readString(in));
            mt.sites.push_back(std::move(site));
        }
        model.molecule_types.push_back(std::move(mt));
    }

    const auto nfam = readPod<std::uint64_t>(in); model.rule_families.reserve(static_cast<std::size_t>(nfam));
    for (std::uint64_t i = 0; i < nfam; ++i) {
        RuleFamilyIR f; f.id = readPod<FamilyId>(in); f.name = readString(in);
        f.begin_index = readPod<std::uint32_t>(in); f.end_index = readPod<std::uint32_t>(in);
        f.default_rate = readPod<double>(in); f.coordinate_parameterized = readPod<std::uint8_t>(in) != 0;
        f.indexed_rates = readVector<double>(in, [](std::istream& x){ return readPod<double>(x); });
        f.predicates = readVector<PredicateIR>(in, readPredicate);
        f.actions = readVector<ActionIR>(in, readAction);
        f.source_rules = readVector<RuleId>(in, [](std::istream& x){ return readPod<RuleId>(x); });
        model.rule_families.push_back(std::move(f));
    }

    const auto ndeps = readPod<std::uint64_t>(in);
    for (std::uint64_t i = 0; i < ndeps; ++i) {
        const auto key = readPod<std::uint64_t>(in);
        model.dependencies.feature_to_families.emplace(key,
            readVector<FamilyId>(in, [](std::istream& x){ return readPod<FamilyId>(x); }));
    }
    const auto expected = readPod<std::uint64_t>(in);
    if (model.fingerprint() != expected) throw std::runtime_error("NFIR cache fingerprint mismatch");
    return model;
}

} // namespace nfnext
