#include "scheduler.hh"
#include <cmath>
#include <algorithm>
namespace NFcore2 {
void FenwickTree::reset(std::size_t n){tree_.assign(n+1,0.0);values_.assign(n,0.0);}
void FenwickTree::set(std::size_t i,double v){if(i>=values_.size()||v<0.0)throw std::out_of_range("fenwick set");if(!std::isfinite(v))throw std::invalid_argument("fenwick activity must be finite");double d=v-values_[i];values_[i]=v;for(std::size_t x=i+1;x<tree_.size();x+=x&(~x+1))tree_[x]+=d;}
double FenwickTree::prefix(std::size_t count) const {if(count>values_.size())count=values_.size();double s=0.0;for(std::size_t x=count;x>0;x-=x&(~x+1))s+=tree_[x];return s;}
double FenwickTree::total() const {return prefix(values_.size());}
std::size_t FenwickTree::sample(double target) const {const double t=total();if(values_.empty()||target<0.0||target>=t)throw std::out_of_range("fenwick sample");std::size_t idx=0;double acc=0.0;std::size_t bit=1;while((bit<<1)<tree_.size())bit<<=1;for(;bit;bit>>=1){std::size_t next=idx+bit;if(next<tree_.size()&&acc+tree_[next]<=target){idx=next;acc+=tree_[next];}}if(idx>=values_.size())idx=values_.size()-1;return idx;}
HierarchicalScheduler::HierarchicalScheduler(const CompiledModel& m):model_(m),family_tree_(m.ruleFamilies().size()){
    const std::vector<RuleFamilyDescriptor>& fs=m.ruleFamilies();member_trees_.reserve(fs.size());for(std::size_t i=0;i<fs.size();++i)member_trees_.push_back(FenwickTree(fs[i].members.size()));
}
void HierarchicalScheduler::setMemberActivity(RuleFamilyId f,std::uint32_t member,double a){FenwickTree& t=member_trees_.at(f.value());t.set(member,a);family_tree_.set(f.value(),t.total());}
void HierarchicalScheduler::setMemberMultiplicity(RuleFamilyId f,std::uint32_t member,double mult){if(!std::isfinite(mult))throw std::invalid_argument("multiplicity must be finite");if(mult<0.0)throw std::out_of_range("negative multiplicity");const RuleFamilyDescriptor& fam=model_.ruleFamilies().at(f.value());if(member>=fam.members.size())throw std::out_of_range("family member");setMemberActivity(f,member,fam.members[member].rate*mult);}
EventChoice HierarchicalScheduler::sample(double u) const {double total=family_tree_.total();if(!(u>=0.0&&u<1.0)||total<=0.0)throw std::out_of_range("scheduler sample");double x=u*total;std::size_t fi=family_tree_.sample(x);double before=family_tree_.prefix(fi);const FenwickTree& mt=member_trees_[fi];double local=x-before;if(local>=mt.total())local=mt.total()*0.999999999999;EventChoice c;c.family=RuleFamilyId(static_cast<std::uint32_t>(fi));c.member=static_cast<std::uint32_t>(mt.sample(local));return c;}
}
