#ifndef NFSIM_PROFILE_HH
#define NFSIM_PROFILE_HH

#include <chrono>
#include <ctime>
#include <map>
#include <ostream>
#include <string>

namespace NFcore {

typedef std::chrono::steady_clock::time_point ProfileTime;

enum ProfileConnectivityContext {
    PROFILE_CONNECTIVITY_OTHER = 0,
    PROFILE_CONNECTIVITY_MATCHING,
    PROFILE_CONNECTIVITY_PRODUCT_PREPARATION,
    PROFILE_CONNECTIVITY_TRANSFORMATION,
    PROFILE_CONNECTIVITY_COMPLEX_MAINTENANCE,
    PROFILE_CONNECTIVITY_LOCAL_FUNCTION,
    PROFILE_CONNECTIVITY_CONTEXT_COUNT
};

static const unsigned int PROFILE_HISTOGRAM_BUCKETS = 65;

inline ProfileTime profileNow()
{
    return std::chrono::steady_clock::now();
}

inline double profileElapsedSeconds(const ProfileTime &start)
{
    return std::chrono::duration<double>(profileNow() - start).count();
}

const char *profileConnectivityContextName(ProfileConnectivityContext context);

struct ProfileConnectivityKey {
    unsigned long long topologyGeneration;
    unsigned long long moleculeCount;
    unsigned long long edgeCount;
    unsigned long long minimumMoleculeId;
    unsigned long long maximumMoleculeId;
    unsigned long long componentSignature;

    bool operator<(const ProfileConnectivityKey &other) const;
};

struct ProfileConnectivityStats {
    ProfileConnectivityStats();

    unsigned long long traversalCalls;
    unsigned long long moleculeVisits;
    unsigned long long edgeVisits;
    double elapsedSeconds;
    unsigned long long fireSamples;
    unsigned long long moleculeMaximum;
    unsigned long long edgeMaximum;
    unsigned long long moleculeHistogram[PROFILE_HISTOGRAM_BUCKETS];
    unsigned long long edgeHistogram[PROFILE_HISTOGRAM_BUCKETS];
    unsigned long long traversalMaximum;
    unsigned long long traversalHistogram[PROFILE_HISTOGRAM_BUCKETS];
    unsigned long long componentMoleculeMaximum;
    unsigned long long componentMoleculeHistogram[PROFILE_HISTOGRAM_BUCKETS];
    unsigned long long topologyChangedBeforeCalls;
    unsigned long long topologyChangedBeforeFireSamples;
    unsigned long long membershipUpdatesBeforeCalls;
    unsigned long long membershipUpdatesBeforeFireSamples;
    unsigned long long equivalentPriorContextCalls[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
};

struct ProfileReactionStats {
    ProfileReactionStats();

    int rxnId;
    std::string name;
    unsigned long long fireCalls;
    unsigned long long nullEvents;
    unsigned long long candidateChecks;
    unsigned long long membershipUpdates;
    unsigned long long templateCompareCalls;
    unsigned long long connectivityMoleculeVisits;
    unsigned long long connectivityEdgeVisits;
    unsigned long long bindCalls;
    unsigned long long unbindCalls;
    unsigned long long complexMaintenanceCalls;
    unsigned long long complexMaintenanceMolecules;
    unsigned long long affectedComplexes;
    unsigned long long affectedComplexMolecules;
    unsigned long long canonicalLabelCalls;
    unsigned long long canonicalLabelNodes;
    unsigned long long canonicalLabelEdges;
    unsigned long long nautyCalls;
    unsigned long long mappingPushes;
    unsigned long long mappingPops;
    unsigned long long mappingRemoves;
    unsigned long long mappingConfirms;
    unsigned long long reactantListExpansions;
    unsigned long long reactantTreeExpansions;
    unsigned long long reactantListExpandedSlots;
    unsigned long long reactantTreeExpandedSlots;
    unsigned long long transformationCalls;
    unsigned long long productPreparationCalls;
    unsigned long long productPreparationMolecules;
    unsigned long long productCollectionCalls;
    unsigned long long productCollectionMolecules;
    unsigned long long observableRemovalMolecules;
    unsigned long long observableAdditionMolecules;
    unsigned long long localFunctionComponentCandidates;
    unsigned long long localFunctionComponentReuses;
    double fireCpuSeconds;
    double membershipUpdateCpuSeconds;
    double templateCompareCpuSeconds;
    double connectivityCpuSeconds;
    double bindCpuSeconds;
    double unbindCpuSeconds;
    double complexMaintenanceCpuSeconds;
    double canonicalLabelCpuSeconds;
    double reactantListExpansionCpuSeconds;
    double reactantTreeExpansionCpuSeconds;
    double transformationCpuSeconds;
    double productPreparationCpuSeconds;
    double productCollectionCpuSeconds;
    double observableRemovalCpuSeconds;
    double observableAdditionCpuSeconds;
    ProfileConnectivityStats connectivityByContext[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
};

class NFsimProfile {
public:
    NFsimProfile();

    void enable(const std::string &outputPath);
    bool isEnabled() const { return enabled; }
    void reset();

    void recordPhase(const std::string &phase, clock_t elapsed);
    void beginReactionFire(int rxnId, const std::string &name);
    void recordReactionFire(int rxnId, const std::string &name,
                            clock_t elapsed, bool nullEvent);
    void recordMatchCandidate() {
        if (!enabled || !activeReaction || activeStats == 0) return;
        ++activeStats->candidateChecks;
    }
    void recordMembershipUpdate() {
        if (!enabled || !activeReaction || activeStats == 0) return;
        ++activeStats->membershipUpdates;
        ++activeMembershipUpdates;
    }
    void recordMembershipPhase(double elapsed);
    bool isReactionActive() const {
        return enabled && activeReaction && activeStats != 0;
    }
    void beginTemplateCompare() {
        if (!isReactionActive()) return;
        ++activeStats->templateCompareCalls;
        if (templateCompareDepth == 0) templateCompareStart = profileNow();
        ++templateCompareDepth;
    }
    void endTemplateCompare() {
        if (!isReactionActive() || templateCompareDepth <= 0) return;
        --templateCompareDepth;
        if (templateCompareDepth == 0) {
            double elapsed = profileElapsedSeconds(templateCompareStart);
            activeStats->templateCompareCpuSeconds += elapsed;
            templateCompareStart = ProfileTime();
        }
    }
    void recordConnectivity(double elapsed,
                            unsigned long long moleculesVisited,
                            unsigned long long edgeVisits,
                            ProfileConnectivityContext context);
    void recordConnectivity(double elapsed,
                            unsigned long long moleculesVisited,
                            unsigned long long edgeVisits,
                            ProfileConnectivityContext context,
                            unsigned long long minimumMoleculeId,
                            unsigned long long maximumMoleculeId,
                            unsigned long long componentSignature);
    void recordTopologyMutation() {
        if (!isReactionActive()) return;
        ++activeTopologyMutationCalls;
    }
    void recordLocalFunctionComponentCandidate(bool alreadyCovered) {
        if (!isReactionActive()) return;
        ++activeStats->localFunctionComponentCandidates;
        if (alreadyCovered)
            ++activeStats->localFunctionComponentReuses;
    }
    ProfileConnectivityContext beginConnectivityContext(
        ProfileConnectivityContext context) {
        ProfileConnectivityContext previous = connectivityContext;
        connectivityContext = context;
        return previous;
    }
    void endConnectivityContext(ProfileConnectivityContext previous) {
        connectivityContext = previous;
    }
    ProfileConnectivityContext getConnectivityContext() const {
        return connectivityContext;
    }
    void recordBind(double elapsed);
    void recordUnbind(double elapsed);
    void recordComplexMaintenance(double elapsed,
                                  unsigned long long moleculesTouched);
    void recordAffectedComplexes(unsigned long long complexes,
                                 unsigned long long molecules);
    void recordCanonicalLabel(double elapsed,
                              unsigned long long nodes,
                              unsigned long long edges,
                              bool nautyCalled);
    void recordMappingPush() {
        if (!isReactionActive()) return;
        ++activeStats->mappingPushes;
    }
    void recordMappingPop() {
        if (!isReactionActive()) return;
        ++activeStats->mappingPops;
    }
    void recordMappingRemove() {
        if (!isReactionActive()) return;
        ++activeStats->mappingRemoves;
    }
    void recordMappingConfirm() {
        if (!isReactionActive()) return;
        ++activeStats->mappingConfirms;
    }
    void recordReactantListExpansion(unsigned long long expandedSlots,
                                     double elapsed);
    void recordReactantTreeExpansion(unsigned long long expandedSlots,
                                     double elapsed);
    void recordTransformation(double elapsed);
    void recordProductPreparation(double elapsed,
                                  unsigned long long moleculesPrepared);
    void recordProductCollection(double elapsed,
                                unsigned long long moleculesAdded);
    void recordObservableRemoval(double elapsed,
                                 unsigned long long molecules);
    void recordObservableAddition(double elapsed,
                                  unsigned long long molecules);

    bool write() const;
    void write(std::ostream &output) const;

private:
    static double seconds(clock_t elapsed) {
        return static_cast<double>(elapsed) / static_cast<double>(CLOCKS_PER_SEC);
    }
    static std::string cleanField(const std::string &value);
    static void setReactionIdentity(ProfileReactionStats &stats,
                                    int rxnId, const std::string &name);

    bool enabled;
    std::string outputPath;
    std::map<std::string, double> phaseCpuSeconds;
    std::map<int, ProfileReactionStats> reactionStats;
    bool activeReaction;
    ProfileReactionStats *activeStats;
    int templateCompareDepth;
    ProfileTime templateCompareStart;
    ProfileConnectivityContext connectivityContext;
    unsigned long long activeConnectivityMolecules[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
    unsigned long long activeConnectivityEdges[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
    unsigned long long activeConnectivityCalls[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
    bool activeConnectivityTopologyChanged[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
    bool activeConnectivityMembershipObserved[
        PROFILE_CONNECTIVITY_CONTEXT_COUNT];
    unsigned long long activeTopologyMutationCalls;
    unsigned long long activeMembershipUpdates;
    std::map<ProfileConnectivityKey, unsigned int> connectivityHistory;

    void recordConnectivityInternal(
        double elapsed,
        unsigned long long moleculesVisited,
        unsigned long long edgeVisits,
        ProfileConnectivityContext context,
        unsigned long long minimumMoleculeId,
        unsigned long long maximumMoleculeId,
        unsigned long long componentSignature,
        bool hasComponentMetadata);
    void recordConnectivityFireSamples(ProfileReactionStats &stats);
};

}

#endif
