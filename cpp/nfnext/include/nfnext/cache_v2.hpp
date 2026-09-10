#pragma once

#include "nfnext/canonical.hpp"

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace nfnext {

class CacheError : public std::runtime_error {
public:
    explicit CacheError(const std::string& message) : std::runtime_error(message) {}
};
class CacheCorrupt : public CacheError { public: using CacheError::CacheError; };
class CacheVersionUnsupported : public CacheError { public: using CacheError::CacheError; };
class CacheSemanticMismatch : public CacheError { public: using CacheError::CacheError; };
class CacheIoError : public CacheError { public: using CacheError::CacheError; };
class CacheBudgetExceeded : public CacheError { public: using CacheError::CacheError; };

struct CacheOptions {
    ConnectivityPolicy connectivity{ConnectivityPolicy::Legacy};
    bool verbose{false};
};

struct CacheKey {
    std::string source_sha256;
    std::string parser_version;
    std::string compiler_version;
    CacheOptions options;
    std::string target_abi;
    bool contains_native_code{false};

    std::string digest() const;
};

struct CacheModel {
    std::string model_name;
    std::map<std::string, std::string> metadata;
    std::string canonical_bytes;
    std::size_t rule_count{0};

    std::string canonicalBytes() const;
    std::uint64_t semanticFingerprint() const noexcept;
};

enum class CacheSection : std::uint16_t {
    MoleculeTypes = 1,
    RuleFamilies = 2,
    CanonicalModel = 3,
    Metadata = 4
};

struct CacheIndex {
    std::vector<std::uint16_t> sections;
    bool hasSection(CacheSection section) const noexcept;
};

struct CacheLoadOptions {
    std::uint64_t max_bytes{1ULL << 34};
    std::uint64_t max_rules{1ULL << 32};
};

enum class CacheFaultPoint : std::uint8_t { BeforeRename };

class CacheFaultInjector {
public:
    explicit CacheFaultInjector(CacheFaultPoint point) : point_(point) {}
    bool trips(CacheFaultPoint point) const noexcept { return point_ == point; }

private:
    CacheFaultPoint point_;
};

struct CacheLoadReport {
    bool migrated{false};
};

struct CacheLoadResult {
    CacheModel model;
    CacheLoadReport report;
};

class CacheV2 {
public:
    static void save(const CacheModel& model, const std::string& path,
                     CacheFaultInjector* fault = nullptr);
    static CacheModel load(const std::string& path,
                           const CacheLoadOptions& options = {});
    static CacheLoadResult loadWithReport(const std::string& path,
                                          const CacheLoadOptions& options = {});
    static CacheIndex inspect(const std::string& path);
};

CacheModel makeCanonicalCacheFixture();
CacheModel makeLargeCacheFixture(std::size_t rule_count);
std::string tempPath(const std::string& suffix);
bool fileExists(const std::string& path);
void removeFile(const std::string& path);
std::vector<unsigned char> readBytes(const std::string& path);
void writeBytes(const std::string& path, const std::vector<unsigned char>& bytes);
inline void writeBytes(const std::string& path, std::initializer_list<unsigned char> bytes) {
    writeBytes(path, std::vector<unsigned char>(bytes));
}
void writeMinimalCache(const std::string& path, const std::string& magic);
void writeCacheVersion(const std::string& path, std::uint32_t version);
void flipByte(const std::string& path, std::size_t offset);
void mutatePayloadAndRepairChecksum(const std::string& path);
void appendBytes(const std::string& path, std::initializer_list<unsigned char> bytes);
void writeCacheWithDeclaredSection(const std::string& path, std::uint64_t declared_size);
void injectOptionalSection(const std::string& path, std::uint16_t id,
                           std::initializer_list<unsigned char> body);
void injectRequiredSection(const std::string& path, std::uint16_t id,
                           std::initializer_list<unsigned char> body);

} // namespace nfnext
