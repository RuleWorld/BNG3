#include "engine.hh"
#include <algorithm>
#include <stdexcept>
namespace NFcore2 {
std::vector<MatcherId> Engine::affectedMatchers(const FeatureDelta& d) const {
    std::vector<MatcherId> out; const DependencyIndex& dep=state_.model().dependencies();
    for(std::size_t i=0;i<d.changed.size();++i){std::pair<const MatcherId*,const MatcherId*> r=dep.dependents(d.changed[i]);if(r.first)out.insert(out.end(),r.first,r.second);}
    std::sort(out.begin(),out.end());out.erase(std::unique(out.begin(),out.end()),out.end());return out;
}
std::vector<RuleFamilyId> Engine::affectedFamilies(const FeatureDelta& d) const {
    const std::vector<MatcherId> ms=affectedMatchers(d); std::vector<RuleFamilyId> out;
    for(std::size_t i=0;i<ms.size();++i){const std::vector<RuleFamilyId>& fs=state_.model().familiesForMatcher(ms[i]);out.insert(out.end(),fs.begin(),fs.end());}
    std::sort(out.begin(),out.end());out.erase(std::unique(out.begin(),out.end()),out.end());return out;
}
bool Engine::fire(RuleFamilyId f,std::uint32_t member,MatchContext& c,FeatureDelta& d){
    const RuleFamilyDescriptor& fam=state_.model().ruleFamilies().at(f.value());if(member>=fam.members.size())return false;
    ++counters_.matcher_evaluations;
    if(!executable_.matchers().at(fam.matcher).evaluate(state_,scaffolds_,c)){++counters_.rejected_fires;return false;}
    d.clear();executable_.transforms().at(fam.transform).execute(state_,scaffolds_,c,d);
    ++counters_.events;counters_.feature_deltas += static_cast<std::uint64_t>(d.changed.size());return true;
}
double Engine::evaluateRate(RuleFamilyId f, std::uint32_t member,
                            const MatchContext& context) const {
    const RuleFamilyDescriptor& family = state_.model().ruleFamilies().at(f.value());
    if (member >= family.members.size()) throw std::out_of_range("family member");
    return family.members[member].rate_law.evaluate(
        state_, context, family.members[member].rate);
}
}
