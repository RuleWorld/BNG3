



#include "reaction.hh"

#include <cmath>
#include <utility>


using namespace std;
using namespace NFcore;

namespace {
	thread_local vector<int> complexScratch;

	template <typename Container>
	int distinctComplexesOf(Container *container, int size)
	{
		complexScratch.clear();
		if (static_cast<int>(complexScratch.capacity()) < size)
			complexScratch.reserve(size);
		for (int i = 0; i < size; ++i) {
			MappingSet *ms = container->getMappingSetByIndex(i);
			if (!ms || ms->getNumOfMappings() == 0) continue;
			Mapping *mapping = ms->get(0);
			if (mapping && mapping->getMolecule())
				complexScratch.push_back(mapping->getMolecule()->getComplexID());
		}
		sort(complexScratch.begin(), complexScratch.end());
		return static_cast<int>(unique(complexScratch.begin(), complexScratch.end()) -
				complexScratch.begin());
	}
}

int NFcore::countDistinctComplexes(ReactantList *rl)
{
	if (!rl->mayShareComplexes()) return rl->size();
	return distinctComplexesOf(rl, rl->size());
}

int NFcore::countDistinctComplexes(ReactantTree *tree)
{
	if (!tree->mayShareComplexes()) return tree->size();
	return distinctComplexesOf(tree, tree->size());
}

double NFcore::perComplexRateFactorSum(ReactantTree *tree)
{
	set<int> seen;
	double sum = 0.0;
	for (int i = 0; i < tree->size(); ++i) {
		MappingSet *ms = tree->getMappingSetByIndex(i);
		if (!ms || ms->getNumOfMappings() == 0) continue;
		Mapping *mapping = ms->get(0);
		if (!mapping || !mapping->getMolecule()) continue;
		if (seen.insert(mapping->getMolecule()->getComplexID()).second)
			sum += tree->getRateFactor(i);
	}
	return sum;
}

void NFcore::collectReactantRepresentatives(ReactantList *rl, bool perComplex,
		vector<MappingSet*> &out, vector<int> *flatIndices)
{
	out.clear();
	if (flatIndices) flatIndices->clear();
	if (!perComplex || !rl->mayShareComplexes()) {
		for (int i = 0; i < rl->size(); ++i) {
			MappingSet *ms = rl->getMappingSetByIndex(i);
			if (ms) {
				out.push_back(ms);
				if (flatIndices) flatIndices->push_back(i);
			}
		}
		return;
	}

	set<int> seen;
	for (int i = 0; i < rl->size(); ++i) {
		MappingSet *ms = rl->getMappingSetByIndex(i);
		if (!ms || ms->getNumOfMappings() == 0) continue;
		Mapping *mapping = ms->get(0);
		if (!mapping || !mapping->getMolecule()) continue;
		if (seen.insert(mapping->getMolecule()->getComplexID()).second) {
			out.push_back(ms);
			if (flatIndices) flatIndices->push_back(i);
		}
	}
}




FunctionalRxnClass::FunctionalRxnClass(string name, GlobalFunction *gf, TransformationSet *transformationSet, System *s) :
	BasicRxnClass(name,1,"",transformationSet,s)
{
	this->reactionType = ReactionClass::OBS_DEPENDENT_RXN;
	this->cf=0;
	this->gf=gf;
	for(int vr=0; vr<gf->getNumOfVarRefs(); vr++) {
		if(gf->getVarRefType(vr)=="Observable") {
			Observable *obs = s->getObservableByName(gf->getVarRefName(vr));
			obs->addDependentRxn(this);
		} else if(gf->getVarRefType(vr)=="Time") {
			// Time is read through GlobalFunction's live System pointer and
			// changes on every NFsim step; it has no observable dependency to
			// register for propensity invalidation.
			continue;
		} else {
			cerr<<"When creating a FunctionalRxnClass of name: "+name+" you provided a function that\n";
			cerr<<"depends on an observable type that I can't yet handle! (which is "+gf->getVarRefType(vr)+"\n";
			cerr<<"try using type: 'MoleculeObservable' for now.\n";
			cerr<<"quiting..."<<endl; exit(1);
		}
	}
}

FunctionalRxnClass::FunctionalRxnClass(string name, CompositeFunction *cf, TransformationSet *transformationSet, System *s) :
	BasicRxnClass(name,1, "", transformationSet,s)
{
	this->reactionType = ReactionClass::OBS_DEPENDENT_RXN;
	this->gf=0;
	this->cf=cf;
	this->cf->setGlobalObservableDependency(this,s);
}


FunctionalRxnClass::~FunctionalRxnClass() {};

double FunctionalRxnClass::update_a() {
	//cout<<"udpating a"<<endl;
	if(this->onTheFlyObservables==false) {
		cerr<<"Warning!!  You have on the fly observables turned off, but you are using functional\n";
		cerr<<"reactions which depend on observables.  Therefore, you cannot turn off onTheFlyObservables!\n";
		cerr<<"exiting now."<<endl;
		exit(1);
	}



	//	cout<<"here"<<endl;
	if(gf!=0) {
	//	cout<<"in here"<<endl;
		// AS-2021
		if(gf->fileFunc==true) {
			gf->fileUpdate();
		}
		// AS-2021
		a=FuncFactory::Eval(gf->p);
	} else if(cf!=0) {
		if (reactantCountBuffer.size() != n_reactants) {
			reactantCountBuffer.resize(n_reactants);
		}
		for(unsigned int r=0; r<n_reactants; r++) {
			reactantCountBuffer[r] = (int)getReactantCount(r);
		}
		int *reactantCountsPtr = (n_reactants > 0) ? &reactantCountBuffer[0] : 0;
		a=cf->evaluateOn(0,0, reactantCountsPtr, n_reactants);
	//	cout<<"and here"<<endl;
	} else {
		cout<<"Error!  Functional rxn is not properly initialized, but is being used!"<<endl;
		exit(1);
	}

	a *= this->volumeConversionFactor;

	// FunctionalRxnClass is constructed with baseRate=1, so the constructor's
	// symmetry correction is otherwise lost for ordinary functional rates.
	// TotalRate already states the complete propensity and must not receive that
	// reaction-center correction.  This placement matches NFsim commit 1b19611:
	// the loader sets totalRateFlag after construction and setBaseRate().
	if (!this->totalRateFlag)
	{
		a *= this->baseRate;
	}

	if(a<0) {
		cout<<"Warning!!  The function you provided for functional rxn: '"<<name<<"' evaluates\n";
		cout<<"to a value less than zero!  You cannot have a negative propensity!";
		cout<<"here is the offending function: \n";
		gf->printDetails();
		cout<<"\nhere is the offending reaction: \n";
		this->printDetails();
		cout<<"\n\nquitting."<<endl;
		exit(1);
	}


	// check here for the total rate flag - if this is set to true, then
	// use the rate exactly as given by the function, but if it is false,
	// then we have to multiply here by the reactant counts
	if(!this->totalRateFlag) {
		for(unsigned int i=0; i<n_reactants; i++)
			a*=(double)getCorrectedReactantCount(i);
	}
	else
	{
		// Check that we have at least one set of reactants!
		for(unsigned int i=0; i<n_reactants; i++) {
			if(getCorrectedReactantCount(i)==0) {
				a=0.0;
				break;
				//cout<<"Warning!  Function evaluates to positive rate for a reaction, but"<<endl;
				//cout<<"one of the reactant lists is empty!"<<endl;
				//this->printDetails();
				//cf->printDetails(reactantTemplates[0]->getMoleculeType()->getSystem());
				//exit(1);
			}
		}
	}
	
	return a;
}

void FunctionalRxnClass::printDetails() const {

	string trate = "off";
	if(this->totalRateFlag) trate = "on";

	if(gf!=0) {
		// AS-2021
		if (gf->fileFunc==true) {
			gf->fileUpdate();
		}
		// AS-2021
		cout<<"ReactionClass: " << name <<"  ( baseFunction="<<gf->getNiceName()<<"="<<FuncFactory::Eval(gf->p)<<",  a="<<a<<", fired="<<fireCounter<<" times, TotalRate="<<trate<<" )"<<endl;
	} else if(cf!=0) {
		int * reactantCounts = new int[this->n_reactants];
		for(unsigned int r=0; r<n_reactants; r++) {
			reactantCounts[r]=getReactantCount(r);
		}
		double value=cf->evaluateOn(0,0, reactantCounts, n_reactants);
		delete [] reactantCounts;
		cout<<"ReactionClass: " << name <<"  ( baseFunction="<<cf->getName()<<"="<<value<<",  a="<<a<<", fired="<<fireCounter<<" times, TotalRate="<<trate<<" )"<<endl;

	}

	for(unsigned int r=0; r<n_reactants; r++)
	{
		cout<<"      -"<< this->reactantTemplates[r]->getMoleculeTypeName();
		cout<<"	(count="<< this->getReactantCount(r) <<")."<<endl;
	}
	if(n_reactants==0)
		cout<<"      >No Reactants: so this rule either creates new species or does nothing."<<endl;
}









MMRxnClass::MMRxnClass(string name, double kcat, double Km, TransformationSet *transformationSet,System *s) :
	BasicRxnClass(name,1,"",transformationSet,s)
{
	this->Km = Km;
	this->kcat = kcat;
	this->sFree=0;
	if(n_reactants!=2) {
		cerr<<"You have tried to create a reaction with a Michaelis-Menten rate law (named: '"+name+"'\n')";
		cerr<<"but you don't have the correct number of reactants!  Michaelis-Menten reactions require\n";
		cerr<<"exactly 2 reactants.  A substrate (always given first) and an enzyme (always given second)\n";
		cerr<<"Read your tutorial next time... now I will quit."<<endl;
		exit(1);
	}
}
MMRxnClass::~MMRxnClass() {};

double FunctionalRxnClass::exactRuleMonkey_a()
{
	return update_a();
}

double MMRxnClass::exactRuleMonkey_a()
{
	return update_a();
}

double MMRxnClass::update_a()
{
	double S = (double)getCorrectedReactantCount(0);
	double E = (double)getCorrectedReactantCount(1);
	const double b = S - Km - E;
	// Solve the quadratic for free substrate without losing the small root
	// when enzyme is in excess.  The direct ``b + sqrt(b*b + 4*Km*S)``
	// expression rounds to zero for the tiny-Km regression from
	// NFsim/test/MM/mm_small_km.bngl.  hypot keeps the discriminant stable,
	// while the alternate root form avoids cancellation when b is negative.
	const double KmS = Km * S;
	const double discriminant = (Km >= 0.0 && S >= 0.0)
		? std::hypot(b, 2.0 * std::sqrt(KmS))
		: std::sqrt(b * b + 4.0 * KmS);
	if (b < 0.0 && KmS > 0.0) {
		sFree = (2.0 * KmS) / (discriminant - b);
	} else {
		sFree = 0.5 * (b + discriminant);
	}
	const double denominator = Km + sFree;
	a = (denominator > 0.0 && std::isfinite(denominator))
		? kcat * sFree * E / denominator
		: 0.0;
	return a;
}

void MMRxnClass::printDetails() const {
	cout<<"ReactionClass: " << name <<"  ( Km="<<Km<<", kcat="<<kcat<<",  a="<<a<<", fired="<<fireCounter<<" times )"<<endl;
	for(unsigned int r=0; r<n_reactants; r++)
	{
		cout<<"      -"<< this->reactantTemplates[r]->getMoleculeTypeName();
		cout<<"	(count="<< this->getReactantCount(r) <<")."<<endl;
	}
	if(n_reactants==0)
		cout<<"      >No Reactants: so this rule either creates new species or does nothing."<<endl;
}









SatRxnClass::SatRxnClass(string name, vector<double> saturationConstants,
                         TransformationSet *transformationSet, System *s) :
    BasicRxnClass(name, 1, "", transformationSet, s),
    saturationConstants(std::move(saturationConstants))
{
    if (this->saturationConstants.size() < 2 ||
        this->saturationConstants.size() > static_cast<std::size_t>(n_reactants) + 1 ||
        n_reactants == 0) {
        cerr << "Saturation reactions require at least two constants and no more "
             << "constants than reactants plus one!" << endl;
        exit(1);
    }
    for (const double constant : this->saturationConstants) {
        if (!std::isfinite(constant) || constant < 0.0) {
            cerr << "Saturation reaction constants must be finite and nonnegative!" << endl;
            exit(1);
        }
    }
}

SatRxnClass::~SatRxnClass() {}

double SatRxnClass::update_a()
{
    // BNG2's Sat(k0,K1,...,KN) law is a total rate:
    //   k0 * prod_i S_i / prod_i (K_i + S_i)
    // where the first N reactants receive saturation denominators and any
    // remaining reactants remain ordinary multiplicative factors.
    double rate = saturationConstants.front();
    const std::size_t denominatorCount = saturationConstants.size() - 1;
    for (unsigned int i = 0; i < n_reactants; ++i) {
        const double count = static_cast<double>(getCorrectedReactantCount(i));
        if (i < denominatorCount) {
            const double denominator = saturationConstants[i + 1] + count;
            if (denominator <= 0.0 || !std::isfinite(denominator)) {
                a = 0.0;
                return a;
            }
            rate *= count / denominator;
        } else {
            rate *= count;
        }
    }
    a = rate * volumeConversionFactor;
    if (!std::isfinite(a) || a < 0.0) a = 0.0;
    return a;
}

double SatRxnClass::exactRuleMonkey_a()
{
    return update_a();
}

void SatRxnClass::printDetails() const {
    cout << "ReactionClass: " << name << "  ( Sat=";
    for (std::size_t i = 0; i < saturationConstants.size(); ++i) {
        if (i != 0) cout << ",";
        cout << saturationConstants[i];
    }
    cout << ",  a=" << a << ", fired=" << fireCounter << " times )" << endl;
    for (unsigned int r = 0; r < n_reactants; ++r) {
        cout << "      -" << this->reactantTemplates[r]->getMoleculeTypeName();
        cout << "\t(count=" << this->getReactantCount(r) << ")." << endl;
    }
}

HillRxnClass::HillRxnClass(string name, double vmax, double kh, double exponent,
                           TransformationSet *transformationSet, System *s) :
    BasicRxnClass(name, 1, "", transformationSet, s),
    vmax(vmax), kh(kh), exponent(exponent)
{
    if (n_reactants == 0 || !std::isfinite(this->vmax) ||
        !std::isfinite(this->kh) || !std::isfinite(this->exponent) ||
        this->vmax < 0.0 || this->kh < 0.0 || this->exponent < 0.0) {
        cerr << "Hill reactions require finite, nonnegative constants and at least one "
             << "reactant!" << endl;
        exit(1);
    }
}

HillRxnClass::~HillRxnClass() {}

double HillRxnClass::update_a()
{
    // BNG2's Hill(Vmax,Kh,n) law saturates the first reactant and leaves
    // additional reactants as ordinary multiplicative factors.
    const double substrate = static_cast<double>(getCorrectedReactantCount(0));
    const double substratePower = std::pow(substrate, exponent);
    const double thresholdPower = std::pow(kh, exponent);
    const double denominator = thresholdPower + substratePower;
    if (denominator <= 0.0 || !std::isfinite(denominator)) {
        a = 0.0;
        return a;
    }

    a = vmax * substratePower / denominator;
    for (unsigned int i = 1; i < n_reactants; ++i) {
        a *= static_cast<double>(getCorrectedReactantCount(i));
    }
    a *= volumeConversionFactor;
    if (!std::isfinite(a) || a < 0.0) a = 0.0;
    return a;
}

double HillRxnClass::exactRuleMonkey_a()
{
    return update_a();
}

void HillRxnClass::printDetails() const {
    cout << "ReactionClass: " << name << "  ( Hill=" << vmax << "," << kh
         << "," << exponent << ",  a=" << a << ", fired=" << fireCounter
         << " times )" << endl;
    for (unsigned int r = 0; r < n_reactants; ++r) {
        cout << "      -" << this->reactantTemplates[r]->getMoleculeTypeName();
        cout << "\t(count=" << this->getReactantCount(r) << ")." << endl;
    }
}


BasicRxnClass::BasicRxnClass(string name, double baseRate, string baseRateName, TransformationSet *transformationSet, System *s) :
	ReactionClass(name,baseRate,baseRateName,transformationSet,s)
{
	this->reactionType = BASIC_RXN;  //set as normal reaction here, but deriving reaction classes can change this
	reactantLists = new ReactantList *[n_reactants];
	//Set up the reactantLists
	for(unsigned int r=0; r<n_reactants; r++)
		reactantLists[r]=(new ReactantList(r,transformationSet,25));
	
	this->connectivityFlag = s->getConnectivityFlag();
	
	msPairBuffer = new MappingSet*[2];
}


BasicRxnClass::~BasicRxnClass()
{
    //cout<<"  -------------------------------\n  ----------------------------\n";
	//cout<<"Reaction: "<<name<<endl;
	//this->reactantLists[0]->printDetails();

	//this->reactantLists[0]->removeMappingSet(0);
	//this->reactantLists[0]->removeMappingSet(3);
	//this->reactantLists[0]->removeMappingSet(6);
	//this->reactantLists[0]->removeMappingSet(9);

	//cout<<endl<<endl<<endl;
	//this->reactantLists[0]->printDetails();




	if(DEBUG) cout<<"Destroying rxn: "<<name<<endl;

	for(unsigned int r=0; r<n_reactants; r++)
	{
		//delete reactantTemplates[r]; DO NOT DELETE HERE (MoleculeType has responsibility of
		//deleting all template molecules of its type now.
		delete reactantLists[r];
	}
	delete [] reactantLists;
	
	delete [] msPairBuffer;
}

void BasicRxnClass::init()
{
	for(unsigned int r=0; r<n_reactants; r++)
	{
		reactantTemplates[r]->getMoleculeType()->addReactionClass(this,r);
	}
}


void BasicRxnClass::prepareForSimulation()
{

}


int BasicRxnClass::checkForEquality(Molecule *m, MappingSet* ms, int rxnIndex, ReactantList* reactantList){
	/*
	Check if mapping set clashes with any of the mapping sets already in reactantList
	*/
	const MappingIdSet& tempSet = m->getRxnListMappingSet(rxnIndex);
	for(MappingIdSet::const_iterator it= tempSet.begin();it!= tempSet.end(); ++it){
		MappingSet* ms2 = reactantList->getMappingSet(*it);
		if(MappingSet::checkForEquality(ms,ms2)){
			return *it;
		}
	}
	return -1;


}

/**
 * Updates a molecule's reaction membership and a reaction's reactant list
 *
 * If a molecule matches the TemplateMolecule of a reaction, then it gets added.
 * Note that NFsim has a single arbitrary TemplateMolecule for each reactant
 * complex for a reaction. So it assumes that you will always check the molecule
 * that matches the designated TemplateMolecule of a reaction for updates. So if
 * I modify the identification of reactant molecules in
 * TransformationSet::getListOfProducts(), I need to make sure that every molecule
 * that is part of a reaction whose propensity might change is included in the
 * listOfProducts.
 *
 * This is the gateway function to TemplateMolecule::compare().
 * @author Arvind Rasi Subramaniam
 * @param m - molecule that is being compared against the TemplateMolecule of a reaction
 * @param reactantPos - the reactant number among the reaction's reacant complexes
 * (note that every connected complex gets only one reactant number.)
 * @return true if there are no errors.
 */
bool BasicRxnClass::tryToAdd(Molecule *m, unsigned int reactantPos)
{
	//First a bit of error checking, that you should skip unless we are debugging...
	//	if(reactantPos<0 || reactantPos>=n_reactants || m==NULL)
	//	{
	//		cout<<"Error adding molecule to reaction!!  Invalid molecule or reactant position given.  Quitting."<<endl;
	//		exit(1);
	//	}

	//Get the specified reactantList
	ReactantList *rl = reactantLists[reactantPos];

	//Check if the molecule is in this list
	int rxnIndex = m->getMoleculeType()->getRxnIndex(this,reactantPos);
	//cout<<" got mappingSetId: " << m->getRxnListMappingId(rxnIndex)<<" size: " <<rl->size()<<endl;
	//cout<< " testing whether to add molecule ";
	//m->printDetails();
	//cout<<" ... as a mormal reaction "<<this->name<<endl;


	//If this reaction has multiple instances, we always remove them all!
	// then we remap because other mappings may have changed.  Yes, this may
	// be more ineffecient, but it is the fast implementation
	if(rl->getHasClonedMappings()) {
		while(m->getRxnListMappingId(rxnIndex)>=0) {
			rl->removeMappingSet(m->getRxnListMappingId(rxnIndex));
			m->deleteRxnListMappingId(rxnIndex,m->getRxnListMappingId(rxnIndex));
			//m->setRxnListMappingId(rxnIndex,Molecule::NOT_IN_RXN);
		}
	}

	// Here we get the standard update...
	// if(m->getRxnListMappingId(rxnIndex)>=0)
	// {
	// 	if(!reactantTemplates[reactantPos]->compare(m)) {
	// 		//	cout<<"Removing molecule "<<m->getUniqueID()<<" which was at mappingSet: "<<m->getRxnListMappingId(rxnIndex)<<endl;
	// 		rl->removeMappingSet(m->getRxnListMappingId(rxnIndex));
	// 		m->setRxnListMappingId(rxnIndex,Molecule::NOT_IN_RXN);
	// 	}
	// 	// case when the molecule is not in the reaction
	// } else {
	// 	// Get a clean mappingSet from the reactantList
	// 	// typically from the end: see the code for pusNextAvailableMappingSet()
	// 	MappingSet *ms = rl->pushNextAvailableMappingSet();
	// 	if(!reactantTemplates[reactantPos]->compare(m,rl,ms)) {
	// 		//we must remove, if we did not match.  This will also remove
	// 		//everything that was cloned off of the mapping set
	// 		rl->removeMappingSet(ms->getId());
	// 	} else {
	// 		m->setRxnListMappingId(rxnIndex,ms->getId());
	// 	}
	// }

	// Arvind Rasi Subramaniam: I am modifying this so that the mappingSet does
	// not change its position if the molecule still matches with the template.
	// This will prevent the simulation trajectory being dependent on whether
	// reaction-molecules pairs with unchanged membership are checked or not.
	// if (connectivityFlag) {
	// 	if(m->getRxnListMappingId(rxnIndex)>=0)
	// 	{
	// 		// Insted of removing the mappingSet
	// 		// and then getting a different clean one from the reactant list,
	// 		// get the mapping set corresponding to the molecule
	// 		ms = rl->getWriteableMappingSet(m->getRxnListMappingId(rxnIndex));
	// 		// and clear it before use.
	// 		ms->clear();
	// 		// If the molecule matches again,
	// 		// the mappingSet gets updated during the compare routine.
	// 		// If the molecule does not match anymore, remove the mapping set
	// 		// and remove the rxn form the molecule's reaction membership.
	// 		if(!reactantTemplates[reactantPos]->compare(m,rl,ms)) {
	// 			rl->removeMappingSet(ms->getId());
	// 			m->setRxnListMappingId(rxnIndex,Molecule::NOT_IN_RXN);
	// 		}
	// 		// case when the molecule is not in the reaction
	// 	} else {
	// 		// Get a clean mappingSet from the reactantList
	// 		// typically from the end: see the code for pusNextAvailableMappingSet()
	// 		MappingSet *ms = rl->pushNextAvailableMappingSet();
	// 		if(!reactantTemplates[reactantPos]->compare(m,rl,ms)) {
	// 			//we must remove, if we did not match.  This will also remove
	// 			//everything that was cloned off of the mapping set
	// 			rl->removeMappingSet(ms->getId());
	// 		} else {
	// 			m->setRxnListMappingId(rxnIndex,ms->getId());
	// 		}
	// 	}
	// }

	//Here we get the standard update...
	MappingIdSet deleteMs = m->getRxnListMappingSet(rxnIndex);
	if (contextCountsPerComplex[reactantPos] && m->getComplex() != 0) {
		rl->noteMappedComplexSize(m->getComplex()->getComplexSize());
	}

	//Try to map it!
	MappingSet *ms = rl->pushNextAvailableMappingSet();
	symmetricMappingSet.clear();
	comparisonResult = reactantTemplates[reactantPos]->compare(m,rl,ms,false,&symmetricMappingSet);
	if(!comparisonResult) {
		//cout << "no mapping in normal reaction, remove"<<endl;
		//we must remove, if we did not match.  This will also remove
		//everything that was cloned off of the mapping set
		rl->removeMappingSet(ms->getId());
		//JJT: removes any symmetric mapping sets that might have been added since we are not using them
		for(vector<MappingSet *>::iterator it=symmetricMappingSet.begin();it!=symmetricMappingSet.end();++it){
			rl->removeMappingSet((*it)->getId());
		}
	} else {
		//cout << "should be in normal reaction, confirm push"<<endl;
		//ms->printDetails();
		
		if (symmetricMappingSet.size() > 0){
            rl->removeMappingSet(ms->getId());
			for(vector<MappingSet *>::iterator it=symmetricMappingSet.begin();it!=symmetricMappingSet.end();++it){
					int mapIndex = checkForEquality(m,*it,rxnIndex,rl);
					if(mapIndex >= 0){
						deleteMs.erase(mapIndex);
						rl->removeMappingSet((*it)->getId());
					}
					else{
						m->setRxnListMappingId(rxnIndex,(*it)->getId());
					}
            }
		}
		else{
			int mapIndex = checkForEquality(m,ms,rxnIndex,rl);
			if(mapIndex >= 0){
				deleteMs.erase(mapIndex);
				rl->removeMappingSet(ms->getId());
			}
			else{
				m->setRxnListMappingId(rxnIndex,ms->getId());
			}
		}
		
	}

	for (MappingIdSet::iterator it = deleteMs.begin(); it != deleteMs.end(); ++it) {
		rl->removeMappingSet(*it);
		m->deleteRxnListMappingId(rxnIndex, *it);
	}

	return true;
}



void BasicRxnClass::remove(Molecule *m, unsigned int reactantPos)
{

	//First a bit of error checking...
	if(reactantPos<0 || reactantPos>=n_reactants || m==NULL)
	{
		cout<<"Error removing molecule from a reaction!!  Invalid molecule or reactant position given.  Quitting."<<endl;
		exit(1);
	}


	//Get the specified reactantList
	ReactantList *rl = reactantLists[reactantPos];

	//Check if the molecule is in this list
	int rxnIndex = m->getMoleculeType()->getRxnIndex(this,reactantPos);
	bool isInRxn = (m->getRxnListMappingId(rxnIndex)>=0);


	if(isInRxn)
	{
		rl->removeMappingSet(m->getRxnListMappingId(rxnIndex));
		m->setRxnListMappingId(rxnIndex,Molecule::NOT_IN_RXN);
	}
}




void BasicRxnClass::notifyRateFactorChange(Molecule * m, int reactantIndex, int rxnListIndex)
{
	cerr<<"You are trying to notify a Basic Reaction of a rate Factor Change!!! You should only use this"<<endl;
	cerr<<"function for DORrxnClass rules!  For this offense, I must abort now."<<endl;
	exit(1);
}

double BasicRxnClass::exactRuleMonkey_a()
{
	if(this->totalRateFlag) {
		double exact_a = baseRate;
		for(unsigned int i=0; i<n_reactants; i++) {
			if(getCorrectedReactantCount(i)==0) exact_a = 0.0;
		}
		return exact_a;
	}

	double validCombinations = 0.0;
	if (n_reactants == 0) {
		validCombinations = 1.0;
	} else if (n_reactants == 1) {
		validCombinations = getCorrectedReactantCount(0);
	} else if (n_reactants == 2) {
		// Enumerate one representative per complex for pure context reactants.
		static thread_local vector<MappingSet*> reps0, reps1;
		collectReactantRepresentatives(reactantLists[0], contextCountsPerComplex[0], reps0);
		collectReactantRepresentatives(reactantLists[1], contextCountsPerComplex[1], reps1);
		double totalCombinations = (double)reps0.size() * (double)reps1.size();
		double invalidCombinations = 0;

		for (size_t i = 0; i < reps0.size(); ++i) {
			msPairBuffer[0] = reps0[i];
			for (size_t j = 0; j < reps1.size(); ++j) {
				msPairBuffer[1] = reps1[j];
				
				// check for collision
				if (!transformationSet->checkMolecularity(msPairBuffer)) {
					invalidCombinations++;
				}
			}
		}
		validCombinations = totalCombinations - invalidCombinations;
		if (validCombinations < 0) validCombinations = 0;
	} else {
		// fallback to standard approximation
		validCombinations = 1.0;
		for(unsigned int i=0; i<n_reactants; i++) {
			validCombinations *= getCorrectedReactantCount(i);
		}
	}

	return validCombinations * baseRate;
}

double BasicRxnClass::update_a()
{
	if (useRuleMonkey) {
		a = exactRuleMonkey_a();
		return a;
	}
	// Use the total rate law convention (macroscopic rate)
	if(this->totalRateFlag) {
		a=baseRate;
		for(unsigned int i=0; i<n_reactants; i++)
			if(getCorrectedReactantCount(i)==0) a=0.0;

	// Use the standard microscopic rate
	} else {
		a = 1.0;
		for(unsigned int i=0; i<n_reactants; i++) {
			a*=getCorrectedReactantCount(i);
		}
		a*=baseRate;
	}
	return a;
}


int BasicRxnClass::getReactantCount(unsigned int reactantIndex) const
{
	return isPopulationType[reactantIndex] ?
			   reactantLists[reactantIndex]->getPopulation()
			 : reactantLists[reactantIndex]->size();
}


int BasicRxnClass::getCorrectedReactantCount(unsigned int reactantIndex) const
{
	/*cerr << "  getCorrectedReactantCount rindex: " << reactantIndex << "  isPop? " << isPopulationType[reactantIndex] << endl;
	if ( isPopulationType[reactantIndex] )
	{
		cerr << "  corr:  " << identicalPopCountCorrection[reactantIndex];
		cerr << "  pop:   " << reactantLists[reactantIndex]->getPopulation() << endl;
		cerr << "  final: " << std::max( reactantLists[reactantIndex]->getPopulation()
	             - identicalPopCountCorrection[reactantIndex], 0 ) << endl;
	}
	else
	{
		cerr << "  count: " << reactantLists[reactantIndex]->size() << endl;
	}
	*/

	if ((matchOncePerReactant[reactantIndex] ||
			contextCountsPerComplex[reactantIndex]) &&
			!isPopulationType[reactantIndex]) {
		return countDistinctComplexes(reactantLists[reactantIndex]);
	}

	return isPopulationType[reactantIndex] ?
			   std::max( reactantLists[reactantIndex]->getPopulation()
			             - identicalPopCountCorrection[reactantIndex], 0 )
			 : reactantLists[reactantIndex]->size();
}

void BasicRxnClass::printFullDetails() const
{
	cout<<"BasicRxnClass: "<<name<<endl;
	for(unsigned int i=0; i<n_reactants; i++)
		reactantLists[i]->printDetails();
}


void BasicRxnClass::pickRuleMonkeyMappingSets(double random_A_number) const
{
	NfsimRNG& rng = system->getRNG();
	if (n_reactants != 2 || totalRateFlag) {
		for(unsigned int i=0; i<n_reactants; i++) {
			if ( isPopulationType[i] ) {
				reactantLists[i]->pickRandomFromPopulation(mappingSet[i], rng);
			} else {
				reactantLists[i]->pickRandom(mappingSet[i], rng);
			}
		}
		return;
	}

	// For molecularity=2, we have to find a valid pair (no null events)
	int size0 = getReactantCount(0);
	int size1 = getReactantCount(1);

	validPairsBuffer.clear();
	for (int i = 0; i < size0; ++i) {
		msPairBuffer[0] = reactantLists[0]->getMappingSet(i);
		for (int j = 0; j < size1; ++j) {
			msPairBuffer[1] = reactantLists[1]->getMappingSet(j);

			if (transformationSet->checkMolecularity(msPairBuffer)) {
				validPairsBuffer.push_back(make_pair(i, j));
			}
		}
	}

	if (validPairsBuffer.empty()) {
		for(unsigned int i=0; i<n_reactants; i++) {
			if ( isPopulationType[i] ) {
				reactantLists[i]->pickRandomFromPopulation(mappingSet[i], rng);
			} else {
				reactantLists[i]->pickRandom(mappingSet[i], rng);
			}
		}
		return;
	}

	// Select a valid pair
	int selectedIndex = rng.random_int(0, validPairsBuffer.size());
	int i = validPairsBuffer[selectedIndex].first;
	int j = validPairsBuffer[selectedIndex].second;

	mappingSet[0] = reactantLists[0]->getMappingSet(i);
	mappingSet[1] = reactantLists[1]->getMappingSet(j);
}


void BasicRxnClass::pickMappingSets(double random_A_number) const
{
	if (useRuleMonkey) {
		pickRuleMonkeyMappingSets(random_A_number);
		return;
	}

	NfsimRNG& rng = system->getRNG();
	for(unsigned int i=0; i<n_reactants; i++)
	{
		if ( isPopulationType[i] ) {
			reactantLists[i]->pickRandomFromPopulation(mappingSet[i], rng);
		} else {
			reactantLists[i]->pickRandom(mappingSet[i], rng);
		}
	}
}
