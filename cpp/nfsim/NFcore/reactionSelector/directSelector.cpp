/*
 * DirectSelector.cpp
 *
 *  Created on: Jul 23, 2009
 *      Author: msneddon
 */



#include "reactionSelector.hh"

using namespace std;
using namespace NFcore;




DirectSelector::DirectSelector(vector <ReactionClass *> &rxns, System *sys) :
	ReactionSelector(sys)
{
	this->Atot = 0;
	this->n_reactions = rxns.size();
	this->reactionClassList = new ReactionClass *[n_reactions];
	for(int r=0; r<n_reactions; r++) {
		reactionClassList[r] = rxns.at(r);
		Atot += reactionClassList[r]->get_a();
	}
}



DirectSelector::~DirectSelector()
{
	Atot = 0;
	n_reactions = 0;
	delete [] reactionClassList;
}

double DirectSelector::refactorPropensities()
{
	Atot = 0;
	for(int r=0; r<n_reactions; r++) {
		Atot += reactionClassList[r]->update_a();
	}
	return Atot;
}


double DirectSelector::update(ReactionClass *r,double oldA, double newA)
{
	Atot-=oldA;
	Atot+=newA;
	return Atot;
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


double DirectSelector::updateBatch(vector<ReactionClass *> &rxns)
{
	for (vector<ReactionClass *>::const_iterator it = rxns.begin();
			it != rxns.end(); ++it) {
		ReactionClass *r = *it;
		if (r == 0)
			continue;
		double oldA = r->get_a();
		double newA = r->update_a();
		Atot -= oldA;
		Atot += newA;
	}
	return Atot;
}


double DirectSelector::updateBatch(
		vector<ReactionClass *> &rxns, const vector<double> &oldAs)
{
	for (std::size_t i = 0; i < rxns.size(); ++i) {
		ReactionClass *r = rxns[i];
		if (r == 0)
			continue;
		double oldA = i < oldAs.size() ? oldAs[i] : r->get_a();
		double newA = r->update_a();
		Atot -= oldA;
		Atot += newA;
	}
	return Atot;
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


double DirectSelector::updateCompactPartnerPoolBatch(
		const vector<ReactionClass *> &rxns,
		int oldPoolSize, int newPoolSize,
		unsigned long long deferredGeneration)
{
	if (oldPoolSize == newPoolSize)
		return Atot;
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

	//WARNING - DO NOT USE THE DEFAULT C++ RANDOM NUMBER GENERATOR FOR THIS STEP
	// - IT INTRODUCES SMALL NUMERICAL ERRORS CAUSING THE ORDER OF RXNS TO
	//   AFFECT SIMULATION RESULTS
	for(int r=0; r<n_reactions; r++) {
		a_sum += reactionClassList[r]->get_a();
		if(randNum <= a_sum)
		{
			rc = reactionClassList[r];
			return (randNum-last_a_sum);
		}
		last_a_sum = a_sum;
	}

	this->refactorPropensities();
	return getNextReactionClass(rc);

	//cerr<<"Error in Direct Reaction Selector: randNum exceeds a_sum!!!"<<endl;
	//cerr<<"randNum: "<<randNum<<"  a_sum: "<< a_sum<<" running a_tot:"<<Atot<<endl;
	//return -1;
}


double DirectSelector::getAtot()
{
	return Atot;
}
