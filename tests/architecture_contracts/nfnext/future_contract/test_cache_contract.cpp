#include "contract_test.hpp"

#if __has_include("nfnext/cache_v2.hpp")
#include "nfnext/cache_v2.hpp"
#include "nfnext/canonical.hpp"
#include <fstream>
#include <random>
using namespace nfnext;

CONTRACT_CASE("cache key includes source model hash") {
    CacheKey a,b; a.source_sha256="aaa"; b.source_sha256="bbb"; REQUIRE_NE(a.digest(),b.digest());
}
CONTRACT_CASE("cache key includes parser semantic version") { CacheKey a,b; a.parser_version="1"; b.parser_version="2"; REQUIRE_NE(a.digest(),b.digest()); }
CONTRACT_CASE("cache key includes compiler semantic version") { CacheKey a,b; a.compiler_version="1"; b.compiler_version="2"; REQUIRE_NE(a.digest(),b.digest()); }
CONTRACT_CASE("cache key includes options affecting semantics") { CacheKey a,b; a.options.connectivity=ConnectivityPolicy::Strict; b.options.connectivity=ConnectivityPolicy::Legacy; REQUIRE_NE(a.digest(),b.digest()); }
CONTRACT_CASE("cache key ignores diagnostics verbosity") { CacheKey a,b; a.options.verbose=false; b.options.verbose=true; REQUIRE_EQ(a.digest(),b.digest()); }
CONTRACT_CASE("cache key includes target ABI where binary code is stored") { CacheKey a,b; a.target_abi="arm64-apple"; b.target_abi="x86_64-linux"; a.contains_native_code=b.contains_native_code=true; REQUIRE_NE(a.digest(),b.digest()); }
CONTRACT_CASE("portable NFIR cache may ignore target ABI") { CacheKey a,b; a.target_abi="arm64"; b.target_abi="x86"; a.contains_native_code=b.contains_native_code=false; REQUIRE_EQ(a.digest(),b.digest()); }

CONTRACT_CASE("save then load preserves canonical bytes exactly") { auto model=makeCanonicalCacheFixture(); auto p=tempPath("roundtrip"); CacheV2::save(model,p); auto x=CacheV2::load(p); REQUIRE_EQ(x.canonicalBytes(),model.canonicalBytes()); removeFile(p); }
CONTRACT_CASE("two saves of same model are byte identical") { auto model=makeCanonicalCacheFixture(); auto a=tempPath("a"),b=tempPath("b"); CacheV2::save(model,a); CacheV2::save(model,b); REQUIRE_EQ(readBytes(a),readBytes(b)); removeFile(a);removeFile(b); }
CONTRACT_CASE("unordered metadata insertion order cannot perturb bytes") { auto a=makeCanonicalCacheFixture(),b=a; a.metadata["z"]="1";a.metadata["a"]="2";b.metadata["a"]="2";b.metadata["z"]="1"; auto pa=tempPath("a"),pb=tempPath("b");CacheV2::save(a,pa);CacheV2::save(b,pb);REQUIRE_EQ(readBytes(pa),readBytes(pb));removeFile(pa);removeFile(pb); }

CONTRACT_CASE("truncated header rejects") { auto p=tempPath("trunc"); writeBytes(p,{0x4e,0x46}); REQUIRE_THROWS_AS(CacheV2::load(p),CacheCorrupt); removeFile(p); }
CONTRACT_CASE("wrong magic rejects") { auto p=tempPath("magic"); writeMinimalCache(p,"BADMAGIC"); REQUIRE_THROWS_AS(CacheV2::load(p),CacheCorrupt); removeFile(p); }
CONTRACT_CASE("newer unsupported format rejects explicitly") { auto p=tempPath("newer"); writeCacheVersion(p,99999); REQUIRE_THROWS_AS(CacheV2::load(p),CacheVersionUnsupported); removeFile(p); }
CONTRACT_CASE("older migratable format invokes explicit migration") { auto p=tempPath("old"); writeCacheVersion(p,1); auto r=CacheV2::loadWithReport(p); REQUIRE(r.report.migrated); removeFile(p); }
CONTRACT_CASE("payload checksum mismatch rejects") { auto model=makeCanonicalCacheFixture(); auto p=tempPath("crc");CacheV2::save(model,p);flipByte(p,128);REQUIRE_THROWS_AS(CacheV2::load(p),CacheCorrupt);removeFile(p); }
CONTRACT_CASE("semantic fingerprint mismatch rejects even with repaired checksum") { auto model=makeCanonicalCacheFixture();auto p=tempPath("fp");CacheV2::save(model,p);mutatePayloadAndRepairChecksum(p);REQUIRE_THROWS_AS(CacheV2::load(p),CacheSemanticMismatch);removeFile(p); }
CONTRACT_CASE("trailing garbage rejects under strict reader") { auto model=makeCanonicalCacheFixture();auto p=tempPath("garbage");CacheV2::save(model,p);appendBytes(p,{1,2,3});REQUIRE_THROWS_AS(CacheV2::load(p),CacheCorrupt);removeFile(p); }
CONTRACT_CASE("oversized declared section rejects before allocation") { auto p=tempPath("oversize");writeCacheWithDeclaredSection(p,std::numeric_limits<std::uint64_t>::max());REQUIRE_THROWS_AS(CacheV2::load(p),CacheCorrupt);removeFile(p); }

CONTRACT_CASE("cache writer uses atomic rename") { auto model=makeCanonicalCacheFixture();auto p=tempPath("atomic"); CacheFaultInjector fault(CacheFaultPoint::BeforeRename); REQUIRE_THROWS_AS(CacheV2::save(model,p,&fault),CacheIoError); REQUIRE(!fileExists(p)); }
CONTRACT_CASE("failed replacement preserves previously valid cache") { auto m1=makeCanonicalCacheFixture(),m2=m1;m2.model_name="other";auto p=tempPath("replace");CacheV2::save(m1,p);auto before=readBytes(p);CacheFaultInjector f(CacheFaultPoint::BeforeRename);REQUIRE_THROWS_AS(CacheV2::save(m2,p,&f),CacheIoError);REQUIRE_EQ(readBytes(p),before);removeFile(p); }
CONTRACT_CASE("reader tolerates concurrent completed writer via immutable snapshot") { auto m=makeCanonicalCacheFixture();auto p=tempPath("concurrent");CacheV2::save(m,p);for(int i=0;i<1000;++i)REQUIRE_EQ(CacheV2::load(p).semanticFingerprint(),m.semanticFingerprint());removeFile(p); }

CONTRACT_CASE("cache sections are length-delimited and skippable") { auto m=makeCanonicalCacheFixture();auto p=tempPath("section");CacheV2::save(m,p);auto index=CacheV2::inspect(p);REQUIRE(index.hasSection(CacheSection::MoleculeTypes));REQUIRE(index.hasSection(CacheSection::RuleFamilies));removeFile(p); }
CONTRACT_CASE("unknown optional section can be skipped") { auto m=makeCanonicalCacheFixture();auto p=tempPath("unknown");CacheV2::save(m,p);injectOptionalSection(p,0x7777,{1,2,3});REQUIRE_NO_THROW(CacheV2::load(p));removeFile(p); }
CONTRACT_CASE("unknown required section rejects") { auto m=makeCanonicalCacheFixture();auto p=tempPath("required");CacheV2::save(m,p);injectRequiredSection(p,0x7777,{1,2,3});REQUIRE_THROWS_AS(CacheV2::load(p),CacheVersionUnsupported);removeFile(p); }

CONTRACT_CASE("cache loader enforces configurable byte budget") { auto m=makeLargeCacheFixture(100000);auto p=tempPath("budget");CacheV2::save(m,p);CacheLoadOptions o;o.max_bytes=1024;REQUIRE_THROWS_AS(CacheV2::load(p,o),CacheBudgetExceeded);removeFile(p); }
CONTRACT_CASE("cache loader enforces configurable object-count budget") { auto m=makeLargeCacheFixture(100000);auto p=tempPath("count");CacheV2::save(m,p);CacheLoadOptions o;o.max_rules=100;REQUIRE_THROWS_AS(CacheV2::load(p,o),CacheBudgetExceeded);removeFile(p); }

CONTRACT_CASE("random single-bit corruptions are always detected") { auto m=makeCanonicalCacheFixture();auto p=tempPath("fuzz");CacheV2::save(m,p);auto original=readBytes(p);std::mt19937_64 rng(1);for(int i=0;i<1000;++i){auto bytes=original;auto bit=rng()%(bytes.size()*8);bytes[bit/8]^=static_cast<unsigned char>(1u<<(bit%8));writeBytes(p,bytes);REQUIRE_THROWS_AS(CacheV2::load(p),CacheError);}removeFile(p); }

CONTRACT_MAIN("cache")
#else
#error "RED CONTRACT: implement robust persistent cache v2 and invalidation contract"
#endif
