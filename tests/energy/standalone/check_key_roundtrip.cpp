#include "compile/energy/BarrierTable.hpp"
#include <cstdio>
using namespace bng::compile::energy;
static int failures = 0;
#define CHECK(c) do { if(!(c)){ std::printf("  FAIL line %d: %s\n", __LINE__, #c); ++failures; } } while(0)

static void roundtrip(const ReactionCenterKey& k) {
    ReactionCenterKey back;
    const auto text = k.toString();
    CHECK(ReactionCenterKey::parse(text, back));
    CHECK(back == k);
    CHECK(back.toString() == text);
}

int main() {
    roundtrip(ReactionCenterKey::binding("A","x","B","y"));
    roundtrip(ReactionCenterKey::binding("B","y","A","x"));
    roundtrip(ReactionCenterKey::binding("A","x","A","x"));
    roundtrip(ReactionCenterKey::stateChange("A","s","U","P"));
    roundtrip(ReactionCenterKey::stateChange("A","s","P","U"));
    roundtrip(ReactionCenterKey::stateChange("Rec","Y1","0","2P"));
    // Malformed keys must be rejected, not guessed at.
    ReactionCenterKey k;
    const char* bad[] = {
        "", "bond", "bond:", "bond:A.x", "bond:A.x|", "bond:|A.x",
        "weird:A.x|B.y", "bond:Ax|B.y", "state:A.s|A.s",
        "state:A.s~U|B.s~P",      // mismatched molecule type
        "state:A.s~U|A.t~P",      // mismatched component
        "bond:A.x|B.y|C.z",       // too many halves
        "bond:B.y|A.x",           // non-canonical half order
        "state:A.s~U|A.s~P",      // non-canonical state order (P sorts first)
    };
    for (const char* text : bad) {
        if (ReactionCenterKey::parse(text, k)) {
            std::printf("  FAIL accepted malformed key: '%s' -> %s\n", text, k.toString().c_str());
            ++failures;
        }
    }
    std::printf(failures ? "KEYPARSE: %d failure(s)\n" : "KEYPARSE: all checks passed\n", failures);
    return failures ? 1 : 0;
}
