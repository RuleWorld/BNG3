#include <catch2/catch_test_macros.hpp>
#include "BNGcore.hpp"

using namespace BNGcore;

TEST_CASE("Node::operator==", "[BNGcore][Node]") {
    SECTION("Nodes with same type and state are equal") {
        NodeType type("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        Node node1(type);
        Node node2(type);
        REQUIRE(node1 == node2);
    }

    SECTION("Nodes with different types are not equal") {
        NodeType type1("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        NodeType type2("B", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        Node node1(type1);
        Node node2(type2);
        REQUIRE_FALSE(node1 == node2);
    }

    SECTION("Nodes with different states are not equal") {
        LabelStateType l_state_type("l_state", "state1");
        l_state_type.add_state("state2");
        NodeType type("A", ENTITY_NODE_TYPE, l_state_type);

        Node node1(type);
        Node node2(type);

        State* state1 = l_state_type.get_state_object();
        state1->set_state("state1");

        State* state2 = l_state_type.get_state_object();
        state2->set_state("state2");

        node1.set_state(*state1);
        node2.set_state(*state2);

        REQUIRE_FALSE(node1 == node2);

        delete state1;
        delete state2;
    }

    SECTION("Nodes with wildcard states match any state") {
        LabelStateType l_state_type("l_state", "state1");
        l_state_type.add_state("state2");
        NodeType type("A", ENTITY_NODE_TYPE, l_state_type);

        Node node1(type);
        Node node2(type);

        State* state_wildcard = l_state_type.get_state_object();
        state_wildcard->set_state(WILDCARD_STRING);

        State* state_specific = l_state_type.get_state_object();
        state_specific->set_state("state2");

        node1.set_state(*state_wildcard);
        node2.set_state(*state_specific);

        REQUIRE(node1 == node2);
        REQUIRE(node2 == node1); // symmetry check for wildcard

        delete state_wildcard;
        delete state_specific;
    }

    SECTION("Compartment matching") {
        NodeType type("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        Node node1(type);
        Node node2(type);

        // Empty compartment on pattern (node1) acts as wildcard
        node2.set_compartment("comp1");
        REQUIRE(node1 == node2);

        // Same compartment
        node1.set_compartment("comp1");
        REQUIRE(node1 == node2);

        // Different compartment
        node2.set_compartment("comp2");
        REQUIRE_FALSE(node1 == node2);

        // Pattern specifies compartment, target does not
        node2.set_compartment("");
        REQUIRE_FALSE(node1 == node2);
    }
}

TEST_CASE("PatternGraph canonicalization defines the empty graph", "[BNGcore][PatternGraph]") {
    // Source-derived from akutuva21/bionetgen commit 46da45c4: empty
    // SpeciesGraph values must not index ptn[-1] during canonicalization.
    PatternGraph graph;

    REQUIRE(graph.get_label().empty());
    REQUIRE(graph.is_canonical());
}

TEST_CASE("Node canonical labels retain their exact format", "[BNGcore][Node]") {
    // Source-derived from akutuva21/bionetgen commit b73d9e3d: the
    // allocation reduction must preserve canonical label bytes.
    NodeType type("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
    Node node(type);
    node.set_index(7);

    REQUIRE(node.get_label() == "7:A~<0>");
}

TEST_CASE("PatternGraph BNG2 strings retain their exact format", "[BNGcore][PatternGraph]") {
    // Source-derived from akutuva21/bionetgen commit 556099d3: replacing
    // string streams with append-based assembly must not change .net text.
    PatternGraph graph;
    NodeType typeA("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
    NodeType typeB("B", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
    Node nodeA(typeA);
    Node nodeB(typeB);
    Node* graphNodeA = graph.add_node(nodeA);
    Node* graphNodeB = graph.add_node(nodeB);
    graph.add_edge(graphNodeA, graphNodeB);

    REQUIRE(graph.get_BNG2_string() == "A(B)");
}

namespace {

// Counts the node functions that are alive, so a test can observe whether a
// node type released the ones it owns.
int g_liveNodeFunctions = 0;

class CountingNodeFunction : public NodeFunction {
public:
    CountingNodeFunction() { ++g_liveNodeFunctions; }
    CountingNodeFunction(const CountingNodeFunction&) { ++g_liveNodeFunctions; }
    NodeFunction* clone() const override { return new CountingNodeFunction(*this); }
    ~CountingNodeFunction() override { --g_liveNodeFunctions; }
};

}  // namespace

TEST_CASE("NodeType releases the node functions it owns", "[BNGcore][Node][Lifecycle]") {
    // The edge maps of a node type own the node functions they hold: every
    // entry is created with `new` or with `NodeFunction::clone()`.  A node
    // type that does not release them leaks one function per edge, which
    // the header-scope static node types of BNGcore.hpp did once per
    // translation unit.
    const int liveBefore = g_liveNodeFunctions;
    {
        NodeType type("A", ENTITY_NODE_TYPE, NULL_STATE_TYPE);
        CountingNodeFunction fcn;
        REQUIRE(type.add_edges_in(ENTITY_NODE_TYPE, fcn));
        // The edge map holds a clone of the function next to the original.
        REQUIRE(g_liveNodeFunctions == liveBefore + 2);
    }
    REQUIRE(g_liveNodeFunctions == liveBefore);
}
