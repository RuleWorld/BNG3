#include "test_harness.hh"
#include "shadow.hh"
using namespace NFcore2;
static ShadowState base(){ShadowState s;s.time=2.5;s.semantic_hash=123;s.populations={1,2,3};s.observables.push_back({"a",4.0});s.observables.push_back({"b",5.0});return s;}
TEST(shadow_identical_states_match){for(int i=0;i<1000;++i){auto a=base(),b=a;EXPECT_FALSE(ShadowComparator::compareState(a,b).mismatch);}}
TEST(shadow_each_population_index_is_detected){for(unsigned i=0;i<3;++i){auto a=base(),b=a;b.populations[i]++;auto x=ShadowComparator::compareState(a,b);EXPECT_TRUE(x.mismatch);EXPECT_TRUE(!x.field.empty());}}
TEST(shadow_each_observable_value_is_detected){for(unsigned i=0;i<2;++i){auto a=base(),b=a;b.observables[i].value+=1;EXPECT_TRUE(ShadowComparator::compareState(a,b).mismatch);}}
TEST(shadow_observable_name_mismatch_detected){auto a=base(),b=a;b.observables[0].name="z";EXPECT_TRUE(ShadowComparator::compareState(a,b).mismatch);}
TEST(shadow_hash_mismatch_detected){auto a=base(),b=a;b.semantic_hash^=1;EXPECT_TRUE(ShadowComparator::compareState(a,b).mismatch);}
TEST(shadow_tolerance_applies_to_floating_values){auto a=base(),b=a;b.time+=1e-8;b.observables[0].value+=1e-8;EXPECT_FALSE(ShadowComparator::compareState(a,b,1e-7).mismatch);EXPECT_TRUE(ShadowComparator::compareState(a,b,1e-10).mismatch);}
TEST(shadow_event_rule_member_propensity_each_checked){ShadowEvent a,b;a.rule_name=b.rule_name="r";a.logical_member=b.logical_member=4;a.propensity=b.propensity=3.2;a.before=b.before=base();a.after=b.after=base();EXPECT_FALSE(ShadowComparator::compareEvent(a,b).mismatch);b.rule_name="q";EXPECT_TRUE(ShadowComparator::compareEvent(a,b).mismatch);b=a;b.logical_member++;EXPECT_TRUE(ShadowComparator::compareEvent(a,b).mismatch);b=a;b.propensity+=1;EXPECT_TRUE(ShadowComparator::compareEvent(a,b).mismatch);}
TEST(semantic_hasher_is_order_sensitive_and_repeatable){SemanticHasher a,b,c;a.addString("x");a.addU64(1);b.addString("x");b.addU64(1);c.addU64(1);c.addString("x");EXPECT_EQ(a.value(),b.value());EXPECT_NE(a.value(),c.value());}
TEST(semantic_hasher_distinguishes_signed_values){SemanticHasher a,b;a.addI64(-1);b.addI64(1);EXPECT_NE(a.value(),b.value());}
