#include <iostream>
#include <stdexcept>
#include "observable.hh"
#include "../NFfunction/NFfunction.hh"


using namespace std;
using namespace NFcore;





Observable::Observable(string name)
{
	this->obsName = name;
	this->n_templates= 0;
	this->templateMolecules = 0;
	this->n_dependentRxns=0;
	this->dependentRxns= new ReactionClass *[n_dependentRxns];
	this->count=0;
	this->type=Observable::NO_TYPE;
	this->system=0;
}

Observable::~Observable()
{
	delete [] dependentRxns;
	delete [] templateMolecules;

	this->n_templates = 0;
	this->templateMolecules = 0;
	this->n_dependentRxns = 0;
	this->dependentRxns = 0;
}

void Observable::notifyLocalFunctions()
{
	if (system) system->markGlobalLocalFunctionsDirty();
	for (LocalFunction *localFunction : localFunctionReferences) {
		if (localFunction != nullptr) localFunction->refreshObservableCounter();
	}
}

void Observable::clear()
{
	count = 0;
	notifyLocalFunctions();
}

void Observable::add()
{
	//First, we add to our observable count
	count++;

	updateDependentReactions();
	notifyLocalFunctions();
}

/* add multiple new matches to an observable (rather than call 'add' a bunch of times --justin */
/* useful for counters! */
void Observable::add( int n_matches )
{
	//debug
	//cout << "Observable::add( " << n_matches << " )" << endl;

	// First, we add to our observable count
	count += n_matches;

	updateDependentReactions();
	notifyLocalFunctions();
}


void Observable::straightAdd()
{
	count++;
	notifyLocalFunctions();
}

void Observable::straightAdd(int n_matches)
{
	count += n_matches;
	notifyLocalFunctions();
}

void Observable::subtract()
{
	if(count==0){
		cerr << "Error in observable count!! Removing from an empty observable!"
		     << "Observable named: " << obsName << endl;
		throw std::runtime_error("Observable count underflow for observable '" + obsName + "'");
	}

	count--;

	updateDependentReactions();
	notifyLocalFunctions();
}

/* Remove multiple matches fron an observable (rather than call 'subtract' a bunch of times --justin */
/* Necessary to make counters fast! */
void Observable::subtract( int n_matches )
{
	//debug
	//cout << "Observable::subtract( " << n_matches << " )" << endl;

	if (count - n_matches < 0)
	{
		cerr << "Error in observable count!! Removing " << n_matches << " matches will result in a negative match count!"
		     << "Observable named: " << obsName << endl;
		throw std::runtime_error("Observable count underflow for observable '" + obsName + "'");
	}

	// First, we subtract from our observable count
	count -= n_matches;

	updateDependentReactions();
	notifyLocalFunctions();
}

void Observable::straightSubtract()
{
	count--;
	notifyLocalFunctions();
}

void Observable::straightSubtract(int n_matches)
{
	count -= n_matches;
	notifyLocalFunctions();
}

void Observable::updateDependentReactions()
{
	System *s = n_dependentRxns > 0
			? templateMolecules[0]->getMoleculeType()->getSystem() : 0;
	for (int r=0; r<n_dependentRxns; r++)
	{
		dependentRxns[r]->markGlobalObservableDirty();
		/* During a firing this count is of no state the system is in: the
		 * rate is computed when the firing's products are counted again
		 * (issue #115). */
		if (s->holdFiringPropensityUpdate(dependentRxns[r]))
			continue;
		double old_a = dependentRxns[r]->get_a();
		double new_a = dependentRxns[r]->update_a();
		s->update_A_tot(
				dependentRxns[r], old_a, new_a);
	}
}



void Observable::getTemplateMoleculeList(int &n_templates, TemplateMolecule **&tmList)
{
	n_templates = this->n_templates;
	tmList = this->templateMolecules;
}
// AS-2021
void Observable::addReferenceToGlobalFunction(GlobalFunction *f) {
	f->addCounterPointer(&count);
}
void Observable::addReferenceToCompositeFunction(CompositeFunction *f) {
	f->addCounterPointer(&count);
}
void Observable::addReferenceToLocalFunction(LocalFunction *f) {
	if (f == nullptr) return;
	if (std::find(localFunctionReferences.begin(), localFunctionReferences.end(), f) ==
		localFunctionReferences.end()) {
		localFunctionReferences.push_back(f);
	}
}
// AS-2021
void Observable::addReferenceToMyself(mu::Parser *p)
{
	p->DefineVar(obsName,&count);
}
void Observable::addReferenceToMyself(string referenceName, mu::Parser *p)
{
	p->DefineVar(referenceName,&count);
}
void Observable::addDependentRxn(ReactionClass *r)
{
	if (r == nullptr) return;
	for (int i = 0; i < n_dependentRxns; i++) {
		if (dependentRxns[i] == r) {
			r->markReadsObservable();
			return;
		}
	}
	ReactionClass ** newDepRxns = new ReactionClass * [n_dependentRxns+1];
	for(int i=0; i<n_dependentRxns; i++) {
		newDepRxns[i] = dependentRxns[i];
	}
	newDepRxns[n_dependentRxns] = r;
	delete [] dependentRxns;
	dependentRxns = newDepRxns;
	n_dependentRxns++;
	r->markReadsObservable();
}




///////////////////////////////////////////////////////////////////////////////////////////////



MoleculesObservable::MoleculesObservable(string name, TemplateMolecule *tm) :
	Observable(name)
{
	n_templates=1;
	templateMolecules = new TemplateMolecule * [n_templates];
	templateMolecules[0]=tm;

	this->relation = nullptr;
	this->quantity = nullptr;
	this->hasStoichiometricConstraints = false;

	this->type=Observable::MOLECULES;
}
MoleculesObservable::MoleculesObservable(string name, vector <TemplateMolecule *> &tmList) :
	Observable(name)
{
	n_templates=tmList.size();
	templateMolecules = new TemplateMolecule * [n_templates];
	for(int t=0; t<n_templates; t++) {
		templateMolecules[t] = tmList.at(t);
	}

	this->relation = nullptr;
	this->quantity = nullptr;
	this->hasStoichiometricConstraints = false;

	this->type=Observable::MOLECULES;

//	cout<<" creating observable "<< name <<endl;
//	if(this->getName()=="CbpTot")
//	{
//		vector <TemplateMolecule *> tms;
//		TemplateMolecule::traverse(tmList.at(0),tms,false);
//		for(int k=0; k<tms.size(); k++)
//		{
//			tms.at(k)->printDetails(cout);
//		}
//		exit(1);
//	}

	//tmList.at(0)->printDetails(cout);
	//tmList.at(0)->printPattern(cout);
	//cout<<"-------------\n"<<endl;

}

MoleculesObservable::MoleculesObservable(string name, vector <TemplateMolecule *> &tmList, vector <string> &stochRelation, vector <int> &stochQuantity) :
	Observable(name)
{
	n_templates=tmList.size();
	templateMolecules = new TemplateMolecule * [n_templates];
	for(int t=0; t<n_templates; t++) {
		templateMolecules[t] = tmList.at(t);
	}

	relation = new int [n_templates];
	quantity = new int [n_templates];
	hasStoichiometricConstraints = false;

	for(int t=0; t<n_templates; t++) {
		if(stochRelation.at(t).empty()) {
			relation[t]=NO_RELATION;
			quantity[t]=-1;

		} else if (stochRelation.at(t).compare("==")==0) {
			relation[t]=EQUALS;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else if (stochRelation.at(t).compare("!=")==0) {
			relation[t]=NOT_EQUALS;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else if (stochRelation.at(t).compare(">")==0) {
			relation[t]=GREATER_THAN;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else if (stochRelation.at(t).compare("<")==0) {
			relation[t]=LESS_THAN;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else if (stochRelation.at(t).compare(">=")==0) {
			relation[t]=GREATOR_OR_EQUAL_TO;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else if (stochRelation.at(t).compare("<=")==0) {
			relation[t]=LESS_THAN_OR_EQUAL_TO;
			quantity[t]=stochQuantity.at(t);
			hasStoichiometricConstraints = true;

		} else {
			relation[t]=NO_RELATION;
			quantity[t]=-1;
		}
	}

	this->type=Observable::MOLECULES;
}

MoleculesObservable::~MoleculesObservable()
{
	if(relation) delete [] relation;
	if(quantity) delete [] quantity;
}


//NOTE:  cloning a molecule DOES NOT clone any dependent reactions.  You will have to
//add that again to this observable, if there are any.  This is the behaviour, because
//observables are generally only cloned in this way for local functions
Observable * MoleculesObservable::clone() {
	vector <TemplateMolecule *> tmList;
	for(int t=0; t<n_templates; t++)
		tmList.push_back(templateMolecules[t]);

	if (hasStoichiometricConstraints) {
		vector <string> stochRelation;
		vector <int> stochQuantity;
		for (int t=0; t<n_templates; t++) {
			if (relation[t] == NO_RELATION) {
				stochRelation.push_back("");
			} else if (relation[t] == EQUALS) {
				stochRelation.push_back("==");
			} else if (relation[t] == NOT_EQUALS) {
				stochRelation.push_back("!=");
			} else if (relation[t] == GREATER_THAN) {
				stochRelation.push_back(">");
			} else if (relation[t] == LESS_THAN) {
				stochRelation.push_back("<");
			} else if (relation[t] == GREATOR_OR_EQUAL_TO) {
				stochRelation.push_back(">=");
			} else if (relation[t] == LESS_THAN_OR_EQUAL_TO) {
				stochRelation.push_back("<=");
			}
			stochQuantity.push_back(quantity[t]);
		}
		auto *cloned = new MoleculesObservable(obsName+"_clone", tmList, stochRelation, stochQuantity);
		cloned->setTermGroupIds(termGroupIds);
		return cloned;
	}

	auto *cloned = new MoleculesObservable(obsName+"_clone",tmList);
	cloned->setTermGroupIds(termGroupIds);
	return cloned;
}

int MoleculesObservable::isObservable(Molecule *m) const
{
	// DEBUG code
	//cout << "MoleculesObservable::isObservable( " << m->getUniqueID() << " )" << endl;
	//m->printDetails();
	//cout << "observable name: " << obsName << endl;
	//cout << "number of templates: " << n_templates << endl;

	int matches = 0;
	for(int t=0; t<n_templates; t++) {
		//cout << "moleculeType: " << (templateMolecules[t]->getMoleculeTypeName()) << endl;
		//cout << "connected to: " << (templateMolecules[t]->getN_connectedTo()) << endl;
		//templateMolecules[t]->printDetails();
		// try to get match counts, rather than just a boolean
		//cout<<endl<<endl<<endl;
		//cout<<"starting!"<<endl;

		bool usedCompiledSimple = false;
		bool matched = templateMolecules[t]->matchesCompiledSimple(
				m, usedCompiledSimple);
		if (!usedCompiledSimple) matched = templateMolecules[t]->compare(m);
		if (matched) {
			//cout<<"  adding one"<< "\n";
			matches += m->getPopulation();
			//return 1;
		}
		//else { cout<<"  nothing."<<endl; }
	}
	//cout << "total_matches: " << matches << endl;
	return matches;
}

int MoleculesObservable::isObservable(Complex *c) const
{
	if (!hasStoichiometricConstraints) {
		int total = 0;
		for(auto molIter=c->complexMembers.begin(); molIter!=c->complexMembers.end(); molIter++) {
			total += isObservable(*molIter);
		}
		return total;
	}

	// Handle stoichiometric observables
	// Group templates belonging to the same BNGL term (e.g. symmetric-site permutations)
	const bool hasGroups = (static_cast<int>(termGroupIds.size()) == n_templates);
	auto groupOf = [&](int t) -> int { return hasGroups ? termGroupIds[t] : t; };
	auto relationSatisfied = [](int rel, int localMatches, int qty) -> bool {
		switch (rel) {
			case EQUALS: return localMatches == qty;
			case NOT_EQUALS: return localMatches != qty;
			case GREATER_THAN: return localMatches > qty;
			case LESS_THAN: return localMatches < qty;
			case GREATOR_OR_EQUAL_TO: return localMatches >= qty;
			case LESS_THAN_OR_EQUAL_TO: return localMatches <= qty;
			default: return localMatches > 0;
		}
	};

	// Check if the complex satisfies all term constraints first
	for (int t = 0; t < n_templates; ) {
		const int g = groupOf(t);
		int end = t + 1;
		while (end < n_templates && groupOf(end) == g) ++end;

		int localMatches = 0;
		for (int k = t; k < end; ++k) {
			for (auto molIter = c->complexMembers.begin(); molIter != c->complexMembers.end(); molIter++) {
				if (templateMolecules[k]->compare(*molIter)) {
					localMatches++;
				}
			}
		}

		if (relation[t] != NO_RELATION) {
			if (!relationSatisfied(relation[t], localMatches, quantity[t])) return 0;
		} else {
			if (localMatches == 0) return 0;
		}
		t = end;
	}

	// Complex satisfies all constraints, now sum up the matches
	int total = 0;
	for (auto molIter = c->complexMembers.begin(); molIter != c->complexMembers.end(); molIter++) {
		total += isObservable(*molIter);
	}
	return total;
}




///////////////////////////////////////////////////////////////////


SpeciesObservable::SpeciesObservable(string name, vector <TemplateMolecule *> &tmList, vector <string> &stochRelation, vector <int> &stochQuantity) :
	Observable(name)
{
	n_templates=tmList.size();
	templateMolecules = new TemplateMolecule * [n_templates];
	for(int t=0; t<n_templates; t++) {
		templateMolecules[t] = tmList.at(t);
	}


	relation = new int [n_templates];
	quantity = new int [n_templates];
	for(int t=0; t<n_templates; t++) {
		if(stochRelation.at(t).empty()) {
			relation[t]=NO_RELATION;
			quantity[t]=-1;

		} else if (stochRelation.at(t).compare("==")==0) {
			relation[t]=EQUALS;
			quantity[t]=stochQuantity.at(t);

		} else if (stochRelation.at(t).compare("!=")==0) {
			relation[t]=NOT_EQUALS;
			quantity[t]=stochQuantity.at(t);

		} else if (stochRelation.at(t).compare(">")==0) {
			relation[t]=GREATER_THAN;
			quantity[t]=stochQuantity.at(t);

		} else if (stochRelation.at(t).compare("<")==0) {
			relation[t]=LESS_THAN;
			quantity[t]=stochQuantity.at(t);

		} else if (stochRelation.at(t).compare(">=")==0) {
			relation[t]=GREATOR_OR_EQUAL_TO;
			quantity[t]=stochQuantity.at(t);

		} else if (stochRelation.at(t).compare("<=")==0) {
			relation[t]=LESS_THAN_OR_EQUAL_TO;
			quantity[t]=stochQuantity.at(t);

		} else {
			relation[t]=NO_RELATION;
			quantity[t]=-1;
		}
	}

	this->type=Observable::SPECIES;
}

SpeciesObservable::~SpeciesObservable()
{
	delete [] relation;
	delete [] quantity;
}


//NOTE:  cloning a molecule DOES NOT clone any dependent reactions.  You will have to
//add that again to this observable, if there are any.  This is the behaviour, because
//observables are generally only cloned in this way for local functions
Observable * SpeciesObservable::clone() {
	vector <TemplateMolecule *> tmList;
	vector <string> stochRelation;
	vector <int> stochQuantity;
	for (int t = 0; t < n_templates; t++) {
		tmList.push_back(templateMolecules[t]);
		if (relation[t] == NO_RELATION) {
			stochRelation.push_back("");
		} else if (relation[t] == EQUALS) {
			stochRelation.push_back("==");
		} else if (relation[t] == NOT_EQUALS) {
			stochRelation.push_back("!=");
		} else if (relation[t] == GREATER_THAN) {
			stochRelation.push_back(">");
		} else if (relation[t] == LESS_THAN) {
			stochRelation.push_back("<");
		} else if (relation[t] == GREATOR_OR_EQUAL_TO) {
			stochRelation.push_back(">=");
		} else if (relation[t] == LESS_THAN_OR_EQUAL_TO) {
			stochRelation.push_back("<=");
		} else {
			stochRelation.push_back("");
		}
		stochQuantity.push_back(quantity[t]);
	}
	auto *cloned = new SpeciesObservable(obsName + "_clone", tmList, stochRelation, stochQuantity);
	cloned->setTermGroupIds(termGroupIds);
	return cloned;
}

int SpeciesObservable::isObservable(Molecule *m) const
{
	cerr<<"Comparing a Species observable '"<<obsName<<"' to a molecule!"<<endl;
	cerr<<"You can only compare Species observable to a complex!"<<endl;
	throw std::runtime_error("Cannot compare Species observable '" + obsName + "' to a single molecule");
}

int SpeciesObservable::isObservableMembers(const list<Molecule *> &members) const
{
	if (members.empty()) return 0;
	const int pop = members.front()->getPopulation();
	const bool hasGroups = (static_cast<int>(termGroupIds.size()) == n_templates);
	auto groupOf = [&](int t) -> int { return hasGroups ? termGroupIds[t] : t; };

	int matches = 0;
	for (int t = 0; t < n_templates; ) {
		const int g = groupOf(t);
		int end = t + 1;
		while (end < n_templates && groupOf(end) == g) ++end;

		if (relation[t] == NO_RELATION) {
			bool matched = false;
			for (int k = t; k < end && !matched; ++k) {
				for (auto molIter = members.begin(); molIter != members.end(); ++molIter) {
					if (templateMolecules[k]->compare(*molIter)) {
						matches += (*molIter)->getPopulation();
						matched = true;
						break;
					}
				}
			}
		} else {
			int localMatches = 0;
			for (int k = t; k < end; ++k) {
				for (auto molIter = members.begin(); molIter != members.end(); ++molIter) {
					if (templateMolecules[k]->compare(*molIter)) {
						localMatches++;
					}
				}
			}
			if (relation[t] == EQUALS) {
				if (localMatches == quantity[t]) matches += pop;
			} else if (relation[t] == NOT_EQUALS) {
				if (localMatches != quantity[t]) matches += pop;
			} else if (relation[t] == GREATER_THAN) {
				if (localMatches > quantity[t]) matches += pop;
			} else if (relation[t] == LESS_THAN) {
				if (localMatches < quantity[t]) matches += pop;
			} else if (relation[t] == GREATOR_OR_EQUAL_TO) {
				if (localMatches >= quantity[t]) matches += pop;
			} else if (relation[t] == LESS_THAN_OR_EQUAL_TO) {
				if (localMatches <= quantity[t]) matches += pop;
			}
		}
		t = end;
	}
	return matches;
}

int SpeciesObservable::isObservable(Complex *c) const
{
	if (c == nullptr) return 0;
	return isObservableMembers(c->complexMembers);
}


