#ifndef BASICREACTIONS_HH_
#define BASICREACTIONS_HH_


#include "../NFreactions.hh"




using namespace std;

namespace NFcore
{

	class BasicRxnClass : public ReactionClass {
		public:
			BasicRxnClass(string name, double baseRate, string baseRateName, TransformationSet *transformationSet, System *s);
			virtual ~BasicRxnClass();

			virtual void init();
			virtual void prepareForSimulation();

			//JJT: checks if there's an existing mapping set in *m equal to *ms that maps to this reaction
			virtual int checkForEquality(Molecule *m, MappingSet* ms,int rxnIndex, ReactantList*);

			virtual bool tryToAdd(Molecule *m, unsigned int reactantPos);
			virtual void remove(Molecule *m, unsigned int reactantPos);
			virtual double update_a();
			virtual void notifyRateFactorChange(Molecule * m, int reactantIndex, int rxnListIndex);
			virtual int getReactantCount(unsigned int reactantIndex) const;
			virtual int getCorrectedReactantCount(unsigned int reactantIndex) const;

			virtual void printFullDetails() const;

				protected:
					virtual void pickRuleMonkeyMappingSets(double randNumber) const;
					virtual double exactRuleMonkey_a();

		protected:
			virtual void pickMappingSets(double randNumber) const;
			// AS-6/22
			bool connectivityFlag;

			ReactantList **reactantLists;


				// RuleMonkey buffers to avoid heap allocations
				MappingSet **msPairBuffer;
				mutable vector<pair<int, int> > validPairsBuffer;
	};


	class FunctionalRxnClass : public BasicRxnClass {

		public:
			FunctionalRxnClass(string name, GlobalFunction *gf, TransformationSet *transformationSet, System *s);
			FunctionalRxnClass(string name, CompositeFunction *cf, TransformationSet *transformationSet, System *s);

			virtual ~FunctionalRxnClass();

			virtual double update_a();
			virtual double exactRuleMonkey_a();
			virtual void pickRuleMonkeyMappingSets(double randNumber) const { BasicRxnClass::pickRuleMonkeyMappingSets(randNumber); }
			virtual void printDetails() const;

		protected:
			GlobalFunction *gf;
			CompositeFunction *cf;
			vector<int> reactantCountBuffer;
	};

	class MMRxnClass : public BasicRxnClass {

		public:
			MMRxnClass(string name, double kcat, double Km, TransformationSet *transformationSet, System *s);
			virtual ~MMRxnClass();

			virtual double update_a();
				virtual double exactRuleMonkey_a();
				virtual void pickRuleMonkeyMappingSets(double randNumber) const { BasicRxnClass::pickRuleMonkeyMappingSets(randNumber); }
			virtual void printDetails() const;

		protected:
			double Km;
			double kcat;
			double sFree;
		};

	class SatRxnClass : public BasicRxnClass {
		public:
			SatRxnClass(string name, vector<double> saturationConstants,
			            TransformationSet *transformationSet, System *s);
			virtual ~SatRxnClass();

			virtual double update_a();
			virtual double exactRuleMonkey_a();
			virtual void pickRuleMonkeyMappingSets(double randNumber) const { BasicRxnClass::pickRuleMonkeyMappingSets(randNumber); }
			virtual void printDetails() const;

		protected:
			vector<double> saturationConstants;
	};

	class HillRxnClass : public BasicRxnClass {
		public:
			HillRxnClass(string name, double vmax, double kh, double exponent,
			             TransformationSet *transformationSet, System *s);
			virtual ~HillRxnClass();

			virtual double update_a();
			virtual double exactRuleMonkey_a();
			virtual void pickRuleMonkeyMappingSets(double randNumber) const { BasicRxnClass::pickRuleMonkeyMappingSets(randNumber); }
			virtual void printDetails() const;

		protected:
			double vmax;
			double kh;
			double exponent;
	};


	class DORRxnClass : public ReactionClass {
		public:
			DORRxnClass(
					string name,
					double baseRate,
					string baseRateName,
					TransformationSet *transformationSet,
					CompositeFunction *function,
					vector <string> &lfArgumentPointerNameList,
					System *s);
			/* Internal constructor for reactions whose rate factor is supplied by
			 * another mapping-local evaluator rather than a BNGL local function. */
			DORRxnClass(
					string name,
					double baseRate,
					string baseRateName,
					TransformationSet *transformationSet,
					int dorReactantIndex,
					System *s);
			DORRxnClass(
					string name,
					double baseRate,
					string baseRateName,
					TransformationSet *transformationSet,
					int dorReactantIndex,
					System *s,
					unsigned int reactantListInitialCapacity,
					unsigned int reactantTreeInitialCapacity,
					bool allocateReactantLists);
			virtual ~DORRxnClass();

			virtual void init();
			virtual void prepareForSimulation() {};
			virtual bool tryToAdd(Molecule *m, unsigned int reactantPos);
			virtual void remove(Molecule *m, unsigned int reactantPos);
			virtual double update_a();

			virtual int getDORreactantPosition() const { return DORreactantIndex; };

			//JJT: checks if there's an existing mapping set in *m equal to *ms that maps to this reaction
			virtual int checkForCollision(Molecule *m, MappingSet* ms,int rxnIndex);

			virtual void notifyRateFactorChange(Molecule * m, int reactantIndex, int rxnListIndex);
			virtual int getReactantCount(unsigned int reactantIndex) const;
			virtual int getCorrectedReactantCount(unsigned int reactantIndex) const;

			virtual void printDetails() const;
			virtual void printFullDetails() const {};

			void directAddForDebugging(Molecule *m);
			void printTreeForDebugging();

			static void test1(System *s);

				protected:
					virtual void pickRuleMonkeyMappingSets(double randNumber) const;
					virtual double exactRuleMonkey_a();

		protected:
			MappingSet **msPairBuffer;
			mutable vector<pair<int, int> > validPairsBuffer;

			virtual double evaluateLocalFunctions(MappingSet *ms);
			void refreshTimeDependentLocalFunctions();

			virtual void pickMappingSets(double randNumber) const;

			virtual double pickLocalFunctionParameter(MappingSet *ms, int, vector <MoleculeType *>*, int*);

			mutable vector<double> validWeightsBuffer;

			ReactantList **reactantLists;
			ReactantTree *reactantTree;



			CompositeFunction *cf;
			bool hasRefreshedTimeDependentLocalFunctions;
			double lastTimeDependentLocalFunctionRefresh;

			//Parameters to keep track of local functions
			int DORreactantIndex;

			int n_argMolecules;
			int * argIndexIntoMappingSet;
			Molecule ** argMappedMolecule;
			int * argScope;


			//vector <int> argIndexIntoMappingSet;



			//vector <LocalFunction *> lfList;
			//vector <int> indexIntoMappingSet;
			//vector <double> localFunctionValue;

	};

	/*
	 * Compact Arrhenius energy reaction. This uses the DOR mapping tree to
	 * select a reaction-center molecule with its context-dependent rate factor,
	 * without materializing one reaction class per boolean context state.
	 */
	class EnergyRxnClass : public DORRxnClass {
		public:
			EnergyRxnClass(
					string name,
					double baseRate,
					string baseRateName,
					TransformationSet *transformationSet,
					int dorReactantIndex,
					const EnergyBindingContext &context,
					double phi,
					double RT,
					bool isForward,
					System *s);
			virtual ~EnergyRxnClass();
			virtual bool usesIncrementalMembership() const {
				return simpleMembership;
			}
			virtual bool membershipDecisionIsTypeInvariant() const {
				return simpleMembership;
			}
			virtual bool supportsSparseSelection() const {
				return simpleMembership;
			}
			virtual bool getIncrementalMembershipChange(
					IncrementalMembershipChange &change) const;
			virtual bool getCompactMembershipIndexInfo(
					unsigned int reactantPos,
					int &reactionCenterComponent,
					std::uint64_t &contextComponentMask,
					unsigned int &minimumContextComponents) const;
			virtual bool shouldUpdateMembership(
					Molecule *m, ReactionClass *firedReaction,
					bool directProduct) const;
			virtual bool shouldUpdateMembershipForChange(
					Molecule *m,
					const IncrementalMembershipChange &change) const;
			virtual bool canSkipIndirectMembership(
					ReactionClass *firedReaction) const;
			virtual CompactPartnerPool *getCompactPartnerPool() const {
				return partnerPool;
			}
			virtual bool getCompactPartnerPoolInfo(
					unsigned int reactantPos, int &partnerComponent) const {
				if (!simpleMembership || !isForward || reactantPos != 1 ||
						partnerComponentIndex < 0)
					return false;
				partnerComponent = partnerComponentIndex;
				return true;
			}
			virtual bool refreshCompactPartnerPool(
					Molecule *m, unsigned int reactantPos);
			virtual bool supportsCompactPartnerPoolUpdate() const {
				return simpleMembership && isForward;
			}
			virtual bool supportsCompactPartnerPoolScale() const {
				return simpleMembership && isForward && !useRuleMonkey;
			}
			virtual bool tryToAdd(Molecule *m, unsigned int reactantPos);
			virtual void remove(Molecule *m, unsigned int reactantPos);
			virtual double update_a();
			virtual double get_a() const;
			virtual double getCompactPartnerPoolCoefficient() const;
			virtual double update_a_for_compact_partner_pool(int poolSize);
			virtual int getReactantCount(unsigned int reactantIndex) const;
			virtual int getCorrectedReactantCount(unsigned int reactantIndex) const;

		protected:
			virtual void pickMappingSets(double randNumber) const;
			virtual double evaluateLocalFunctions(MappingSet *ms);
			virtual void pickRuleMonkeyMappingSets(double randNumber) const;
			virtual double exactRuleMonkey_a();

		private:
			vector<EnergyPatternTerm> conditionalTerms;
			vector<int> conditionComponentIndices;
			vector<std::uint64_t> conditionalComponentMasks;
			bool componentMaskFastPath;
			bool simpleMembership;
			int reactionCenterComponentIndex;
			int partnerComponentIndex;
			MoleculeType *partnerMoleculeType;
			CompactPartnerPool *partnerPool;
			MappingSet *compactPartnerMappingSet;
			double compactRateFactor;
			double baseEnergy;
			double phi;
			double RT;
			bool isForward;
			std::uint64_t weightedDependencyMask;
			bool dependencyMaskValid;
			unsigned int minimumConditionalBits;

			bool dependsOnEndpoint(
					MoleculeType *targetMoleculeType,
					MoleculeType *changedMoleculeType,
					int changedComponentIndex) const;
	};

	/* A reaction class with DOR calculations on two reactants.
	 * The rate function must be factored as  f(x,y) = g(x)*h(y)
	 * */
	class DOR2RxnClass : public ReactionClass {
		public:
			DOR2RxnClass(
					string name,
					double baseRate,
					string baseRateName,
					TransformationSet *transformationSet,
					CompositeFunction *function1,
					CompositeFunction *function2,
					vector <string> &lfArgumentPointerNameList1,
					vector <string> &lfArgumentPointerNameList2,
					System *s);
			virtual ~DOR2RxnClass();

			virtual void init();
			virtual void prepareForSimulation() {};
			virtual bool tryToAdd(Molecule *m, unsigned int reactantPos);
			virtual void remove(Molecule *m, unsigned int reactantPos);
			virtual double update_a();

			virtual int getDORreactantPosition()  const { return DORreactantIndex1; };
			virtual int getDORreactantPosition2() const { return DORreactantIndex2; };

			virtual void notifyRateFactorChange(Molecule * m, int reactantIndex, int rxnListIndex);
			virtual int getReactantCount(unsigned int reactantIndex) const;
			virtual int getCorrectedReactantCount(unsigned int reactantIndex) const;

			virtual void printDetails() const;
			virtual void printFullDetails() const {};

			void directAddForDebugging(Molecule *m);
			void printTreeForDebugging();

			static void test1(System *s);

			public:
				virtual void pickRuleMonkeyMappingSets(double randNumber) const;
				virtual double exactRuleMonkey_a();

		protected:
			MappingSet **msPairBuffer;
			mutable vector<pair<int, int> > validPairsBuffer;

			virtual double evaluateLocalFunctions1(MappingSet *ms);
			virtual double evaluateLocalFunctions2(MappingSet *ms);
			void refreshTimeDependentLocalFunctions();

			virtual void pickMappingSets(double randNumber) const;

			mutable vector<double> validWeightsBuffer;

			ReactantList **reactantLists;
			ReactantTree *reactantTree1;
			ReactantTree *reactantTree2;


			CompositeFunction *cf1;
			CompositeFunction *cf2;
			bool hasRefreshedTimeDependentLocalFunctions;
			double lastTimeDependentLocalFunctionRefresh;

			//Parameters to keep track of local functions
			int DORreactantIndex1;
			int DORreactantIndex2;

			int n_argMolecules1;
			int n_argMolecules2;
			int * argIndexIntoMappingSet1;
			int * argIndexIntoMappingSet2;
			Molecule ** argMappedMolecule1;
			Molecule ** argMappedMolecule2;
			int * argScope1;
			int * argScope2;

	};

}







#endif /*BASICREACTIONS_HH_*/
