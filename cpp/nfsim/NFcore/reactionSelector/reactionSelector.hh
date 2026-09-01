/*
 * reactionSelector.hh
 *
 *  Created on: Jul 23, 2009
 *      Author: msneddon
 */

#ifndef REACTIONSELECTOR_HH_
#define REACTIONSELECTOR_HH_



#include "../NFcore.hh"
//#include <vector>


using namespace std;


namespace NFcore
{
	//Forward Declarations
	class ReactionClass;
	class CompactPartnerPool;


	// Abstract Interface Class for the Reaction Selection Algorithm
	class ReactionSelector {

		public:

			//Initializations and basic functionality
			ReactionSelector() : sys_(nullptr) {};
			explicit ReactionSelector(System *sys) : sys_(sys) {};
			virtual ~ReactionSelector() {};

			virtual double refactorPropensities() = 0;


			virtual double update(ReactionClass *r,double oldA, double newA) = 0;
			virtual double updateBatch(vector<ReactionClass *> &rxns);
			virtual double updateBatch(vector<ReactionClass *> &rxns,
					const vector<double> &oldAs);
			virtual double updateCompactPartnerPoolBatch(
					const vector<ReactionClass *> &rxns,
					int oldPoolSize, int newPoolSize,
					unsigned long long deferredGeneration);
			virtual double getNextReactionClass(ReactionClass *&rc) = 0;
			virtual double getAtot() = 0;

		protected:
			System *sys_;  // Pointer to System for accessing per-instance RNG
	};


	class DirectSelector : public ReactionSelector {

		public:
			//Initializations and basic functionality
			DirectSelector(vector <ReactionClass *> &rxns, System *sys);
			virtual ~DirectSelector();

			virtual double refactorPropensities();


			virtual double update(ReactionClass *r,double oldA, double newA);
			virtual double updateBatch(vector<ReactionClass *> &rxns);
			virtual double updateBatch(vector<ReactionClass *> &rxns,
					const vector<double> &oldAs);
			virtual double updateCompactPartnerPoolBatch(
					const vector<ReactionClass *> &rxns,
					int oldPoolSize, int newPoolSize,
					unsigned long long deferredGeneration);
			virtual double getNextReactionClass(ReactionClass *&rc);
			virtual double getAtot();


		protected:
			struct CompactPoolSelectionGroup {
				CompactPoolSelectionGroup() : pool(0), poolSize(0),
						totalCoefficient(0.0), blockCoefficients(), reactionIndices() {}
				CompactPartnerPool *pool;
				int poolSize;
				double totalCoefficient;
				vector<double> blockCoefficients;
				vector<int> reactionIndices;
			};

			int findCompactPoolGroup(CompactPartnerPool *pool) const;
			void applyCompactPoolGroupSize(int groupIndex, int newPoolSize);
			void synchronizeCompactPoolGroup(int groupIndex);
			void updateCompactPoolActiveBits(
					const CompactPoolSelectionGroup &group,
					bool active);
			double getSelectionPropensity(std::size_t reaction) const;

			double Atot;
			int n_reactions;
			ReactionClass ** reactionClassList;
			bool sparseSelectionSafe;
			/* -1 until the first update; 1 when prepared reaction IDs match
			 * selector positions, 0 for direct-selector compatibility callers. */
			int reactionIndexMode;
			vector<std::uint64_t> activeReactionBits;
			unsigned int selectionBlockSize;
			vector<double> selectionBlockPropensities;
			/* Sparse selectors read propensities frequently.  Keep a contiguous
			 * mirror; grouped compact rules derive selection values from their
			 * coefficient and shared pool size. */
			vector<double> reactionPropensities;
			/* For factorized compact forward rules, retain weighted-side
			 * coefficients while shared partner-pool size is selector state. */
			vector<int> compactPoolGroupByReaction;
			vector<double> compactPoolCoefficients;
			vector<CompactPoolSelectionGroup> compactPoolSelectionGroups;

		};


	class LogClassSelector : public ReactionSelector {

		public:
			//Initializations and basic functionality
			LogClassSelector(vector <ReactionClass *> &rxns, System *sys);
			virtual ~LogClassSelector();

			virtual double refactorPropensities();


			virtual double update(ReactionClass *r,double oldA, double newA);
			virtual double getNextReactionClass(ReactionClass *&rc);
			virtual double getAtot();


		protected:

			int calculateClass(double a);

			void place(ReactionClass *r,int logClass,double a);

			void setLogClassToActive(int logClass);
			void setLogClassToInactive(int logClass);


			// The absolute maximum log class
			int maxClassLimit;
			int minClassLimit;
			int totalLogClassCount;

			//the current range of log classes that we have to loop over
			int currentHighClass;
			int currentLowClass;


			// A 2d array of the logClasses
			ReactionClass *** logClassList;

			// A 1d array of the logClasses sizes
			int *logClassSize;
			int *logClassCapacity;


			//An array to keep track of the log classes with positive values
			int *activeLogClasses;
			bool *isLogClassActive;
			int n_activeLogClasses;



			// A 1d array of the propensity sum of the logClass
			double *logClassPropensity;



			int *mapRxnIdToLogClass;
			int *mapRxnIdToLogClassPosition;




			double Atot;
			int n_reactions;
			ReactionClass ** reactionClassList;

	};



}








#endif /* REACTIONSELECTOR_HH_ */
