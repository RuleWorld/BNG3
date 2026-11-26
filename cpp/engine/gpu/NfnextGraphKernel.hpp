#pragma once

#include "engine/gpu/NfnextGpuBackend.hpp"
#include "engine/gpu/NfnextUnaryStateKernel.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace bng::engine::detail {

constexpr std::uint32_t kGpuMaxSitesPerMolecule = 8;
constexpr std::uint32_t kGpuMaxObsPatternNodes = 4;
constexpr std::uint32_t kGpuMaxObsPatternBonds = 4;

// Site constraint kinds for GPU graph pattern matching.
enum : std::uint8_t {
    kGpuConstraintState = 0,
    kGpuConstraintFree = 1,
    kGpuConstraintBound = 2,
};

// Action kinds for GPU graph rewriting.
enum : std::uint8_t {
    kGpuActionSetState = 0,
    kGpuActionBind = 1,
    kGpuActionUnbind = 2,
    kGpuActionCreate = 3,
    kGpuActionDestroy = 4,
    kGpuActionDestroyComplex = 5,
};

// Bytecode VM opcodes for GPU dynamic/global/local functional rate laws.
enum : std::uint8_t {
    kGpuVmConst = 0,
    kGpuVmObservable = 1,
    kGpuVmAdd = 2,
    kGpuVmSub = 3,
    kGpuVmMul = 4,
    kGpuVmDiv = 5,
    kGpuVmPow = 6,
    kGpuVmNeg = 7,
    kGpuVmExp = 8,
    kGpuVmLog = 9,
    kGpuVmSqrt = 10,
    kGpuVmSin = 11,
    kGpuVmCos = 12,
    kGpuVmTan = 13,
    kGpuVmAbs = 14,
    kGpuVmMin = 15,
    kGpuVmMax = 16,
    kGpuVmLess = 17,
    kGpuVmLessEq = 18,
    kGpuVmGreater = 19,
    kGpuVmGreaterEq = 20,
    kGpuVmEqual = 21,
    kGpuVmNotEqual = 22,
    kGpuVmJumpIfZero = 23,
    kGpuVmJump = 24,
};

struct alignas(4) GpuSiteConstraint {
    std::uint16_t site{0};
    std::uint8_t kind{0};
    std::uint8_t pad{0};
    std::int32_t state{0};
};
static_assert(sizeof(GpuSiteConstraint) == 8);

// A 1-node or 2-node-bonded reactant component anchored on node 0.
struct alignas(4) GpuMatchListDef {
    std::int32_t anchorType{0};
    std::int32_t partnerType{-1}; // -1 => single-node pattern
    std::uint32_t node0ConstraintOffset{0};
    std::uint32_t node0ConstraintCount{0};
    std::uint32_t node1ConstraintOffset{0};
    std::uint32_t node1ConstraintCount{0};
    std::uint16_t bondSite0{0};
    std::uint16_t bondSite1{0};
    std::uint32_t listOffset{0}; // offset in per-trajectory mlItems/mlPos arrays
    std::uint32_t listCapacity{0};
};
static_assert(sizeof(GpuMatchListDef) == 36);

struct alignas(4) GpuRuleAction {
    std::uint8_t kind{0};
    std::uint8_t pad{0};
    std::uint16_t targetNode{0};
    std::uint16_t site{0};
    std::uint16_t partnerNode{0};
    std::uint16_t partnerSite{0};
    std::uint16_t reserved{0};
    std::int32_t value{0}; // new state or created molecule type
};
static_assert(sizeof(GpuRuleAction) == 16);

struct alignas(4) GpuRuleFilter {
    std::uint32_t termOffset{0};
    std::uint32_t termCount{0};
    std::uint16_t reactantNode{0};
    std::uint8_t include{1};
    std::uint8_t pad{0};
};
static_assert(sizeof(GpuRuleFilter) == 12);

struct alignas(4) GpuGraphRule {
    std::uint32_t matchList0{0};
    std::uint32_t matchList1{0xFFFFFFFFu}; // 0xFFFFFFFFu => unimolecular / single-component
    std::uint32_t actionOffset{0};
    std::uint32_t actionCount{0};
    std::uint32_t vmOffset{0};
    std::uint32_t vmLen{0};
    float rate{0.0f};
    std::uint8_t isTwoComponent{0};
    std::uint8_t isInterchangeable{0};
    std::uint8_t isDynamicRate{0};
    std::uint8_t hasLocalObservable{0};
    std::uint32_t createdCount{0};
    std::uint32_t filterOffset{0};
    std::uint16_t filterCount{0};
    std::uint8_t isTotalRate{0};
    std::uint8_t pad0{0};
};
static_assert(sizeof(GpuGraphRule) == 44);

struct alignas(4) GpuVmInstr {
    std::uint8_t op{0};
    std::uint8_t pad0{0};
    std::uint16_t pad1{0};
    std::uint32_t index{0}; // observable index or jump target
    float value{0.0f};
};
static_assert(sizeof(GpuVmInstr) == 12);

struct alignas(4) GpuObsPatternNode {
    std::int32_t molType{0};
    std::uint32_t constraintOffset{0};
    std::uint32_t constraintCount{0};
};
static_assert(sizeof(GpuObsPatternNode) == 12);

struct alignas(4) GpuObsPatternBond {
    std::uint16_t firstNode{0};
    std::uint16_t firstSite{0};
    std::uint16_t secondNode{0};
    std::uint16_t secondSite{0};
};
static_assert(sizeof(GpuObsPatternBond) == 8);

struct alignas(4) GpuObsTermDef {
    std::uint32_t nodeOffset{0};
    std::uint32_t nodeCount{0};
    std::uint32_t bondOffset{0};
    std::uint32_t bondCount{0};
    std::uint32_t weight{1};
    std::uint32_t pad{0};
};
static_assert(sizeof(GpuObsTermDef) == 24);

struct alignas(4) GpuObsDef {
    std::uint32_t termOffset{0};
    std::uint32_t termCount{0};
    std::uint8_t isSpecies{0};
    std::uint8_t pad0{0};
    std::uint16_t pad1{0};
};
static_assert(sizeof(GpuObsDef) == 12);

struct NfnextGraphPlan {
    std::uint32_t numTypes{0};
    std::uint32_t maxSites{0};
    std::uint32_t totalCapacity{0};
    std::uint32_t totalMatchListSlots{0};

    std::vector<std::uint32_t> typeOffsets;
    std::vector<std::uint32_t> typeCapacities;
    std::vector<std::uint32_t> typeSiteCounts;
    std::vector<std::int32_t> typeDefaultStates; // [numTypes * maxSites]

    // Initial particle state over [0, totalCapacity).
    std::vector<std::int8_t> initAlive;
    std::vector<std::int32_t> initMolType;
    std::vector<std::int32_t> initSiteState;     // [totalCapacity * maxSites]
    std::vector<std::int32_t> initSiteBondMol;   // [totalCapacity * maxSites], -1 if unbound
    std::vector<std::int32_t> initSiteBondSite;  // [totalCapacity * maxSites], -1 if unbound

    std::vector<GpuSiteConstraint> constraints;
    std::vector<GpuMatchListDef> matchLists;
    std::vector<GpuRuleAction> actions;
    std::vector<GpuGraphRule> rules;
    std::vector<GpuRuleFilter> ruleFilters;
    std::vector<GpuVmInstr> vmCode;

    std::vector<GpuObsPatternNode> obsNodes;
    std::vector<GpuObsPatternBond> obsBonds;
    std::vector<GpuObsTermDef> obsTerms;
    std::vector<GpuObsDef> observables;
    std::vector<std::string> observableNames;
};

NfnextDeviceOutput simulateNfnextGraphMetal(
    const NfnextGraphPlan& plan, const NfnextGpuRequest& request);

NfnextDeviceOutput simulateNfnextGraphCuda(
    const NfnextGraphPlan& plan, const NfnextGpuRequest& request);

} // namespace bng::engine::detail
