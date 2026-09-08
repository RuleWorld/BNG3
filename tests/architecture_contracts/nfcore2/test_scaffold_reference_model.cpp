#include "test_harness.hh"
#include "scaffold.hh"
#include <vector>
#include <random>
using namespace NFcore2;

TEST(dense_and_sparse_scaffolds_match_for_every_position){
    const unsigned N=4096;ScaffoldStore s;auto d=s.create(N,3,SCAFFOLD_DENSE);auto p=s.create(N,3,SCAFFOLD_SPARSE);
    for(unsigned i=0;i<N;++i){unsigned v=(i*37u+11u)%7u;s.setState(d,i,(uint8_t)v);s.setState(p,i,(uint8_t)v);}for(unsigned i=0;i<N;++i)EXPECT_EQ(s.state(d,i),s.state(p,i));
}
TEST(sparse_default_write_elides_materialization){
    ScaffoldStore s;auto p=s.create(1000000,9,SCAFFOLD_SPARSE);for(unsigned i=0;i<10000;++i)s.setState(p,i*97,9);EXPECT_EQ(s.materializedStateCount(p),0u);
}
TEST(sparse_exception_removed_when_restored_to_default){
    ScaffoldStore s;auto p=s.create(1000,4,SCAFFOLD_SPARSE);for(unsigned i=0;i<500;++i)s.setState(p,i,5);EXPECT_EQ(s.materializedStateCount(p),500u);for(unsigned i=0;i<500;++i)s.setState(p,i,4);EXPECT_EQ(s.materializedStateCount(p),0u);
}
TEST(randomized_dense_sparse_differential_200k_operations){
    const unsigned N=8192;ScaffoldStore s;auto d=s.create(N,1,SCAFFOLD_DENSE);auto p=s.create(N,1,SCAFFOLD_SPARSE);std::mt19937 rng(1234567);
    for(unsigned step=0;step<200000;++step){unsigned pos=rng()%N;uint8_t val=(uint8_t)(rng()%8);s.setState(d,pos,val);s.setState(p,pos,val);if((step%997)==0){for(unsigned k=0;k<128;++k){unsigned q=rng()%N;EXPECT_EQ(s.state(d,q),s.state(p,q));}}}
    for(unsigned i=0;i<N;++i)EXPECT_EQ(s.state(d,i),s.state(p,i));
}
TEST(occupancy_reference_set_clear_count){
    const unsigned N=2048;ScaffoldStore s;auto p=s.create(N,0,SCAFFOLD_SPARSE);std::vector<bool> occ(N,false);size_t count=0;
    for(unsigned i=0;i<N;i+=3){MoleculeHandle h(i+1,1);s.setOccupant(p,i,h);occ[i]=true;++count;}EXPECT_EQ(s.occupiedCount(p),count);for(unsigned i=0;i<N;++i)EXPECT_EQ(s.occupant(p,i).valid(),occ[i]);for(unsigned i=0;i<N;i+=6){s.setOccupant(p,i,MoleculeHandle());occ[i]=false;--count;}EXPECT_EQ(s.occupiedCount(p),count);
}
TEST(out_of_bounds_accesses_are_rejected){
    ScaffoldStore s;auto p=s.create(4,0,SCAFFOLD_SPARSE);EXPECT_THROW(s.state(p,4),std::out_of_range);EXPECT_THROW(s.setState(p,4,1),std::out_of_range);EXPECT_THROW(s.occupant(p,4),std::out_of_range);EXPECT_THROW(s.setOccupant(p,4,MoleculeHandle(1,1)),std::out_of_range);
}
TEST(huge_sparse_scaffold_cost_tracks_exceptions_not_length){
    ScaffoldStore s;auto p=s.create(1000000000u,0,SCAFFOLD_SPARSE);for(unsigned i=0;i<1000;++i)s.setState(p,i*999983u,1);EXPECT_EQ(s.materializedStateCount(p),1000u);EXPECT_EQ(s.length(p),1000000000u);
}
