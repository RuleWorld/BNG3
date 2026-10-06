#include <catch2/catch_test_macros.hpp>
#include <sstream>
#include <string>
#include <vector>

#include "BNGcore.hpp"

using namespace BNGcore;

namespace {

// Reference implementations: the historical stream-based construction that
// the direct-return implementation replaced.  Each reference reproduces the
// original byte-for-byte semantics, so any divergence in the live code shows
// up as a test failure rather than as a silently different species string.
std::string ref_NodeType_get_label(const std::string& type_name) {
    std::stringstream s;
    s << type_name;
    return s.str();
}

std::string ref_NodeType_get_BNG2_string(const std::string& type_name) {
    std::stringstream s;
    s << ref_NodeType_get_label(type_name);
    return s.str();
}

std::string ref_EntityType_get_BNG2_string(const std::string& type_name) {
    std::stringstream s;
    s << ref_NodeType_get_label(type_name);
    return s.str();
}

// Names that exercise the edges of the construction: empty, single character,
// multi-character, names that look like BNG2 syntax, names long enough to
// defeat small-string optimisation, and names with an embedded NUL (which a
// length-aware insert preserves and a C-string insert would truncate).
const std::vector<std::string> kTypeNames = {
    "",
    "A",
    "egfr",
    "Shc",
    "Sos",
    "Grb2_Sos",
    "Y1068",
    "pY",
    "X",
    "0123456789",
    "veryLongMoleculeTypeNameThatExceedsSmallStringCapacity0123456789",
    "with space",
    "with(paren)",
    "with,comma",
    "with!bang",
    "with~tilde",
    "with\\backslash",
    std::string("with\0nul", 8),
    std::string("trailing\0", 9),
};

}  // namespace

TEST_CASE("NodeType::get_label matches the stream-built reference", "[BNGcore][Node]") {
    for (const auto& name : kTypeNames) {
        CAPTURE(name.size(), name);
        NodeType type(name, NULL_STATE_TYPE);
        CHECK(type.get_label() == ref_NodeType_get_label(name));
        CHECK(type.get_label() == name);
    }
}

TEST_CASE("NodeType::get_BNG2_string matches the stream-built reference", "[BNGcore][Node]") {
    for (const auto& name : kTypeNames) {
        CAPTURE(name.size(), name);
        NodeType type(name, NULL_STATE_TYPE);
        // both modes took the same code path in the original
        CHECK(type.get_BNG2_string(true) == ref_NodeType_get_BNG2_string(name));
        CHECK(type.get_BNG2_string(false) == ref_NodeType_get_BNG2_string(name));
    }
}

TEST_CASE("EntityType::get_BNG2_string matches the stream-built reference",
          "[BNGcore][Node]") {
    for (const auto& name : kTypeNames) {
        CAPTURE(name.size(), name);
        EntityType type(name, ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        CHECK(type.get_BNG2_string(true) == ref_EntityType_get_BNG2_string(name));
        CHECK(type.get_BNG2_string(false) == ref_EntityType_get_BNG2_string(name));
    }
}

TEST_CASE("BondType::get_BNG2_string is empty in both modes", "[BNGcore][Node]") {
    BondType type(BOND_TYPING_FCN);
    CHECK(type.get_BNG2_string(true).empty());
    CHECK(type.get_BNG2_string(false).empty());
}

TEST_CASE("Node::get_label keeps index, type and state segments", "[BNGcore][Node]") {
    LabelStateType l_state_type("l_state", "state1");
    l_state_type.add_state("state2");
    NodeType type("A", ENTITY_NODE_TYPE, l_state_type);

    // multi-character and negative-free indices must render exactly as
    // std::to_string would
    for (int index : {0, 1, 9, 10, 99, 100, 12345}) {
        Node node(type);
        node.set_index(index);
        CHECK(node.get_label() == std::to_string(index) + ":" + "A" + "~<l_state>state1");
    }
}