// RED CONTRACT: parametric/indexed rule-family IR for Rasi/genome models.
#include <catch2/catch_test_macros.hpp>
#include "compile/indexed/IndexedRuleFamily.hpp"

using namespace bng::compile::indexed;

TEST_CASE("affine indexed expression evaluates exactly across domain") {
    IndexDomain d{"i", 1, 1000};
    IndexedExpression e = IndexedExpression::affine("i", 2, -1);
    CHECK(e.evaluate({{"i",1}}) == 1);
    CHECK(e.evaluate({{"i",500}}) == 999);
    CHECK(e.evaluate({{"i",1000}}) == 1999);
}

TEST_CASE("local genome mutation affects only neighboring indexed rules") {
    IndexedRuleFamily family("elongation", {IndexDomain{"i", 1, 9999}});
    family.addReadSite(IndexedSite{"ribosome", IndexedExpression::variable("i")});
    family.addReadSite(IndexedSite{"mrna", IndexedExpression::affine("i",1,1)});
    const auto affected = family.affectedInstances(IndexedSiteInstance{"mrna", 5000});
    CHECK(affected.size() <= 2);
    CHECK(affected.count({{"i",4999}}) == 1);
}

TEST_CASE("boundary query never generates out-of-domain rule instance") {
    IndexedRuleFamily family("move", {IndexDomain{"i", 1, 10}});
    family.addReadSite(IndexedSite{"x", IndexedExpression::affine("i",1,1)});
    const auto affected = family.affectedInstances(IndexedSiteInstance{"x",1});
    for (const auto& assignment : affected) {
        CHECK(assignment.at("i") >= 1);
        CHECK(assignment.at("i") <= 10);
    }
}

TEST_CASE("two index domains have Cartesian logical size without eager materialization") {
    IndexedRuleFamily family("pair", {IndexDomain{"i",1,1000},IndexDomain{"j",1,1000}});
    CHECK(family.logicalInstanceCount()==1000000);
    CHECK(family.materializedInstanceCount()==0);
}

TEST_CASE("inverse affine dependency query returns exact source index") {
    IndexedRuleFamily family("shift", {IndexDomain{"i",1,100}});
    family.addReadSite(IndexedSite{"x",IndexedExpression::affine("i",2,1)});
    auto affected=family.affectedInstances(IndexedSiteInstance{"x",51});
    REQUIRE(affected.size()==1);
    CHECK(affected.begin()->at("i")==25);
}

TEST_CASE("nonintegral inverse affine dependency has no affected instance") {
    IndexedRuleFamily family("shift", {IndexDomain{"i",1,100}});
    family.addReadSite(IndexedSite{"x",IndexedExpression::affine("i",2,0)});
    CHECK(family.affectedInstances(IndexedSiteInstance{"x",51}).empty());
}

TEST_CASE("invalid index domain is rejected") {
    CHECK_THROWS(IndexDomain("i",10,1));
}

TEST_CASE("multiple read expressions deduplicate same affected instance") {
    IndexedRuleFamily family("dup", {IndexDomain{"i",1,10}});
    family.addReadSite(IndexedSite{"x",IndexedExpression::variable("i")});
    family.addReadSite(IndexedSite{"x",IndexedExpression::variable("i")});
    auto affected=family.affectedInstances(IndexedSiteInstance{"x",5});
    CHECK(affected.size()==1);
}
