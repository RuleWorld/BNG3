#include "rule_compiler.hh"
#include <map>
#include <sstream>
#include <stdexcept>
#include <cmath>
namespace NFcore2 {
namespace {
std::string keyFor(const RuleInstanceIR& r) {
    std::ostringstream os;
    os << r.matcher.value() << ':' << r.transform.value() << ':'
       << r.matcher_signature << '\x1f' << r.transform_signature;
    return os.str();
}
}
RuleFamilyCompilation RuleFamilyCompiler::compile(const std::vector<RuleInstanceIR>& in) {
    RuleFamilyCompilation out;
    out.instance_to_family.resize(in.size());
    out.instance_to_member.resize(in.size());
    std::map<std::string, std::uint32_t> family_by_key;
    for (std::size_t i=0;i<in.size();++i) {
        if (!std::isfinite(in[i].rate) || in[i].rate < 0.0)
            throw std::invalid_argument("rule rate must be finite and nonnegative");
        const std::string key=keyFor(in[i]);
        std::map<std::string,std::uint32_t>::iterator it=family_by_key.find(key);
        std::uint32_t fi;
        if(it==family_by_key.end()) {
            fi=static_cast<std::uint32_t>(out.families.size());
            family_by_key[key]=fi;
            RuleFamilyDescriptor f; f.name=in[i].name; f.matcher=in[i].matcher; f.transform=in[i].transform; f.uniform_rate=true;
            out.families.push_back(f);
        } else fi=it->second;
        RuleFamilyDescriptor& f=out.families[fi];
        RuleMember m; m.rate=in[i].rate; m.parameter_index=in[i].parameter_index; m.coordinate=in[i].coordinate;
        if(!f.members.empty() && f.members[0].rate != m.rate) f.uniform_rate=false;
        const std::uint32_t mi=static_cast<std::uint32_t>(f.members.size());
        f.members.push_back(m);
        out.instance_to_family[i]=RuleFamilyId(fi); out.instance_to_member[i]=mi;
    }
    return out;
}
}
