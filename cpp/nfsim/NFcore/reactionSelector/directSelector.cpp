/*
 * DirectSelector.cpp
 *
 *  Created on: Jul 23, 2009
 *      Author: msneddon
 */



#include "reactionSelector.hh"

#if defined(_MSC_VER)
#include <intrin.h>
#endif

using namespace std;
using namespace NFcore;

namespace {

unsigned int directSelectorTrailingZeroCount(std::uint64_t value)
{
#if defined(_MSC_VER)
	unsigned long bit = 0;
	_BitScanForward64(&bit, value);
	return static_cast<unsigned int>(bit);
#else
	return static_cast<unsigned int>(__builtin_ctzll(value));
#endif
}

/* Active bits normally remain unchanged during a compact batch.  Avoiding a
 * redundant store matters because the sparse scan reads these words directly. */
inline void directSelectorUpdateActiveBit(
		std::uint64_t &word, std::uint64_t bit, bool wasActive, bool isActive)
{
	if (wasActive == isActive)
		return;
	if (isActive)
		word |= bit;
	else
		word &= ~bit;
}

}


double ReactionSelector::updateBatch(vector<ReactionClass *> &rxns)
{
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		ReactionClass *r = *it;
		if (r == 0)
			continue;
		double oldA = r->get_a();
		double newA = r->update_a();
		update(r, oldA, newA);
	}
	return getAtot();
}


double ReactionSelector::updateBatch(
		vector<ReactionClass *> &rxns, const vector<double> &oldAs)
{
	for (std::size_t i = 0; i < rxns.size(); ++i) {
		ReactionClass *r = rxns[i];
		if (r == 0)
			continue;
		double oldA = i < oldAs.size() ? oldAs[i] : r->get_a();
		double newA = r->update_a();
		update(r, oldA, newA);
	}
	return getAtot();
}


double ReactionSelector::updateCompactPartnerPoolBatch(
		const vector<ReactionClass *> &rxns,
		int oldPoolSize, int newPoolSize,
		unsigned long long deferredGeneration)
{
	if (oldPoolSize == newPoolSize)
		return getAtot();
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		ReactionClass *r = *it;
		if (r == 0 || (deferredGeneration != 0 &&
				r->hasDeferredMembershipUpdate(deferredGeneration)))
			continue;
		double coefficient = r->getCompactPartnerPoolCoefficient();
		double oldA = coefficient == 0.0 ? r->get_a()
				: coefficient * static_cast<double>(oldPoolSize);
		double newA = r->update_a_for_compact_partner_pool(newPoolSize);
		update(r, oldA, newA);
	}
	return getAtot();
}




DirectSelector::DirectSelector(vector <ReactionClass *> &rxns, System *sys) :
	ReactionSelector(sys)
{
	this->Atot = 0;
	this->n_reactions = rxns.size();
	this->reactionIndexMode = -1;
	this->reactionClassList = new ReactionClass *[n_reactions];
	this->selectionBlockSize = 16;
	this->selectionBlockPropensities.assign(
			(static_cast<std::size_t>(n_reactions) + selectionBlockSize - 1) /
					selectionBlockSize, 0.0);
	this->reactionPropensities.assign(static_cast<std::size_t>(n_reactions), 0.0);
	this->sparseSelectionSafe = n_reactions > 0;
	this->compactPoolGroupByReaction.assign(
			static_cast<std::size_t>(n_reactions), -1);
	this->compactPoolCoefficients.assign(
			static_cast<std::size_t>(n_reactions), 0.0);
	for(int r=0; r<n_reactions; r++) {
		reactionClassList[r] = rxns.at(r);
		double propensity = reactionClassList[r]->get_a();
		reactionPropensities[static_cast<std::size_t>(r)] = propensity;
		Atot += propensity;
		selectionBlockPropensities[static_cast<std::size_t>(r) /
				selectionBlockSize] += propensity;
		if (!reactionClassList[r]->supportsSparseSelection())
			sparseSelectionSafe = false;
	}
	if (sparseSelectionSafe) {
		activeReactionBits.assign(
				(static_cast<std::size_t>(n_reactions) + 63) / 64, 0);
		for (int r=0; r<n_reactions; r++) {
			if (reactionPropensities[static_cast<std::size_t>(r)] != 0.0)
				activeReactionBits[static_cast<std::size_t>(r) >> 6] |=
					(std::uint64_t(1) << (r & 63));
		}
		for (int r = 0; r < n_reactions; ++r) {
			ReactionClass *reaction = reactionClassList[r];
			if (!reaction->supportsCompactPartnerPoolScale())
				continue;
			CompactPartnerPool *pool = reaction->getCompactPartnerPool();
			if (pool == 0 || !pool->supportsBatchUpdate())
				continue;
			bool everyRegisteredReactionSupportsScale = true;
			const vector<ReactionClass *> &registered =
					pool->getRegisteredReactions();
			for (vector<ReactionClass *>::const_iterator it = registered.begin();
					it != registered.end(); ++it) {
				if (*it == 0 || !(*it)->supportsCompactPartnerPoolScale()) {
					everyRegisteredReactionSupportsScale = false;
					break;
				}
			}
			if (!everyRegisteredReactionSupportsScale)
				continue;
			int groupIndex = findCompactPoolGroup(pool);
			if (groupIndex < 0) {
				CompactPoolSelectionGroup group;
				group.pool = pool;
				group.poolSize = pool->size();
				group.blockCoefficients.assign(
						selectionBlockPropensities.size(), 0.0);
				compactPoolSelectionGroups.push_back(group);
				groupIndex = static_cast<int>(compactPoolSelectionGroups.size() - 1);
			}
			std::size_t reactionIndex = static_cast<std::size_t>(r);
			CompactPoolSelectionGroup &group =
					compactPoolSelectionGroups[static_cast<std::size_t>(groupIndex)];
			compactPoolGroupByReaction[reactionIndex] = groupIndex;
			group.reactionIndices.push_back(r);
			double coefficient = reaction->getCompactPartnerPoolCoefficient();
			compactPoolCoefficients[reactionIndex] = coefficient;
			group.totalCoefficient += coefficient;
			group.blockCoefficients[reactionIndex / selectionBlockSize] +=
					coefficient;
		}
	} else {
		vector<double>().swap(reactionPropensities);
	}
}



DirectSelector::~DirectSelector()
{
	Atot = 0;
	n_reactions = 0;
	delete [] reactionClassList;
	sparseSelectionSafe = false;
	activeReactionBits.clear();
	reactionPropensities.clear();
	compactPoolGroupByReaction.clear();
	compactPoolCoefficients.clear();
	compactPoolSelectionGroups.clear();
}


int DirectSelector::findCompactPoolGroup(CompactPartnerPool *pool) const
{
	if (pool == 0)
		return -1;
	for (std::size_t i = 0; i < compactPoolSelectionGroups.size(); ++i) {
		if (compactPoolSelectionGroups[i].pool == pool)
			return static_cast<int>(i);
	}
	return -1;
}


void DirectSelector::updateCompactPoolActiveBits(
		const CompactPoolSelectionGroup &group, bool active)
{
	if (!sparseSelectionSafe)
		return;
	for (vector<int>::const_iterator it = group.reactionIndices.begin();
			it != group.reactionIndices.end(); ++it) {
		int reaction = *it;
		bool isActive = active &&
				compactPoolCoefficients[static_cast<std::size_t>(reaction)] != 0.0;
		std::uint64_t &word =
				activeReactionBits[static_cast<std::size_t>(reaction) >> 6];
		std::uint64_t bit = std::uint64_t(1) << (reaction & 63);
		if (isActive)
			word |= bit;
		else
			word &= ~bit;
	}
}


void DirectSelector::applyCompactPoolGroupSize(
		int groupIndex, int newPoolSize)
{
	CompactPoolSelectionGroup &group =
			compactPoolSelectionGroups[static_cast<std::size_t>(groupIndex)];
	if (group.poolSize == newPoolSize)
		return;
	double delta = static_cast<double>(newPoolSize - group.poolSize);
	Atot += group.totalCoefficient * delta;
	for (std::size_t block = 0; block < group.blockCoefficients.size(); ++block)
		selectionBlockPropensities[block] +=
				group.blockCoefficients[block] * delta;
	bool crossedZero = (group.poolSize == 0) != (newPoolSize == 0);
	group.poolSize = newPoolSize;
	if (crossedZero)
		updateCompactPoolActiveBits(group, newPoolSize != 0);
}


void DirectSelector::synchronizeCompactPoolGroup(int groupIndex)
{
	CompactPoolSelectionGroup &group =
			compactPoolSelectionGroups[static_cast<std::size_t>(groupIndex)];
	if (group.pool != 0)
		applyCompactPoolGroupSize(groupIndex, group.pool->size());
}


double DirectSelector::getSelectionPropensity(std::size_t reaction) const
{
	if (reaction < compactPoolGroupByReaction.size()) {
		int groupIndex = compactPoolGroupByReaction[reaction];
		if (groupIndex >= 0)
			return compactPoolCoefficients[reaction] *
					static_cast<double>(compactPoolSelectionGroups[
							static_cast<std::size_t>(groupIndex)].poolSize);
	}
	return reactionPropensities[reaction];
}


double DirectSelector::refactorPropensities()
{
	Atot = 0;
	std::fill(selectionBlockPropensities.begin(),
			selectionBlockPropensities.end(), 0.0);
	if (sparseSelectionSafe)
		std::fill(activeReactionBits.begin(), activeReactionBits.end(), 0);
	for (vector<CompactPoolSelectionGroup>::iterator it =
			compactPoolSelectionGroups.begin();
			it != compactPoolSelectionGroups.end(); ++it) {
		it->poolSize = it->pool == 0 ? 0 : it->pool->size();
		it->totalCoefficient = 0.0;
		std::fill(it->blockCoefficients.begin(),
				it->blockCoefficients.end(), 0.0);
	}
	for(int r=0; r<n_reactions; r++) {
		double propensity = reactionClassList[r]->update_a();
		if (sparseSelectionSafe) {
			reactionPropensities[static_cast<std::size_t>(r)] = propensity;
			int groupIndex = compactPoolGroupByReaction[
					static_cast<std::size_t>(r)];
			if (groupIndex >= 0) {
				double coefficient = reactionClassList[r]->
						getCompactPartnerPoolCoefficient();
				compactPoolCoefficients[static_cast<std::size_t>(r)] = coefficient;
				CompactPoolSelectionGroup &group = compactPoolSelectionGroups[
						static_cast<std::size_t>(groupIndex)];
				group.totalCoefficient += coefficient;
				group.blockCoefficients[static_cast<std::size_t>(r) /
						selectionBlockSize] += coefficient;
			}
		}
		Atot += propensity;
		selectionBlockPropensities[static_cast<std::size_t>(r) /
				selectionBlockSize] += propensity;
		if (sparseSelectionSafe && propensity != 0.0)
			activeReactionBits[static_cast<std::size_t>(r) >> 6] |=
					(std::uint64_t(1) << (r & 63));
	}
	return Atot;
}


double DirectSelector::update(ReactionClass *r,double oldA, double newA)
{
	if (r == 0)
		return Atot;
	if (reactionIndexMode < 0) {
		reactionIndexMode = 1;
		for (int i = 0; i < n_reactions; ++i) {
			if (reactionClassList[i]->getRxnId() != i) {
				reactionIndexMode = 0;
				break;
			}
		}
	}
	int reaction = r->getRxnId();
	if (reaction < 0 || reaction >= n_reactions ||
			reactionClassList[reaction] != r || reactionIndexMode == 0) {
		/* System::prepareForSimulation() assigns the global reaction id before
		 * runtime updates.  Retain a cold fallback for direct test callers. */
		for (reaction = 0; reaction < n_reactions; ++reaction) {
			if (reactionClassList[reaction] == r)
				break;
		}
	}
	if (reaction >= 0 && reaction < n_reactions) {
		std::size_t reactionIndex = static_cast<std::size_t>(reaction);
		int groupIndex = reactionIndex < compactPoolGroupByReaction.size()
				? compactPoolGroupByReaction[reactionIndex] : -1;
		if (groupIndex >= 0) {
			synchronizeCompactPoolGroup(groupIndex);
			CompactPoolSelectionGroup &group = compactPoolSelectionGroups[
					static_cast<std::size_t>(groupIndex)];
			double oldCoefficient = compactPoolCoefficients[reactionIndex];
			double oldEffective = oldCoefficient *
					static_cast<double>(group.poolSize);
			double newCoefficient = r->getCompactPartnerPoolCoefficient();
			Atot -= oldEffective;
			Atot += newA;
			std::size_t block = reactionIndex / selectionBlockSize;
			selectionBlockPropensities[block] -= oldEffective;
			selectionBlockPropensities[block] += newA;
			group.totalCoefficient += newCoefficient - oldCoefficient;
			group.blockCoefficients[block] += newCoefficient - oldCoefficient;
			compactPoolCoefficients[reactionIndex] = newCoefficient;
			if (sparseSelectionSafe) {
				reactionPropensities[reactionIndex] = newA;
				std::uint64_t &word = activeReactionBits[reactionIndex >> 6];
				std::uint64_t bit = std::uint64_t(1) << (reaction & 63);
				directSelectorUpdateActiveBit(word, bit,
						oldEffective != 0.0, newA != 0.0);
			}
			return Atot;
		}
	}
	Atot-=oldA;
	Atot+=newA;
	if (reaction >= 0 && reaction < n_reactions) {
		std::size_t block = static_cast<std::size_t>(reaction) /
				selectionBlockSize;
		selectionBlockPropensities[block] -= oldA;
		selectionBlockPropensities[block] += newA;
		if (sparseSelectionSafe)
			reactionPropensities[static_cast<std::size_t>(reaction)] = newA;
	}
	if (sparseSelectionSafe && reaction >= 0 && reaction < n_reactions) {
		std::uint64_t &word =
				activeReactionBits[static_cast<std::size_t>(reaction) >> 6];
		std::uint64_t bit = std::uint64_t(1) << (reaction & 63);
		directSelectorUpdateActiveBit(word, bit,
				oldA != 0.0, newA != 0.0);
	}
	return Atot;
}


double DirectSelector::updateBatch(vector<ReactionClass *> &rxns)
{
	if (reactionIndexMode < 0) {
		reactionIndexMode = 1;
		for (int i = 0; i < n_reactions; ++i) {
			if (reactionClassList[i]->getRxnId() != i) {
				reactionIndexMode = 0;
				break;
			}
		}
	}
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		ReactionClass *r = *it;
		if (r == 0)
			continue;
		int reaction = r->getRxnId();
		bool indexedReaction = sparseSelectionSafe &&
				reaction >= 0 && reaction < n_reactions &&
				reactionClassList[reaction] == r;
		double oldA = indexedReaction
				? reactionPropensities[static_cast<std::size_t>(reaction)]
				: r->get_a();
		double newA = r->update_a();
		update(r, oldA, newA);
	}
	return Atot;
}


double DirectSelector::updateBatch(
		vector<ReactionClass *> &rxns, const vector<double> &oldAs)
{
	if (reactionIndexMode < 0) {
		reactionIndexMode = 1;
		for (int i = 0; i < n_reactions; ++i) {
			if (reactionClassList[i]->getRxnId() != i) {
				reactionIndexMode = 0;
				break;
			}
		}
	}
	for (std::size_t i = 0; i < rxns.size(); ++i) {
		ReactionClass *r = rxns[i];
		if (r == 0)
			continue;
		double oldA = i < oldAs.size() ? oldAs[i] : r->get_a();
		double newA = r->update_a();
		update(r, oldA, newA);
	}
	return Atot;
}


double DirectSelector::updateCompactPartnerPoolBatch(
		const vector<ReactionClass *> &rxns,
		int oldPoolSize, int newPoolSize,
		unsigned long long deferredGeneration)
{
	if (oldPoolSize == newPoolSize)
		return Atot;
	CompactPartnerPool *pool = 0;
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		if (*it != 0) {
			pool = (*it)->getCompactPartnerPool();
			if (pool != 0)
				break;
		}
	}
	int groupIndex = findCompactPoolGroup(pool);
	if (groupIndex >= 0) {
		/* Deferred batches update changed reactions first, synchronizing the
		 * group to the post-event pool size.  Ordinary pool-only changes use the
		 * exact lazy scale here. */
		(void)deferredGeneration;
		applyCompactPoolGroupSize(groupIndex, newPoolSize);
		return Atot;
	}
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		ReactionClass *r = *it;
		if (r == 0 || (deferredGeneration != 0 &&
				r->hasDeferredMembershipUpdate(deferredGeneration)))
			continue;
		double coefficient = r->getCompactPartnerPoolCoefficient();
		double oldA = coefficient == 0.0 ? r->get_a()
				: coefficient * static_cast<double>(oldPoolSize);
		double newA = r->update_a_for_compact_partner_pool(newPoolSize);
		update(r, oldA, newA);
	}
	return Atot;
}



double DirectSelector::getNextReactionClass(ReactionClass *&rc)
{
	double randNum = sys_->getRNG().random(Atot);

	double a_sum=0, last_a_sum=0;
	/* Compact EnergyPattern reactions can omit zero-rate entries while keeping
	 * reaction order.  Prefix blocks bound the scan and retain a dense fallback
	 * for reaction classes that cannot prove this invariant. */
	if (sparseSelectionSafe && selectionBlockPropensities.size() > 1) {
		for (std::size_t block = 0;
				block < selectionBlockPropensities.size(); ++block) {
			double blockPropensity = selectionBlockPropensities[block];
			if (randNum <= a_sum + blockPropensity) {
				std::size_t first = block * selectionBlockSize;
				std::size_t last = std::min<std::size_t>(
						first + selectionBlockSize,
						static_cast<std::size_t>(n_reactions));
				if (selectionBlockSize <= 64 &&
						(first >> 6) == ((last - 1) >> 6)) {
					unsigned int bitOffset =
						static_cast<unsigned int>(first & 63);
					std::uint64_t active = activeReactionBits[first >> 6] >>
							bitOffset;
					unsigned int bitCount =
							static_cast<unsigned int>(last - first);
					if (bitCount < 64)
						active &= (std::uint64_t(1) << bitCount) - 1;
					while (active != 0) {
						unsigned int bit = directSelectorTrailingZeroCount(active);
						std::size_t r = first + bit;
						active &= active - 1;
						a_sum += getSelectionPropensity(r);
						if (randNum <= a_sum) {
							rc = reactionClassList[r];
							return (randNum-last_a_sum);
						}
						last_a_sum = a_sum;
					}
				} else {
					for (std::size_t r = first; r < last; ++r) {
						if ((activeReactionBits[r >> 6] &
								(std::uint64_t(1) << (r & 63))) == 0)
							continue;
						a_sum += getSelectionPropensity(r);
						if (randNum <= a_sum) {
							rc = reactionClassList[r];
							return (randNum-last_a_sum);
						}
						last_a_sum = a_sum;
					}
				}
				/* Re-entering the next block after an exact scan handles the rare
				 * one-ulp difference between block and scalar prefix sums. */
				last_a_sum = a_sum;
				continue;
			}
			a_sum += blockPropensity;
			last_a_sum = a_sum;
		}
		this->refactorPropensities();
		return getNextReactionClass(rc);
	}

	//WARNING - DO NOT USE THE DEFAULT C++ RANDOM NUMBER GENERATOR FOR THIS STEP
	// - IT INTRODUCES SMALL NUMERICAL ERRORS CAUSING THE ORDER OF RXNS TO
	//   AFFECT SIMULATION RESULTS
	if (sparseSelectionSafe) {
		for(std::size_t wordIndex=0; wordIndex<activeReactionBits.size();
				++wordIndex) {
			std::uint64_t active = activeReactionBits[wordIndex];
			while (active != 0) {
				unsigned int bit = directSelectorTrailingZeroCount(active);
				unsigned int r = static_cast<unsigned int>((wordIndex << 6) + bit);
				active &= active - 1;
				a_sum += getSelectionPropensity(r);
				if(randNum <= a_sum)
				{
					rc = reactionClassList[r];
					return (randNum-last_a_sum);
				}
				last_a_sum = a_sum;
			}
		}
	} else {
		for(int r=0; r<n_reactions; r++) {
			a_sum += reactionClassList[r]->get_a();
			if(randNum <= a_sum)
			{
				rc = reactionClassList[r];
				return (randNum-last_a_sum);
			}
			last_a_sum = a_sum;
		}
	}

	this->refactorPropensities();
	return getNextReactionClass(rc);

}


double DirectSelector::getAtot()
{
	return Atot;
}
