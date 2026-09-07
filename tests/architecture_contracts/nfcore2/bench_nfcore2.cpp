#include "rule_compiler.hh"
#include "scaffold.hh"
#include "scheduler.hh"
#include <chrono>
#include <iostream>
#include <vector>
using namespace NFcore2;
int main(){
  const std::size_t n=1000000;
  std::vector<RuleInstanceIR> rules(n);
  for(std::size_t i=0;i<n;++i){rules[i].name="elongation";rules[i].matcher_signature="ribo+free_next";rules[i].transform_signature="move+1";rules[i].matcher=MatcherId(0);rules[i].transform=TransformProgramId(0);rules[i].rate=1.0;rules[i].coordinate=(std::uint32_t)i;}
  std::chrono::steady_clock::time_point t0=std::chrono::steady_clock::now();
  RuleFamilyCompilation c=RuleFamilyCompiler::compile(rules);
  std::chrono::steady_clock::time_point t1=std::chrono::steady_clock::now();
  ScaffoldStore sc;ScaffoldId sid=sc.create(100000000,0,SCAFFOLD_SPARSE);sc.setState(sid,1234567,1);sc.setOccupant(sid,7654321,MoleculeHandle(1,1));
  std::chrono::steady_clock::time_point t2=std::chrono::steady_clock::now();
  double compile_ms=std::chrono::duration<double,std::milli>(t1-t0).count();
  double scaffold_ms=std::chrono::duration<double,std::milli>(t2-t1).count();
  std::cout<<"instances="<<n<<" families="<<c.families.size()<<" members="<<c.families[0].members.size()<<" compile_ms="<<compile_ms<<"\n";
  std::cout<<"genome_length="<<sc.length(sid)<<" materialized_states="<<sc.materializedStateCount(sid)<<" occupied="<<sc.occupiedCount(sid)<<" setup_ms="<<scaffold_ms<<"\n";
}
