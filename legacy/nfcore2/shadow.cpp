#include "shadow.hh"
#include <cmath>
#include <sstream>

namespace NFcore2 {
namespace {
bool sameDouble(double a,double b,double tol){return std::fabs(a-b)<=tol;}
ShadowMismatch mismatch(const std::string& field,const std::string& detail){ShadowMismatch m;m.mismatch=true;m.field=field;m.detail=detail;return m;}
}
SemanticHasher::SemanticHasher():hash_(1469598103934665603ULL){}
void SemanticHasher::addU64(std::uint64_t v){for(int i=0;i<8;++i){hash_^=(v&0xffu);hash_*=1099511628211ULL;v>>=8;}}
void SemanticHasher::addI64(std::int64_t v){addU64(static_cast<std::uint64_t>(v));}
void SemanticHasher::addString(const std::string& s){for(std::size_t i=0;i<s.size();++i){hash_^=static_cast<unsigned char>(s[i]);hash_*=1099511628211ULL;}hash_^=0xffu;hash_*=1099511628211ULL;}

ShadowMismatch ShadowComparator::compareState(const ShadowState& a,const ShadowState& b,double tol){
    if(!sameDouble(a.time,b.time,tol))return mismatch("time","simulation times differ");
    if(a.populations!=b.populations)return mismatch("populations","population vectors differ");
    if(a.observables.size()!=b.observables.size())return mismatch("observables","observable counts differ");
    for(std::size_t i=0;i<a.observables.size();++i){if(a.observables[i].name!=b.observables[i].name)return mismatch("observables","observable names/order differ");if(!sameDouble(a.observables[i].value,b.observables[i].value,tol))return mismatch("observables","observable values differ");}
    if(a.semantic_hash!=b.semantic_hash)return mismatch("semantic_hash","canonical molecular/scaffold state differs");
    return ShadowMismatch();
}
ShadowMismatch ShadowComparator::compareEvent(const ShadowEvent& a,const ShadowEvent& b,double tol){
    if(a.rule_name!=b.rule_name)return mismatch("rule_name","selected logical rules differ");
    if(a.logical_member!=b.logical_member)return mismatch("logical_member","selected rule-family members differ");
    if(!sameDouble(a.propensity,b.propensity,tol))return mismatch("propensity","selected propensities differ");
    ShadowMismatch m=compareState(a.before,b.before,tol);if(m.mismatch){m.field="before."+m.field;return m;}
    m=compareState(a.after,b.after,tol);if(m.mismatch){m.field="after."+m.field;return m;}return ShadowMismatch();
}
}
