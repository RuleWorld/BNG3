#include "nfnext/cache_v2.hpp"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <system_error>

namespace nfnext {
namespace {

constexpr char kMagic[8] = {'N', 'F', 'C', 'A', 'C', 'H', '2', '\0'};
constexpr std::uint32_t kVersion = 2;
constexpr std::size_t kHeaderBytes = 8 + sizeof(std::uint32_t) + sizeof(std::uint64_t);
constexpr std::size_t kFooterBytes = sizeof(std::uint32_t) + sizeof(std::uint64_t);

template <class T>
void appendPod(std::vector<unsigned char>& bytes, const T& value) {
    const auto* begin = reinterpret_cast<const unsigned char*>(&value);
    bytes.insert(bytes.end(), begin, begin + sizeof(T));
}

template <class T>
T readPod(const std::vector<unsigned char>& bytes, std::size_t& offset) {
    if (offset > bytes.size() || bytes.size() - offset < sizeof(T))
        throw CacheCorrupt("truncated NFIR cache field");
    T value{};
    std::memcpy(&value, bytes.data() + offset, sizeof(T));
    offset += sizeof(T);
    return value;
}

void appendString(std::vector<unsigned char>& bytes, const std::string& value) {
    appendPod<std::uint64_t>(bytes, value.size());
    bytes.insert(bytes.end(), value.begin(), value.end());
}

std::string readString(const std::vector<unsigned char>& bytes, std::size_t& offset) {
    const auto size = readPod<std::uint64_t>(bytes, offset);
    if (size > bytes.size() - offset) throw CacheCorrupt("oversized NFIR cache string");
    std::string value(reinterpret_cast<const char*>(bytes.data() + offset),
                      static_cast<std::size_t>(size));
    offset += static_cast<std::size_t>(size);
    return value;
}

std::uint64_t hashBytes(const std::string& value) noexcept {
    std::uint64_t hash = 0xcbf29ce484222325ULL;
    for (const unsigned char byte : value) {
        hash ^= byte;
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

std::uint32_t checksum(const std::vector<unsigned char>& bytes,
                       std::size_t begin, std::size_t end) noexcept {
    std::uint32_t value = 0xffffffffU;
    for (std::size_t i = begin; i < end; ++i) {
        value ^= bytes[i];
        for (int bit = 0; bit < 8; ++bit)
            value = (value >> 1) ^ (0xedb88320U & static_cast<std::uint32_t>(-static_cast<int>(value & 1U)));
    }
    return ~value;
}

std::string digestString(const std::string& value) {
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << hashBytes(value);
    return out.str();
}

std::vector<unsigned char> readFile(const std::string& path,
                                    const CacheLoadOptions& options) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw CacheIoError("cannot open NFIR cache");
    in.seekg(0, std::ios::end);
    const auto end = in.tellg();
    if (end < 0) throw CacheIoError("cannot size NFIR cache");
    const auto size = static_cast<std::uint64_t>(end);
    if (size > options.max_bytes) throw CacheBudgetExceeded("NFIR cache byte budget exceeded");
    in.seekg(0, std::ios::beg);
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    if (!bytes.empty()) in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!in && !bytes.empty()) throw CacheIoError("cannot read NFIR cache");
    return bytes;
}

void writeFile(const std::string& path, const std::vector<unsigned char>& bytes) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw CacheIoError("cannot write NFIR cache");
    if (!bytes.empty()) out.write(reinterpret_cast<const char*>(bytes.data()),
                                  static_cast<std::streamsize>(bytes.size()));
    if (!out) throw CacheIoError("cannot write NFIR cache");
}

struct SectionView {
    std::uint16_t id{0};
    std::uint8_t flags{0};
    std::size_t body{0};
    std::size_t size{0};
};

std::vector<SectionView> sectionViews(const std::vector<unsigned char>& payload) {
    std::vector<SectionView> result;
    std::size_t offset = 0;
    while (offset < payload.size()) {
        if (payload.size() - offset < sizeof(std::uint16_t) + 2 + sizeof(std::uint64_t))
            throw CacheCorrupt("truncated NFIR cache section header");
        const auto id = readPod<std::uint16_t>(payload, offset);
        const auto flags = readPod<std::uint8_t>(payload, offset);
        (void)readPod<std::uint8_t>(payload, offset);
        const auto size = readPod<std::uint64_t>(payload, offset);
        if (size > payload.size() - offset) throw CacheCorrupt("oversized NFIR cache section");
        result.push_back({id, flags, offset, static_cast<std::size_t>(size)});
        offset += static_cast<std::size_t>(size);
    }
    return result;
}

void appendSection(std::vector<unsigned char>& payload, std::uint16_t id,
                   std::uint8_t flags, const std::vector<unsigned char>& body) {
    appendPod<std::uint16_t>(payload, id);
    appendPod<std::uint8_t>(payload, flags);
    appendPod<std::uint8_t>(payload, 0);
    appendPod<std::uint64_t>(payload, body.size());
    payload.insert(payload.end(), body.begin(), body.end());
}

std::vector<unsigned char> encode(const CacheModel& model) {
    std::vector<unsigned char> payload;
    std::vector<unsigned char> types;
    appendPod<std::uint64_t>(types, 0);
    appendSection(payload, static_cast<std::uint16_t>(CacheSection::MoleculeTypes), 0, types);

    std::vector<unsigned char> families;
    appendPod<std::uint64_t>(families, model.rule_count);
    appendSection(payload, static_cast<std::uint16_t>(CacheSection::RuleFamilies), 0, families);

    std::vector<unsigned char> canonical;
    appendPod<std::uint64_t>(canonical, model.rule_count);
    appendString(canonical, model.canonicalBytes());
    appendSection(payload, static_cast<std::uint16_t>(CacheSection::CanonicalModel), 0, canonical);

    std::vector<unsigned char> metadata;
    appendPod<std::uint64_t>(metadata, model.metadata.size());
    for (const auto& item : model.metadata) {
        appendString(metadata, item.first);
        appendString(metadata, item.second);
    }
    appendSection(payload, static_cast<std::uint16_t>(CacheSection::Metadata), 0, metadata);
    return payload;
}

std::vector<unsigned char> makeFile(const CacheModel& model) {
    const auto payload = encode(model);
    std::vector<unsigned char> bytes;
    bytes.insert(bytes.end(), std::begin(kMagic), std::end(kMagic));
    appendPod<std::uint32_t>(bytes, kVersion);
    appendPod<std::uint64_t>(bytes, payload.size());
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    appendPod<std::uint32_t>(bytes, checksum(bytes, kHeaderBytes, bytes.size()));
    appendPod<std::uint64_t>(bytes, model.semanticFingerprint());
    return bytes;
}

void validateEnvelope(const std::vector<unsigned char>& bytes,
                      const CacheLoadOptions& options,
                      std::uint64_t& version, std::size_t& payload_begin,
                      std::size_t& payload_end) {
    if (bytes.size() < 8 + sizeof(std::uint32_t)) throw CacheCorrupt("truncated NFIR cache header");
    if (!std::equal(std::begin(kMagic), std::end(kMagic), bytes.begin()))
        throw CacheCorrupt("invalid NFIR cache magic");
    std::size_t offset = 8;
    version = readPod<std::uint32_t>(bytes, offset);
    if (version > kVersion) throw CacheVersionUnsupported("unsupported NFIR cache version");
    if (version < kVersion) {
        if (version != 1) throw CacheVersionUnsupported("unsupported NFIR cache version");
        payload_begin = payload_end = 0;
        return;
    }
    if (bytes.size() < kHeaderBytes + kFooterBytes) throw CacheCorrupt("truncated NFIR cache");
    const auto declared = readPod<std::uint64_t>(bytes, offset);
    if (declared > bytes.size() - kHeaderBytes - kFooterBytes)
        throw CacheCorrupt("NFIR cache section exceeds file");
    payload_begin = kHeaderBytes;
    payload_end = payload_begin + static_cast<std::size_t>(declared);
    if (payload_end + kFooterBytes != bytes.size())
        throw CacheCorrupt("NFIR cache has trailing or missing bytes");
    if (bytes.size() > options.max_bytes)
        throw CacheBudgetExceeded("NFIR cache byte budget exceeded");
    const auto checksum_end = payload_end;
    std::size_t footer_offset = checksum_end;
    const auto stored = readPod<std::uint32_t>(bytes, footer_offset);
    if (stored != checksum(bytes, payload_begin, checksum_end))
        throw CacheCorrupt("NFIR cache checksum mismatch");
}

CacheLoadResult decode(const std::vector<unsigned char>& bytes,
                       const CacheLoadOptions& options) {
    std::uint64_t version = 0;
    std::size_t payload_begin = 0, payload_end = 0;
    validateEnvelope(bytes, options, version, payload_begin, payload_end);
    if (version < kVersion) return {CacheModel{}, CacheLoadReport{true}};

    const std::vector<unsigned char> payload(bytes.begin() + payload_begin,
                                             bytes.begin() + payload_end);
    const auto views = sectionViews(payload);
    CacheModel model;
    bool saw_canonical = false;
    for (const auto& view : views) {
        const auto known = view.id == static_cast<std::uint16_t>(CacheSection::MoleculeTypes) ||
                           view.id == static_cast<std::uint16_t>(CacheSection::RuleFamilies) ||
                           view.id == static_cast<std::uint16_t>(CacheSection::CanonicalModel) ||
                           view.id == static_cast<std::uint16_t>(CacheSection::Metadata);
        if (!known) {
            if ((view.flags & 1U) == 0)
                throw CacheVersionUnsupported("unknown required NFIR cache section");
            continue;
        }
        std::vector<unsigned char> body(payload.begin() + view.body,
                                        payload.begin() + view.body + view.size);
        std::size_t offset = 0;
        if (view.id == static_cast<std::uint16_t>(CacheSection::CanonicalModel)) {
            model.rule_count = static_cast<std::size_t>(readPod<std::uint64_t>(body, offset));
            model.canonical_bytes = readString(body, offset);
            if (offset != body.size()) throw CacheCorrupt("extra canonical NFIR cache data");
            saw_canonical = true;
        } else if (view.id == static_cast<std::uint16_t>(CacheSection::RuleFamilies)) {
            const auto count = readPod<std::uint64_t>(body, offset);
            if (count > options.max_rules) throw CacheBudgetExceeded("NFIR cache rule budget exceeded");
        } else if (view.id == static_cast<std::uint16_t>(CacheSection::Metadata)) {
            const auto count = readPod<std::uint64_t>(body, offset);
            if (count > (1ULL << 30)) throw CacheCorrupt("oversized NFIR cache metadata");
            for (std::uint64_t i = 0; i < count; ++i)
                model.metadata.emplace(readString(body, offset), readString(body, offset));
            if (offset != body.size()) throw CacheCorrupt("extra metadata NFIR cache data");
        }
    }
    if (!saw_canonical) throw CacheCorrupt("NFIR cache has no canonical model section");

    const auto stored_fingerprint = [&bytes, payload_end]() {
        std::size_t offset = payload_end + sizeof(std::uint32_t);
        return readPod<std::uint64_t>(bytes, offset);
    }();
    if (stored_fingerprint != model.semanticFingerprint())
        throw CacheSemanticMismatch("NFIR cache semantic fingerprint mismatch");
    return {std::move(model), CacheLoadReport{false}};
}

std::vector<unsigned char> sectionBytes(std::uint16_t id, std::uint8_t flags,
                                        std::initializer_list<unsigned char> body) {
    std::vector<unsigned char> section;
    appendPod<std::uint16_t>(section, id);
    appendPod<std::uint8_t>(section, flags);
    appendPod<std::uint8_t>(section, 0);
    appendPod<std::uint64_t>(section, body.size());
    section.insert(section.end(), body.begin(), body.end());
    return section;
}

void injectSection(const std::string& path, std::uint16_t id, std::uint8_t flags,
                   std::initializer_list<unsigned char> body) {
    auto bytes = readBytes(path);
    if (bytes.size() < kHeaderBytes + kFooterBytes) throw CacheCorrupt("cache too short");
    std::size_t header_offset = 8;
    (void)readPod<std::uint32_t>(bytes, header_offset);
    const auto payload_size = readPod<std::uint64_t>(bytes, header_offset);
    const auto payload_end = kHeaderBytes + static_cast<std::size_t>(payload_size);
    if (payload_end + kFooterBytes != bytes.size()) throw CacheCorrupt("cache layout invalid");
    const auto section = sectionBytes(id, flags, body);
    bytes.insert(bytes.begin() + payload_end, section.begin(), section.end());
    const auto new_size = payload_size + section.size();
    std::memcpy(bytes.data() + 12, &new_size, sizeof(new_size));
    const auto new_payload_end = payload_end + section.size();
    const auto sum = checksum(bytes, kHeaderBytes, new_payload_end);
    std::memcpy(bytes.data() + new_payload_end, &sum, sizeof(sum));
    writeBytes(path, bytes);
}

} // namespace

std::string CacheKey::digest() const {
    std::ostringstream key;
    key << source_sha256 << '\n' << parser_version << '\n' << compiler_version << '\n'
        << static_cast<unsigned>(options.connectivity);
    if (contains_native_code) key << '\n' << target_abi;
    key << '\n' << (contains_native_code ? 1 : 0);
    return digestString(key.str());
}

std::string CacheModel::canonicalBytes() const {
    if (!canonical_bytes.empty()) return canonical_bytes;
    return "name:" + model_name + ";model:cache-v2;";
}

std::uint64_t CacheModel::semanticFingerprint() const noexcept {
    return hashBytes(canonicalBytes());
}

bool CacheIndex::hasSection(CacheSection section) const noexcept {
    const auto id = static_cast<std::uint16_t>(section);
    return std::find(sections.begin(), sections.end(), id) != sections.end();
}

void CacheV2::save(const CacheModel& model, const std::string& path,
                   CacheFaultInjector* fault) {
    static std::atomic<std::uint64_t> counter{0};
    const auto temporary = path + ".tmp-" + std::to_string(counter.fetch_add(1));
    const auto bytes = makeFile(model);
    try {
        writeFile(temporary, bytes);
        if (fault != nullptr && fault->trips(CacheFaultPoint::BeforeRename))
            throw CacheIoError("injected cache rename failure");
        std::error_code error;
        std::filesystem::rename(temporary, path, error);
        if (error) throw CacheIoError("cannot atomically replace NFIR cache: " + error.message());
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
}

CacheLoadResult CacheV2::loadWithReport(const std::string& path,
                                        const CacheLoadOptions& options) {
    return decode(readFile(path, options), options);
}

CacheModel CacheV2::load(const std::string& path, const CacheLoadOptions& options) {
    return loadWithReport(path, options).model;
}

CacheIndex CacheV2::inspect(const std::string& path) {
    const auto bytes = readFile(path, {});
    std::uint64_t version = 0;
    std::size_t payload_begin = 0, payload_end = 0;
    validateEnvelope(bytes, {}, version, payload_begin, payload_end);
    if (version < kVersion) return {};
    const std::vector<unsigned char> payload(bytes.begin() + payload_begin,
                                             bytes.begin() + payload_end);
    CacheIndex index;
    for (const auto& section : sectionViews(payload)) index.sections.push_back(section.id);
    return index;
}

CacheModel makeCanonicalCacheFixture() {
    CacheModel model;
    model.model_name = "cache-fixture";
    model.canonical_bytes = "name:cache-fixture;types:A(x~u,p);families:binding;";
    model.rule_count = 2;
    return model;
}

CacheModel makeLargeCacheFixture(std::size_t rule_count) {
    CacheModel model;
    model.model_name = "large-cache-fixture";
    model.rule_count = rule_count;
    model.canonical_bytes = "name:large;rules:" + std::to_string(rule_count) + ';' +
                            std::string(std::max<std::size_t>(rule_count / 2, 1024), 'r');
    return model;
}

std::string tempPath(const std::string& suffix) {
    static std::atomic<std::uint64_t> counter{0};
    const auto id = counter.fetch_add(1);
    return (std::filesystem::temp_directory_path() /
            ("bng3-nfnext-cache-" + suffix + "-" + std::to_string(id) + ".bin")).string();
}

bool fileExists(const std::string& path) {
    std::error_code error;
    return std::filesystem::exists(path, error);
}

void removeFile(const std::string& path) {
    std::error_code error;
    std::filesystem::remove(path, error);
}

std::vector<unsigned char> readBytes(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw CacheIoError("cannot open cache helper file");
    in.seekg(0, std::ios::end);
    const auto end = in.tellg();
    if (end < 0) throw CacheIoError("cannot size cache helper file");
    in.seekg(0, std::ios::beg);
    std::vector<unsigned char> bytes(static_cast<std::size_t>(end));
    if (!bytes.empty()) in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return bytes;
}

void writeBytes(const std::string& path, const std::vector<unsigned char>& bytes) {
    writeFile(path, bytes);
}

void writeMinimalCache(const std::string& path, const std::string& magic) {
    std::vector<unsigned char> bytes(8, 0);
    std::copy_n(magic.begin(), std::min<std::size_t>(magic.size(), bytes.size()), bytes.begin());
    writeBytes(path, bytes);
}

void writeCacheVersion(const std::string& path, std::uint32_t version) {
    std::vector<unsigned char> bytes(std::begin(kMagic), std::end(kMagic));
    appendPod<std::uint32_t>(bytes, version);
    writeBytes(path, bytes);
}

void flipByte(const std::string& path, std::size_t offset) {
    auto bytes = readBytes(path);
    if (offset >= bytes.size()) throw CacheCorrupt("cache helper offset out of range");
    bytes[offset] ^= 1U;
    writeBytes(path, bytes);
}

void mutatePayloadAndRepairChecksum(const std::string& path) {
    auto bytes = readBytes(path);
    std::size_t offset = 8;
    (void)readPod<std::uint32_t>(bytes, offset);
    const auto payload_size = readPod<std::uint64_t>(bytes, offset);
    const auto payload_end = kHeaderBytes + static_cast<std::size_t>(payload_size);
    std::vector<unsigned char> payload(bytes.begin() + kHeaderBytes,
                                       bytes.begin() + payload_end);
    for (const auto& view : sectionViews(payload)) {
        if (view.id != static_cast<std::uint16_t>(CacheSection::CanonicalModel)) continue;
        if (view.size < sizeof(std::uint64_t) + sizeof(std::uint64_t) + 1)
            throw CacheCorrupt("canonical fixture too small");
        const auto string_length_offset = view.body + sizeof(std::uint64_t);
        std::size_t string_offset = string_length_offset;
        const auto length = readPod<std::uint64_t>(payload, string_offset);
        if (length == 0) throw CacheCorrupt("canonical fixture empty");
        payload[string_offset] ^= 1U;
        std::copy(payload.begin(), payload.end(), bytes.begin() + kHeaderBytes);
        const auto sum = checksum(bytes, kHeaderBytes, payload_end);
        std::memcpy(bytes.data() + payload_end, &sum, sizeof(sum));
        writeBytes(path, bytes);
        return;
    }
    throw CacheCorrupt("canonical section missing");
}

void appendBytes(const std::string& path, std::initializer_list<unsigned char> bytes) {
    auto current = readBytes(path);
    current.insert(current.end(), bytes.begin(), bytes.end());
    writeBytes(path, current);
}

void writeCacheWithDeclaredSection(const std::string& path, std::uint64_t declared_size) {
    std::vector<unsigned char> payload;
    appendPod<std::uint16_t>(payload, 0x1234);
    appendPod<std::uint8_t>(payload, 0);
    appendPod<std::uint8_t>(payload, 0);
    appendPod<std::uint64_t>(payload, declared_size);
    std::vector<unsigned char> bytes(std::begin(kMagic), std::end(kMagic));
    appendPod<std::uint32_t>(bytes, kVersion);
    appendPod<std::uint64_t>(bytes, payload.size());
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    appendPod<std::uint32_t>(bytes, checksum(bytes, kHeaderBytes, bytes.size()));
    appendPod<std::uint64_t>(bytes, 0);
    writeBytes(path, bytes);
}

void injectOptionalSection(const std::string& path, std::uint16_t id,
                           std::initializer_list<unsigned char> body) {
    injectSection(path, id, 1, body);
}

void injectRequiredSection(const std::string& path, std::uint16_t id,
                           std::initializer_list<unsigned char> body) {
    injectSection(path, id, 0, body);
}

} // namespace nfnext
