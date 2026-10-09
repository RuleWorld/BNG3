#include <ctime>
#include <chrono>
#include <map>
#include <set>
#include <string>
#include <cstdlib>
#include <iostream>
#include <limits>
#include "NFcore.hh"

#if defined(_MSC_VER)
#include <intrin.h>
#endif


using namespace std;
using namespace NFcore;

namespace {

unsigned int compactMembershipBitCount(std::uint64_t value)
{
	unsigned int count = 0;
	while (value != 0) {
		value &= (value - 1);
		++count;
	}
	return count;
}

void setCompactMembershipCandidateBit(
		vector<std::uint64_t> &bits, unsigned int reactionIndex)
{
	const std::size_t wordIndex = reactionIndex >> 6;
	if (bits.size() <= wordIndex)
		bits.resize(wordIndex + 1, 0);
	bits[wordIndex] |=
			(std::uint64_t(1) << (reactionIndex & 63));
}

unsigned int compactMembershipTrailingZeroCount(std::uint64_t value)
{
#if defined(_MSC_VER)
	unsigned long bit = 0;
	_BitScanForward64(&bit, value);
	return static_cast<unsigned int>(bit);
#else
	return static_cast<unsigned int>(__builtin_ctzll(value));
#endif
}

bool compactMembershipBitIsSet(
		const vector<std::uint64_t> &bits, unsigned int reactionIndex)
{
	const std::size_t wordIndex = reactionIndex >> 6;
	return wordIndex < bits.size() &&
			(bits[wordIndex] &
				(std::uint64_t(1) << (reactionIndex & 63))) != 0;
}

}




MoleculeType::MoleculeType(
	string name,
	vector <string> &compName,
	System *s)
 : population_type( false ), isFixed_(false), fixedCount_(0), fixedCompartment_(nullptr)
{
	vector <string> defaultCompState;
	vector < vector <string> > possibleCompStates;
	vector <bool> isIntegerComponent;
	for(unsigned int i=0; i<compName.size(); i++) {
		vector <string> v;
		possibleCompStates.push_back(v);
		defaultCompState.push_back("NO_STATE");
		isIntegerComponent.push_back(false);
	}
	init(name, compName, defaultCompState, possibleCompStates, isIntegerComponent, s);

}

MoleculeType::MoleculeType(
	string name,
	vector <string> &compName,
	vector <string> &defaultCompState,
	System *s)
 : population_type( false ), isFixed_(false), fixedCount_(0), fixedCompartment_(nullptr)
{
	vector < vector <string> > possibleCompStates;
	vector <bool> isIntegerComponent;
	for(unsigned int i=0; i<compName.size(); i++) {
		vector <string> v;
		possibleCompStates.push_back(v);
		isIntegerComponent.push_back(false);
	}
	init(name, compName, defaultCompState, possibleCompStates, isIntegerComponent, s);
}







MoleculeType::MoleculeType(
		string name,
		vector <string> &compName,
		vector <string> &defaultCompState,
		vector < vector<string> > &possibleCompStates,
		System *system)
 : population_type( false ), isFixed_(false), fixedCount_(0), fixedCompartment_(nullptr)
{
	vector <bool> isIntegerComponent;
	for(unsigned int i=0; i<compName.size(); i++) {
		isIntegerComponent.push_back(false);
	}
	init(name, compName, defaultCompState, possibleCompStates, isIntegerComponent, system);
}

MoleculeType::MoleculeType(
		string name,
		vector <string> &compName,
		vector <string> &defaultCompState,
		vector < vector<string> > &possibleCompStates,
		vector <bool> isIntegerComponent,
		System *system)
 : population_type( false ), isFixed_(false), fixedCount_(0), fixedCompartment_(nullptr)
{
	init(name, compName, defaultCompState, possibleCompStates, isIntegerComponent, system);
}


MoleculeType::MoleculeType(
		string name,
		vector <string> &compName,
		vector <string> &defaultCompState,
		vector < vector<string> > &possibleCompStates,
		vector <bool> isIntegerComponent,
		bool pop_type,
		System *system)
 : population_type( pop_type ), isFixed_(false), fixedCount_(0), fixedCompartment_(nullptr)
{
	init(name, compName, defaultCompState, possibleCompStates, isIntegerComponent, system);
}


const string& MoleculeType::getComponentName(int cIndex) const {
	if(cIndex>=this->numOfComponents) {
		cerr<<"in MoleculeType:getComponentName, can't get that component!"<<endl;
		cerr<<"looking for cIndex: "<<cIndex<<endl;
		cerr<<"I only have: "<<numOfComponents<<" components."<<endl;
		exit(2);
	}
	return this->compName[cIndex];
}

void MoleculeType::init(
	string name,
	vector <string> &compName,
	vector <string> &defaultCompState,
	vector < vector<string> > &possibleCompStates,
	vector <bool> isIntegerComponent,
	System *system)
{
	//Basics...
	this->name=name;
	this->numOfComponents=compName.size();

	//First, some quick error checks
	if((int)defaultCompState.size()!=numOfComponents || (int)possibleCompStates.size()!=numOfComponents ||
			(int)isIntegerComponent.size()!=numOfComponents) {
		cout<<"Error creating MoleculeType: '"<<name<<"': The length of the input vectors\n";
		cout<<"do not match, so I can't initialize this object.\n";
		cout<<"quitting now."<<endl; exit(1);
	}

	//Now we can get on with initializing the MoleculeType information
	this->compName=new string [numOfComponents];
	this->defaultCompState = new int [numOfComponents];
	this->isIntegerCompState = new bool [numOfComponents];

	int nostate = Molecule::NOSTATE;
	for(int c=0; c<numOfComponents; c++) {
		this->compName[c]=compName.at(c);
		this->compNameMap[compName.at(c)] = c;
		this->isIntegerCompState[c]=isIntegerComponent.at(c);

		bool foundDefaultState=false;
		vector <string> p;
		for(unsigned int i=0; i<possibleCompStates.at(c).size(); i++) {
			p.push_back(possibleCompStates.at(c).at(i));
			if(possibleCompStates.at(c).at(i) == defaultCompState.at(c)) {
				this->defaultCompState[c]=i; foundDefaultState=true;
			}
		}
		if(!foundDefaultState) this->defaultCompState[c]=Molecule::NOSTATE;
		this->possibleCompStates.push_back(p);
	}


	//Register myself with the system, and get an ID number
	this->system = system;
	this->type_id = this->system->addMoleculeType(this);
	reactionMappingIndices.clear();
	reactionMappingCount = 0;
	compactPartnerPools.assign(numOfComponents,
			static_cast<CompactPartnerPool *>(0));
	compactEnergyCenterCandidateBits.assign(
			numOfComponents, vector<std::uint64_t>());
	compactEnergyContextCandidateBits.assign(
			numOfComponents, vector<std::uint64_t>());
	compactPartnerCandidateBits.assign(
			numOfComponents, vector<std::uint64_t>());
	compactPartnerReactionIndices.assign(
			numOfComponents, vector<unsigned int>());
	compactEnergyContextMinimumRequiredBits.assign(numOfComponents, 0);
	nonCompactMembershipCandidateBits.clear();
	hasCompactEnergyMembershipIndex = false;
	compactPoolScaleCandidatesKey = 0;


	mList = new MoleculeList(this,2,system->getGlobalMoleculeLimit());
	n_eqComp = 0;
	eqCompOriginalName = nullptr;
	eqCompSizes = nullptr;
	eqCompName = nullptr;
	eqCompIndex = nullptr;
	indexToEqClass = nullptr;
}






MoleculeType::~MoleculeType()
{
	if(DEBUG) cout << "Destroying MoleculeType " << name << endl;

	//Delete freestore component information
	delete [] compName;
	delete [] defaultCompState;
	delete [] isIntegerCompState;

	//Delete details about equivalent components
	delete [] eqCompSizes;
	for(int i=0; i<n_eqComp; i++) {
		delete [] eqCompName[i];
		delete [] eqCompIndex[i];
	}
	delete [] eqCompName;
	delete [] eqCompIndex;
	delete [] eqCompOriginalName;
	if (indexToEqClass) {
		delete [] indexToEqClass;
	}
	for (vector<CompactPartnerPool *>::iterator it = compactPartnerPools.begin();
			it != compactPartnerPools.end(); ++it) {
		delete *it;
	}




	//Delete all template molecules of this type that exist
	TemplateMolecule *t;
	while(allTemplates.size()>0)
	{
		t = allTemplates.back();
		allTemplates.pop_back();
		delete t;
	}




	delete mList;
}

void MoleculeType::addEquivalentComponents(vector <vector <string> > &identicalComponents)
{
	this->n_eqComp = identicalComponents.size();
	eqCompOriginalName = new string [n_eqComp];
	eqCompName=new string * [n_eqComp];
	eqCompIndex=new int *[n_eqComp];
	eqCompSizes=new int [n_eqComp];

	if (indexToEqClass == nullptr) {
		indexToEqClass = new int[numOfComponents];
		for(int c=0; c<numOfComponents; c++) {
			indexToEqClass[c] = -1;
		}
	}

	for(int i=0; i<n_eqComp; i++) {
		const vector<string>& names = identicalComponents.at(i);
		if (names.empty()) {
			eqCompOriginalName[i] = "";
			eqCompSizes[i] = 0;
			continue;
		}
		string genericName = names.at(0);
		if (!genericName.empty()) genericName = genericName.substr(0, genericName.size() - 1);
		// Some callers provide the generic BNGL spelling as a final alias
		// (e.g. {r1,r2,r3,r}); it is not a runtime component and therefore
		// must not be resolved through compNameMap.
		eqCompSizes[i] = names.size();
		if (names.back() == genericName) --eqCompSizes[i];
		eqCompName[i] = new string [eqCompSizes[i]];
		eqCompIndex[i] = new int [eqCompSizes[i]];
		for(int k=0; k<eqCompSizes[i]; k++) {
			if(k==0) {
				string tempString = names.at(k);
				eqCompOriginalName[i] = tempString.substr(0,tempString.size()-1);
			}
			eqCompName[i][k] = names.at(k);
			eqCompIndex[i][k] = getCompIndexFromName(eqCompName[i][k]);

			// Map the component index to the equivalency class index
			if(eqCompIndex[i][k] >= 0 && eqCompIndex[i][k] < numOfComponents) {
				indexToEqClass[eqCompIndex[i][k]] = i;
			}
		}
	}
}


bool MoleculeType::isIntegerComponent(const string& cName) const {
	for(int c=0; c<numOfComponents; c++)
			if(compName[c].compare(cName)==0) {
				return this->isIntegerCompState[c];
			}
	cerr<<"!!! error !!! cannot find site name "<< cName << " in MoleculeType: "<<name;
	cerr<<"in function isIntegerComponent(string cName).  "<<endl;
	this->printDetails();
	exit(1);
}
bool MoleculeType::isIntegerComponent(int cIndex) const {
	if(cIndex>=0 && cIndex<numOfComponents) {
		return this->isIntegerCompState[cIndex];
	} else {
		cerr<<"!!! error !!! "<< cIndex << " is not a valid component index in MoleculeType: "<<name;
		cerr<<"in function isIntegerComponent(int cIndex).  "<<endl;
		this->printDetails();
		exit(1);
	}
}


bool MoleculeType::isEquivalentComponent(const string& cName) const {
	for(int i=0; i<n_eqComp; i++) {
		if(eqCompOriginalName[i].compare(cName)==0) {
			return true;
		}
	}
	return false;
}
bool MoleculeType::isEquivalentComponent(int cIndex) const {
	if (indexToEqClass && cIndex >= 0 && cIndex < numOfComponents) {
		return indexToEqClass[cIndex] != -1;
	}
	return false;
}

int MoleculeType::getEquivalenceClassNumber(int cIndex) const {
	if (indexToEqClass && cIndex >= 0 && cIndex < numOfComponents) {
		return indexToEqClass[cIndex];
	}
	return -1;
}

string MoleculeType::getEquivalenceClassComponentNameFromComponentIndex(int cIndex) const {
	if (indexToEqClass && cIndex >= 0 && cIndex < numOfComponents) {
		int eqClassIndex = indexToEqClass[cIndex];
		if (eqClassIndex != -1) {
			return eqCompOriginalName[eqClassIndex];
		}
	}
	cerr<<"Could not find equivalency class component string for component number: "<<cIndex<<"!!!"<<endl;
	exit(1);
}

void MoleculeType::getEquivalencyClass(int *&components, int &n_components, const string& cName) const {
	for(int i=0; i<n_eqComp; i++) {
		if(eqCompOriginalName[i].compare(cName)==0) {
			components = eqCompIndex[i];
			n_components=eqCompSizes[i];
			return;
		}
	}
}
int MoleculeType::getEquivalencyClassNumber(const string& cName) const {
	for(int i=0; i<n_eqComp; i++) {
		if(eqCompOriginalName[i].compare(cName)==0) {
				return i;
		}
	}
	cerr<<"Could not find equivalency class number for component named: "<<cName<<"!!!"<<endl;
	exit(1);
}




string MoleculeType::getComponentStateName(int cIndex, int cValue) {
	if(cValue==Molecule::NOSTATE) return "NO_STATE";
	if( cIndex>=(int)possibleCompStates.size() || cIndex<0 ){
		cerr<<"Component index out of range (moltype="<<getName()<<" cIndex="<<cIndex<<")!!!"<<endl;
		exit(1);
	}
	if( cValue>=(int)possibleCompStates.at(cIndex).size() || cValue<0 ){
		cerr<<"State index out of range (moltype="<<getName()<<" cIndex="<<cIndex<<" cValue="<<cValue<<")!!!"<<endl;
		exit(1);
	}
	return possibleCompStates.at(cIndex).at(cValue);
}




Molecule *MoleculeType::genDefaultMolecule(Compartment *c)
{
	Molecule *m;
	mList->create(m);
	m->setAlive(true);
	m->setCompartment(c);
	// MoleculeList preallocates inactive Molecule objects.  If complex
	// bookkeeping was enabled after the MoleculeType was constructed (for
	// example by a Species observable), those objects still carry the old
	// per-molecule flag and no complex ID.
	if (system->isUsingComplex()) {
		m->setUseComplex(true);
		if (m->getComplexID() == -1) {
			m->setComplexID(createComplex(m));
		}
	}
	//cout<<"adding molecule: "<<m->getMoleculeTypeName()<<"_"<<m->getUniqueID()<<endl;

	return m;
}


void MoleculeType::addMoleculeToRunningSystem(Molecule *&mol)
{
	//cout<<"adding molecule: "<<mol->getMoleculeTypeName()<<"_"<<mol->getUniqueID()<<endl;
	//First prepare the molecule for simulation
	mol->setUpLocalFunctionList();
	mol->prepareForSimulation();
	mol->setAlive(true);

	mol->addToObservables();
	this->updateRxnMembership(mol);
}


void MoleculeType::addMoleculeToRunningSystemButDontUpdate(Molecule *&mol)
{
	//First prepare the molecule for simulation

	mol->setUpLocalFunctionList();
	mol->prepareForSimulation();
	mol->setAlive(true);
	if (system != 0) system->recordNewMembershipMolecule(mol);

	//We assume observables and reaction membership will be updated later
	// (this is now the case for reaction firing)
}


void MoleculeType::removeMoleculeFromRunningSystem(Molecule *&m)
{
	if (system->isUsingComplex())
		// Need to manually unset canonical flag since we're not calling a Complex method
		m->getComplex()->unsetCanonical();

	//Remove this guy from the list, the observables list, and from all rxns
	mList->remove(m->getMolListId(), m);
	removeFromObservables(m);
	removeFromRxns(m);


	//We also have to remove all bonds
	for(int c=0; c<getNumOfComponents(); c++) {
		if(m->isBindingSiteBonded(c)) {
			Molecule::unbind(m,c);
		}
	}

	m->setAlive(false);

}


void MoleculeType::removeAllMolecules()
{
	// Iterate through all molecules and remove them. Loop backwards because
	// remove() removes by swapping with the last element. MoleculeList owns its
	// preallocated Molecule objects, so leave the inactive slots in place for
	// reuse and for MoleculeList::~MoleculeList() to release.
	for (int m = mList->size() - 1; m >= 0; m--) {
		Molecule *mol = mList->at(m);
		removeMoleculeFromRunningSystem(mol);
	}
}

void MoleculeType::removeMoleculeFromRunningSystemButDontUpdate(Molecule *&m)
{
	//Remove this guy from the list, the observables list, and from all rxns
	mList->remove(m->getMolListId(), m);
	//removeFromObservables(m);
	//removeFromRxns(m);

	//We also have to remove all bonds
	for(int c=0; c<getNumOfComponents(); c++) {
		if(m->isBindingSiteBonded(c)) {
			Molecule::unbind(m,c);
		}
	}

	m->setAlive(false);
}


Molecule * MoleculeType::getMolecule(int ID_molecule) const {
	return mList->at(ID_molecule);
}
int MoleculeType::getMoleculeCount() const {
	return mList->size();
}

CompactPartnerPool *MoleculeType::getOrCreateCompactPartnerPool(
		int componentIndex)
{
	if (componentIndex < 0 || componentIndex >= numOfComponents)
		return 0;
	if (compactPartnerPools[componentIndex] == 0)
		compactPartnerPools[componentIndex] = new CompactPartnerPool();
	return compactPartnerPools[componentIndex];
}


void MoleculeType::addTemplateMolecule(TemplateMolecule *t)
{
	if(t->getMoleculeType()==this)
		allTemplates.push_back(t);
	else
		cout<<"!!!!Error: trying to add molecule of type " << t->getMoleculeTypeName() << " to MoleculeType " << name << endl;
}



string MoleculeType::getMolObsName(int obsIndex) const {
	return molObs.at(obsIndex)->getName();
}

int MoleculeType::getMolObsCount(int obsIndex) const {
	return molObs.at(obsIndex)->getCount();
}



int MoleculeType::getCompIndexFromName(const string& cName) const
{
	auto it = compNameMap.find(cName);
	if(it != compNameMap.end()) return it->second;

	cerr<<"!!! warning !!! cannot find site name "<< cName << " in MoleculeType: "<<name<<endl;
	this->printDetails();
	throw std::runtime_error("Cannot find site name " + cName + " in MoleculeType: " + name);
}

int MoleculeType::getStateValueFromName(int cIndex, const string& stateName) const
{
	for(unsigned int s=0; s<possibleCompStates.at(cIndex).size(); s++) {
		if(possibleCompStates.at(cIndex).at(s)==stateName) {
			return s;
		}
	}
	cerr<<"Error!  '"<<stateName<<" is not a recognized possible state for '"<<compName[cIndex]<<"' in MoleculeType: '"<<name<<"'"<<endl;
	cerr<<"For that, I'm quitting!";
	printDetails();
	exit(1);
}




void MoleculeType::addReactionClass(ReactionClass * r, int rPosition)
{
	directMembershipDecisionCache.clear();
	directMembershipDecisionCacheSafe.clear();
	unsigned int reactionIndex = static_cast<unsigned int>(reactions.size());
	this->reactions.push_back(r);
	this->reactionPositions.push_back(rPosition);
	int partnerComponent = -1;
	bool compactPartnerRegistration =
		r->getCompactPartnerPoolInfo(rPosition, partnerComponent) &&
		partnerComponent >= 0 && partnerComponent < numOfComponents;
	reactionMappingIndices.push_back(compactPartnerRegistration
			? -1 : reactionMappingCount++);

	int reactionCenterComponent = -1;
	std::uint64_t contextComponentMask = 0;
	unsigned int minimumContextComponents = 0;
	bool indexed = r->getCompactMembershipIndexInfo(
			rPosition, reactionCenterComponent, contextComponentMask,
			minimumContextComponents) &&
		reactionCenterComponent >= 0 &&
		reactionCenterComponent < numOfComponents;
	if (indexed) {
		hasCompactEnergyMembershipIndex = true;
		setCompactMembershipCandidateBit(
				compactEnergyCenterCandidateBits[reactionCenterComponent],
				reactionIndex);
		for (int componentIndex = 0;
				componentIndex < numOfComponents && componentIndex < 64;
				++componentIndex) {
			if ((contextComponentMask &
					std::uint64_t(1) << componentIndex) == 0)
				continue;
			setCompactMembershipCandidateBit(
					compactEnergyContextCandidateBits[componentIndex],
					reactionIndex);
			unsigned int &minimum =
				compactEnergyContextMinimumRequiredBits[componentIndex];
			if (minimum == 0 || minimumContextComponents < minimum)
				minimum = minimumContextComponents;
		}
	} else {
		setCompactMembershipCandidateBit(
				nonCompactMembershipCandidateBits, reactionIndex);
	}
	if (compactPartnerRegistration) {
		CompactPartnerPool *partnerPool = r->getCompactPartnerPool();
		if (partnerPool != 0)
			partnerPool->registerReaction(
					r, r->supportsCompactPartnerPoolUpdate());
		setCompactMembershipCandidateBit(
				compactPartnerCandidateBits[partnerComponent], reactionIndex);
		compactPartnerReactionIndices[partnerComponent].push_back(reactionIndex);
	}

	//We also have to check to make sure that if the reaction is a DOR reaction,
	//we remember it so we can updated it
	if(r->getRxnType()==ReactionClass::DOR_RXN) {
		if( r->getDORreactantPosition()==rPosition) {
			indexOfDORrxns.push_back(reactions.size()-1);
		}
	}
	else if(r->getRxnType()==ReactionClass::DOR2_RXN) {
		if( r->getDORreactantPosition()==rPosition) {
			indexOfDORrxns.push_back(reactions.size()-1);
		}
		else if( r->getDORreactantPosition2()==rPosition) {
			indexOfDORrxns.push_back(reactions.size()-1);
		}
	}
}



bool MoleculeType::canSkipIndirectMembership(
		ReactionClass *firedReaction) const
{
	for (vector<ReactionClass *>::const_iterator it = reactions.begin();
			it != reactions.end(); ++it) {
		if (!(*it)->canSkipIndirectMembership(firedReaction))
			return false;
	}
	return true;
}

void MoleculeType::populateWithDefaultMolecules(int moleculeCount)
{
	if(DEBUG) cout<< " Populating "<< this->name << " with " << moleculeCount << " molecule(s)";
	if(DEBUG) cout<< " for a total of " << mList->size()+moleculeCount << " molecule(s)."<<endl;
	//mInstances.reserve(mInstances.size()+moleculeCount);
	for(int m=0; m<moleculeCount; m++)
	{
		if(DEBUG) cout<<" ("<<m+1<<") ";

		//Create the molecule (which knows how many components to make)
		this->genDefaultMolecule();
		//new Molecule(this);

		//Add the molecule to the list of molecules so we save it (does this automatically now!!!! )
		//mInstances.push_back(mol);
	}
}



void MoleculeType::setUpLocalFunctionListForMolecules()
{
	Molecule *mol;
	for(int m=0; m<mList->size(); m++ )
	{
	  	mol = mList->at(m);
	  	mol->setUpLocalFunctionList();
	}
}

namespace {
	static inline void appendUniqueMembershipIndex(
			vector<unsigned int> &v, unsigned int reactionIndex) {
		if (v.empty() || v.back() != reactionIndex)
			v.push_back(reactionIndex);
	}

	static bool generalMembershipFilterEnabled() {
		static int enabled = -1;
		if (enabled < 0) {
			/* Opt-in. Skipping a molecule's registration walk also skips the
			 * MappingSet churn that walk performs, so the order of a ReactantList
			 * — and therefore which molecule pickRandom selects — depends on
			 * whether the filter was active. That changes seeded trajectories
			 * relative to BNG3's full-walk behavior, which the seeded connectivity
			 * oracle requires to be byte-identical. NFSIM_MEMFILTER=1 enables it
			 * for same-binary throughput measurements only. */
			const char *value = getenv("NFSIM_MEMFILTER");
			enabled = (value != 0 && value[0] != '\0' && value[0] != '0') ? 1 : 0;
		}
		return enabled == 1;
	}

	static bool generalMembershipDiffEnabled() {
		static int enabled = -1;
		if (enabled < 0) {
			const char *value = getenv("NFSIM_MEMFILTER_DIFF");
			enabled = (value != 0 && value[0] != '\0' && value[0] != '0') ? 1 : 0;
		}
		return enabled == 1;
	}
	static bool generalMembershipFilterForceEnabled() {
		static int enabled = -1;
		if (enabled < 0) {
			const char *value = getenv("NFSIM_MEMFILTER_FORCE");
			enabled = (value != 0 && value[0] != '\0' && value[0] != '0') ? 1 : 0;
		}
		return enabled == 1;
	}
	static unsigned int generalMembershipFilterMinRegistrations() {
		static int threshold = -1;
		if (threshold < 0) {
			/* The membership filter is already opt-in.  Once enabled, even very
			 * small registration lists benefit when updates repeatedly revisit
			 * unchanged rules (notably translation lsu/mrna types).  The former
			 * cutoff of 16 forced a full walk/tryToAdd path for those lists and
			 * was consistently slower in fixed-seed sweeps.  Keep the environment
			 * override for diagnostics/tuning. */
			threshold = 1;
			const char *value = getenv("NFSIM_MEMFILTER_MIN_REGISTRATIONS");
			if (value != 0) {
				char *end = 0;
				long parsed = strtol(value, &end, 10);
				if (end != value && parsed >= 0) threshold = static_cast<int>(parsed);
			}
		}
		return static_cast<unsigned int>(threshold);
	}
	static unsigned int generalMembershipFilterTuning(
			const char *name, unsigned int fallback) {
		const char *value = getenv(name);
		if (value != 0) {
			char *end = 0;
			long parsed = strtol(value, &end, 10);
			if (end != value && *end == '\0' && parsed >= 0 &&
					static_cast<unsigned long>(parsed) <=
					static_cast<unsigned long>(numeric_limits<unsigned int>::max()))
				return static_cast<unsigned int>(parsed);
		}
		return fallback;
	}
	static unsigned int generalMembershipFilterLossBitmapMin() {
		static unsigned int threshold =
				generalMembershipFilterTuning("NFSIM_MEMFILTER_LOSS_BITMAP_MIN", 64);
		return threshold;
	}
	static unsigned int generalMembershipFilterLossActiveMultiplier() {
		static unsigned int multiplier = generalMembershipFilterTuning(
				"NFSIM_MEMFILTER_LOSS_ACTIVE_MULTIPLIER", 8);
		return multiplier;
	}
	static bool candidateTraceEnabled() {
		static int enabled = -1;
		if (enabled < 0)
			enabled = getenv("NFSIM_CANDTRACE") != 0 ? 1 : 0;
		return enabled == 1;
	}
	bool memprofEnabled();
}
namespace NFcore {
	void memprofCandidateProbe(const std::string &name, long long vectorProbes,
			long long activeProbes, long long rootChecks);
}

void MoleculeType::buildMembershipDependencyIndex()
{
	membershipStateRequiredCandidates.clear();
	membershipStateExcludedCandidates.clear();
	membershipBondFreeCandidates.clear();
	membershipBondFreeGainFallbackCandidates.clear();
	membershipBondFreeGainAnchorComponents.clear();
	membershipBondFreeGainCompositeCandidates.clear();
	membershipBondBoundCandidates.clear();
	membershipBondBoundGainFallbackCandidates.clear();
	membershipBondBoundGainAnchorComponents.clear();
	membershipBondBoundGainCompositeCandidates.clear();
	membershipTopologyCandidates.clear();
	membershipTopologyGainFallbackCandidates.clear();
	membershipTopologyGainAnchorComponents.clear();
	membershipTopologyGainCompositeCandidates.clear();
	membershipBondFreeGainLookups.clear();
	membershipBondBoundGainLookups.clear();
	membershipTopologyGainLookups.clear();
	unconditionalMembershipCandidates.clear();
	membershipNonlocalPropensityCandidates.clear();
	membershipRootContexts.assign(reactions.size(),
			vector<MembershipRootPredicate>());
	membershipRootContextSafe.assign(reactions.size(), 0);
	membershipRootRequiredBoundMasks.assign(reactions.size(), 0);
	membershipRootRequiredFreeMasks.assign(reactions.size(), 0);
	membershipCandidateViews.clear();
	membershipLossCandidateBitmaps.clear();
	membershipCandidateSeen.assign(reactions.size(), 0);
	membershipActiveSnapshot.assign(reactions.size(), 0);
	membershipActiveSnapshotGeneration = 0;
	membershipRootContextChecked.assign(reactions.size(), 0);
	membershipRootContextResult.assign(reactions.size(), 0);
	membershipCandidateScratch.clear();
	membershipCandidateScratch.reserve(reactions.size());
	membershipEventCandidatePlan.clear();
	membershipEventPlanGeneration = ~0ULL;
	membershipEventPlanCache.clear();
	membershipEventPlanCacheSize = 0;
	activeMembershipEventPlan = 0;
	activeMembershipLossUnion = 0;
	activeMembershipLossTotal = 0;
	membershipCandidateGeneration = 0;

	for (unsigned int r = 0; r < reactions.size(); ++r) {
		if (!reactions[r]->propensityDependsOnlyOnMembership())
			membershipNonlocalPropensityCandidates.push_back(r);
		TemplateMolecule *root = reactions[r]->getReactantTemplate(
				reactionPositions[r]);
		vector<MembershipPatternDependency> dependencies;
		if (root == 0 || !root->collectMembershipDependencies(dependencies)) {
			appendUniqueMembershipIndex(unconditionalMembershipCandidates, r);
			continue;
		}
		vector<MembershipPatternDependency> rootDependencies;
		bool rootDependenciesSafe =
				root->collectRootMembershipDependencies(rootDependencies);
		bool hasCompositeBondAnchor = false;
		int compositeBondAnchorScore = -1;
		MembershipPatternDependency compositeBondAnchor;
		if (rootDependenciesSafe) {
			vector<MembershipRootPredicate> &stored = membershipRootContexts[r];
			stored.reserve(rootDependencies.size());
			for (vector<MembershipPatternDependency>::const_iterator rit =
					rootDependencies.begin(); rit != rootDependencies.end(); ++rit) {
				/* Free/bound predicates on the first 64 components are represented
				 * completely by the compiled root masks below.  Do not also retain
				 * them in the generic predicate vector: surviving candidates would
				 * otherwise iterate and switch over predicates whose result is already
				 * proven by two bit operations.  State and topology predicates remain
				 * in the vector because they carry information beyond occupancy. */
				const bool compiledBondPredicate = rit->componentIndex >= 0 &&
					rit->componentIndex < 64 &&
					(rit->kind == MembershipPatternDependency::BOND_FREE ||
					 rit->kind == MembershipPatternDependency::BOND_BOUND);
				if (!compiledBondPredicate) {
					MembershipRootPredicate p;
					p.kind = static_cast<int>(rit->kind);
					p.componentIndex = rit->componentIndex;
					p.stateValue = rit->stateValue;
					p.partnerType = rit->partnerType;
					p.partnerComponentIndex = rit->partnerComponentIndex;
					p.partnerStateComponentIndex = rit->partnerStateComponentIndex;
					stored.push_back(p);
				}
				if (rit->componentIndex >= 0 && rit->componentIndex < 64) {
					const std::uint64_t bit = std::uint64_t(1) << rit->componentIndex;
					if (rit->kind == MembershipPatternDependency::BOND_FREE)
						membershipRootRequiredFreeMasks[r] |= bit;
					else if (rit->kind == MembershipPatternDependency::BOND_BOUND ||
							rit->kind == MembershipPatternDependency::TOPOLOGY)
						membershipRootRequiredBoundMasks[r] |= bit;
				}
				/* A required explicit topology dependency is a sound necessary-condition
				 * anchor for gain-side partitioning on both small machinery and large
				 * polymers.  The key already contains the concrete component index, so
				 * positional polymers remain exact rather than collapsing to a generic
				 * molecule-type bucket. */
				if (rit->kind == MembershipPatternDependency::TOPOLOGY &&
						rit->componentIndex >= 0 && rit->partnerType != 0 &&
						rit->partnerComponentIndex >= 0) {
					/* Prefer the anchor whose partner type has the largest component
					 * space.  In positional polymer models this selects, for example,
					 * ribosome.asite->mRNA.pN over ribosome.hit3->ribosome.hit5,
					 * turning the latter's generic machinery bond into a selective key. */
					int score = rit->partnerType->getNumOfComponents();
					if (!hasCompositeBondAnchor || score > compositeBondAnchorScore) {
						compositeBondAnchor = *rit;
						compositeBondAnchorScore = score;
						hasCompositeBondAnchor = true;
					}
				}
			}
			membershipRootContextSafe[r] = 1;
		}

		for (vector<MembershipPatternDependency>::const_iterator it =
				dependencies.begin(); it != dependencies.end(); ++it) {
			const MembershipPatternDependency &d = *it;
			if (d.moleculeType == 0 || d.componentIndex < 0) {
				appendUniqueMembershipIndex(unconditionalMembershipCandidates, r);
				continue;
			}
			switch (d.kind) {
			case MembershipPatternDependency::STATE_REQUIRED:
				appendUniqueMembershipIndex(
					membershipStateRequiredCandidates[
						MembershipStateKey(d.moleculeType, d.componentIndex,
							d.stateValue)], r);
				break;
			case MembershipPatternDependency::STATE_EXCLUDED:
				appendUniqueMembershipIndex(
					membershipStateExcludedCandidates[
						MembershipStateKey(d.moleculeType, d.componentIndex,
							d.stateValue)], r);
				break;
			case MembershipPatternDependency::BOND_FREE: {
				MembershipComponentKey trigger(d.moleculeType, d.componentIndex);
				appendUniqueMembershipIndex(membershipBondFreeCandidates[trigger], r);
				if (hasCompositeBondAnchor) {
					MembershipBondContextKey contextKey(
						d.moleculeType, d.componentIndex,
						compositeBondAnchor.componentIndex,
						compositeBondAnchor.partnerType,
						compositeBondAnchor.partnerComponentIndex);
					appendUniqueMembershipIndex(
						membershipBondFreeGainCompositeCandidates[contextKey], r);
					vector<int> &anchors = membershipBondFreeGainAnchorComponents[trigger];
					if (std::find(anchors.begin(), anchors.end(),
							compositeBondAnchor.componentIndex) == anchors.end())
						anchors.push_back(compositeBondAnchor.componentIndex);
				} else {
					appendUniqueMembershipIndex(
						membershipBondFreeGainFallbackCandidates[trigger], r);
				}
				break;
			}
			case MembershipPatternDependency::BOND_BOUND: {
				MembershipComponentKey trigger(d.moleculeType, d.componentIndex);
				/* Keep the complete list for loss-side current-membership
				 * intersection.  Gain-side lookup may use the composite partition. */
				appendUniqueMembershipIndex(
					membershipBondBoundCandidates[trigger], r);
				if (hasCompositeBondAnchor) {
					MembershipBondContextKey contextKey(
						d.moleculeType, d.componentIndex,
						compositeBondAnchor.componentIndex,
						compositeBondAnchor.partnerType,
						compositeBondAnchor.partnerComponentIndex);
					appendUniqueMembershipIndex(
						membershipBondBoundGainCompositeCandidates[contextKey], r);
					vector<int> &anchors =
						membershipBondBoundGainAnchorComponents[trigger];
					if (std::find(anchors.begin(), anchors.end(),
							compositeBondAnchor.componentIndex) == anchors.end())
						anchors.push_back(compositeBondAnchor.componentIndex);
				} else {
					appendUniqueMembershipIndex(
						membershipBondBoundGainFallbackCandidates[trigger], r);
				}
				break;
			}
			case MembershipPatternDependency::PARTNER_STATE_REQUIRED:
			case MembershipPatternDependency::PARTNER_STATE_EXCLUDED:
				/* Partner-state predicates are root-context refinements only.  The
				 * full connected-pattern dependency list already contributes the
				 * partner template's state constraint as STATE_REQUIRED/EXCLUDED,
				 * keyed by the partner MoleculeType/component above.  Indexing these
				 * again here would duplicate state-change triggers under the root
				 * bond endpoint; retain them only in membershipRootContexts/views. */
				break;
			case MembershipPatternDependency::TOPOLOGY: {
				if (d.partnerType == 0 || d.partnerComponentIndex < 0) {
					appendUniqueMembershipIndex(unconditionalMembershipCandidates, r);
					break;
				}
				MembershipTopologyKey trigger(d.moleculeType, d.componentIndex,
					d.partnerType, d.partnerComponentIndex);
				/* Complete list retained for loss-side current-membership
				 * intersection. Gain-side lookup can be partitioned by an
				 * independent explicit root topology anchor. */
				appendUniqueMembershipIndex(membershipTopologyCandidates[trigger], r);
				bool anchorIsTrigger = hasCompositeBondAnchor &&
					compositeBondAnchor.moleculeType == d.moleculeType &&
					compositeBondAnchor.componentIndex == d.componentIndex &&
					compositeBondAnchor.partnerType == d.partnerType &&
					compositeBondAnchor.partnerComponentIndex == d.partnerComponentIndex;
				if (hasCompositeBondAnchor && !anchorIsTrigger) {
					MembershipTopologyContextKey contextKey(
						d.moleculeType, d.componentIndex, d.partnerType,
						d.partnerComponentIndex, compositeBondAnchor.componentIndex,
						compositeBondAnchor.partnerType,
						compositeBondAnchor.partnerComponentIndex);
					appendUniqueMembershipIndex(
						membershipTopologyGainCompositeCandidates[contextKey], r);
					vector<int> &anchors = membershipTopologyGainAnchorComponents[trigger];
					if (std::find(anchors.begin(), anchors.end(),
							compositeBondAnchor.componentIndex) == anchors.end())
						anchors.push_back(compositeBondAnchor.componentIndex);
				} else {
					appendUniqueMembershipIndex(
						membershipTopologyGainFallbackCandidates[trigger], r);
				}
				break;
			}
			}
		}
	}
	/* Anchor component lists are constructed in reaction order, not component
	 * order. Sort them once so hot gain application can intersect a broad
	 * static anchor set with the molecule's sparse, sorted bonded-component
	 * list from whichever side is smaller. */
	for (auto it = membershipBondFreeGainAnchorComponents.begin();
			it != membershipBondFreeGainAnchorComponents.end(); ++it) {
		std::sort(it->second.begin(), it->second.end());
		it->second.erase(std::unique(it->second.begin(), it->second.end()),
			it->second.end());
	}
	for (auto it = membershipBondBoundGainAnchorComponents.begin();
			it != membershipBondBoundGainAnchorComponents.end(); ++it) {
		std::sort(it->second.begin(), it->second.end());
		it->second.erase(std::unique(it->second.begin(), it->second.end()),
			it->second.end());
	}
	for (auto it = membershipTopologyGainAnchorComponents.begin();
			it != membershipTopologyGainAnchorComponents.end(); ++it) {
		std::sort(it->second.begin(), it->second.end());
		it->second.erase(std::unique(it->second.begin(), it->second.end()),
			it->second.end());
	}
	/* Retain the validated iteration23 loss-vector cutoff and active-side
	 * crossover. Large vectors get O(1) membership tests; smaller ones keep the
	 * existing binary-search path. */
	auto ensureLossBitmap = [&](const vector<unsigned int> *vec) {
		if (vec == 0 || vec->size() < generalMembershipFilterLossBitmapMin() ||
				membershipLossCandidateBitmaps.count(vec))
			return;
		vector<std::uint64_t> bitmap((reactions.size() + 63u) / 64u, 0);
		for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it)
			if (*it < reactions.size())
				bitmap[*it >> 6] |= std::uint64_t(1) << (*it & 63u);
		membershipLossCandidateBitmaps.emplace(vec, std::move(bitmap));
	};
	for (auto &kv : membershipStateRequiredCandidates) ensureLossBitmap(&kv.second);
	for (auto &kv : membershipStateExcludedCandidates) ensureLossBitmap(&kv.second);
	for (auto &kv : membershipBondFreeCandidates) ensureLossBitmap(&kv.second);
	for (auto &kv : membershipBondBoundCandidates) ensureLossBitmap(&kv.second);
	for (auto &kv : membershipTopologyCandidates) ensureLossBitmap(&kv.second);

	/* Gain-vector views carry two independent proofs: complete small-root
	 * occupancy and one common first residual topology predicate. */
	const bool smallOccupancyRoot = numOfComponents > 0 && numOfComponents <= 6;
	const unsigned int maskCount = smallOccupancyRoot ? (1u << numOfComponents) : 0;
	auto ensureView = [&](const vector<unsigned int> *vec) {
		/* A candidate view only pays for itself when it can eliminate multiple
		 * root-context probes. Occupancy indexing already requires four entries
		 * and state indexing requires eight; previously 1-3 entry vectors could
		 * still allocate a hash entry solely for the common-topology shortcut.
		 * That creates thousands of startup-only objects in generated models to
		 * save at most a couple of cheap checks per affected event. */
		static const std::size_t minCandidateViewSize = []() -> std::size_t {
			const char *value = getenv("NFSIM_MEMFILTER_MIN_VIEW_SIZE");
			if (value != 0) {
				char *end = 0;
				unsigned long parsed = strtoul(value, &end, 10);
				if (end != value && *end == '\0' && parsed <= 65536UL)
					return static_cast<std::size_t>(parsed);
			}
			/* Small candidate vectors are faster to inspect directly than to build,
			 * hash and retain an auxiliary occupancy/state/topology view.  A sweep
			 * across RASI, uORF and the combinatorial stress fixtures put the startup
			 * crossover near 16 entries; larger/selective families keep the indexed
			 * path that delivers the large event-loop gains. */
			return std::size_t(16);
		}();
		if (vec == 0 || vec->size() < minCandidateViewSize ||
				membershipCandidateViews.count(vec)) return;
		MembershipCandidateView view; view.candidates = vec;
		if (smallOccupancyRoot && vec->size() >= 4) {
			view.byBoundMask.resize(maskCount);
			for (unsigned int mask = 0; mask < maskCount; ++mask) {
				vector<unsigned int> &out = view.byBoundMask[mask];
				out.reserve(vec->size());
				for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
					unsigned int r = *it;
					std::uint64_t bound = membershipRootRequiredBoundMasks[r];
					std::uint64_t free = membershipRootRequiredFreeMasks[r];
					if ((std::uint64_t(mask) & bound) == bound &&
							(std::uint64_t(mask) & free) == 0) out.push_back(r);
				}
			}
		}
		/* Generated rule families often differ only by one finite root state
		 * (for example R(x~0..63)).  Occupancy cannot separate those rules, so
		 * build one state-indexed ordered view when it is both selective and
		 * compact.  The 4x total-entry cap prevents wildcard/exclusion-heavy
		 * vectors from trading CPU for a large startup/memory regression. */
		if (vec->size() >= 8) {
			set<int> stateComponents;
			for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
				unsigned int r = *it;
				if (r >= membershipRootContexts.size() || !membershipRootContextSafe[r]) continue;
				const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
				for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit)
					if ((pit->kind == MembershipPatternDependency::STATE_REQUIRED ||
						 pit->kind == MembershipPatternDependency::STATE_EXCLUDED) &&
						 pit->componentIndex >= 0 && pit->componentIndex < numOfComponents)
						stateComponents.insert(pit->componentIndex);
			}
			size_t bestMaxBucket = vec->size();
			int bestComponent = -1;
			vector<size_t> bestCounts;
			for (set<int>::const_iterator cit=stateComponents.begin(); cit!=stateComponents.end(); ++cit) {
				int componentIndex = *cit;
				size_t stateCount = possibleCompStates[componentIndex].size();
				if (stateCount < 2 || stateCount > 256) continue;
				vector<size_t> counts(stateCount, 0);
				size_t totalEntries = 0;
				for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
					unsigned int r = *it;
					const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
					for (size_t stateValue=0; stateValue<stateCount; ++stateValue) {
						bool allowed = true;
						for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
							if (pit->componentIndex != componentIndex) continue;
							if (pit->kind == MembershipPatternDependency::STATE_REQUIRED &&
									pit->stateValue != static_cast<int>(stateValue)) { allowed = false; break; }
							if (pit->kind == MembershipPatternDependency::STATE_EXCLUDED &&
									pit->stateValue == static_cast<int>(stateValue)) { allowed = false; break; }
						}
						if (allowed) { ++counts[stateValue]; ++totalEntries; }
					}
				}
				if (totalEntries > vec->size() * 4u) continue;
				size_t maxBucket = 0;
				for (size_t i=0; i<counts.size(); ++i) maxBucket = std::max(maxBucket, counts[i]);
				if (maxBucket < bestMaxBucket) {
					bestMaxBucket = maxBucket; bestComponent = componentIndex; bestCounts.swap(counts);
				}
			}
			if (bestComponent >= 0 && bestMaxBucket * 4u <= vec->size() * 3u) {
				view.stateComponentIndex = bestComponent;
				view.byStateValue.resize(bestCounts.size());
				for (size_t stateValue=0; stateValue<bestCounts.size(); ++stateValue)
					view.byStateValue[stateValue].reserve(bestCounts[stateValue]);
				for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
					unsigned int r = *it;
					const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
					for (size_t stateValue=0; stateValue<bestCounts.size(); ++stateValue) {
						bool allowed = true;
						for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
							if (pit->componentIndex != bestComponent) continue;
							if (pit->kind == MembershipPatternDependency::STATE_REQUIRED &&
									pit->stateValue != static_cast<int>(stateValue)) { allowed = false; break; }
							if (pit->kind == MembershipPatternDependency::STATE_EXCLUDED &&
									pit->stateValue == static_cast<int>(stateValue)) { allowed = false; break; }
						}
						if (allowed) view.byStateValue[stateValue].push_back(r);
					}
				}
			}
		}
		/* A directly bonded partner is just as cheap to inspect as a root-local
		 * state once the root bond is known.  Build one selective partner-state
		 * view so mutually-exclusive partner-state rule families do not scan and
		 * reject every rule on every event. */
		if (vec->size() >= 8) {
			struct PartnerSelector {
				int rootComponent; MoleculeType *partnerType;
				int partnerBondComponent; int stateComponent;
			};
			vector<PartnerSelector> selectors;
			for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
				unsigned int r = *it;
				if (r >= membershipRootContexts.size() || !membershipRootContextSafe[r]) continue;
				const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
				for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
					if (pit->kind != MembershipPatternDependency::PARTNER_STATE_REQUIRED &&
						pit->kind != MembershipPatternDependency::PARTNER_STATE_EXCLUDED) continue;
					if (pit->componentIndex < 0 || pit->componentIndex >= numOfComponents ||
						pit->partnerType == 0 || pit->partnerComponentIndex < 0 ||
						pit->partnerStateComponentIndex < 0 ||
						pit->partnerStateComponentIndex >= pit->partnerType->numOfComponents) continue;
					PartnerSelector candidate = {pit->componentIndex, pit->partnerType,
						pit->partnerComponentIndex, pit->partnerStateComponentIndex};
					bool seen = false;
					for (vector<PartnerSelector>::const_iterator sit=selectors.begin(); sit!=selectors.end(); ++sit)
						if (sit->rootComponent == candidate.rootComponent && sit->partnerType == candidate.partnerType &&
							sit->partnerBondComponent == candidate.partnerBondComponent && sit->stateComponent == candidate.stateComponent) { seen = true; break; }
					if (!seen) selectors.push_back(candidate);
				}
			}
			size_t bestMaxBucket = vec->size();
			int bestSelector = -1;
			vector<size_t> bestCounts;
			for (size_t si=0; si<selectors.size(); ++si) {
				const PartnerSelector &selector = selectors[si];
				size_t stateCount = selector.partnerType->possibleCompStates[selector.stateComponent].size();
				if (stateCount < 2 || stateCount > 4096) continue;
				vector<size_t> counts(stateCount, 0);
				size_t totalEntries = 0;
				if (stateCount <= 256) {
					/* Small state spaces are faster with the original dense loop. */
					for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
						unsigned int r = *it;
						const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
						for (size_t stateValue=0; stateValue<stateCount; ++stateValue) {
							bool allowed = true;
							for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
								if (pit->componentIndex != selector.rootComponent || pit->partnerType != selector.partnerType ||
									pit->partnerComponentIndex != selector.partnerBondComponent ||
									pit->partnerStateComponentIndex != selector.stateComponent) continue;
								if (pit->kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED &&
									pit->stateValue != static_cast<int>(stateValue)) { allowed = false; break; }
								if (pit->kind == MembershipPatternDependency::PARTNER_STATE_EXCLUDED &&
									pit->stateValue == static_cast<int>(stateValue)) { allowed = false; break; }
							}
							if (allowed) { ++counts[stateValue]; ++totalEntries; }
						}
					}
				} else {
					/* Large finite-state domains need sparse counting.  Exact requirements
					 * touch one bucket; unconstrained rules contribute a wildcard base and
					 * exclusions subtract from individual buckets. */
					vector<size_t> exactCounts(stateCount, 0);
					vector<size_t> excludedWildcardCounts(stateCount, 0);
					size_t wildcardCount = 0;
					const size_t entryLimit = vec->size() * 4u;
					for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
						unsigned int r = *it;
						const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
						int requiredState = -1;
						bool impossible = false;
						vector<int> excludedStates;
						for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
							if (pit->componentIndex != selector.rootComponent || pit->partnerType != selector.partnerType ||
								pit->partnerComponentIndex != selector.partnerBondComponent ||
								pit->partnerStateComponentIndex != selector.stateComponent) continue;
							if (pit->kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED) {
								if (requiredState >= 0 && requiredState != pit->stateValue) impossible = true;
								requiredState = pit->stateValue;
							} else if (pit->kind == MembershipPatternDependency::PARTNER_STATE_EXCLUDED &&
									pit->stateValue >= 0 && static_cast<size_t>(pit->stateValue) < stateCount &&
									std::find(excludedStates.begin(), excludedStates.end(), pit->stateValue) == excludedStates.end()) {
								excludedStates.push_back(pit->stateValue);
							}
						}
						if (impossible) continue;
						if (requiredState >= 0) {
							if (static_cast<size_t>(requiredState) >= stateCount ||
									std::find(excludedStates.begin(), excludedStates.end(), requiredState) != excludedStates.end())
								continue;
							++exactCounts[requiredState];
							++totalEntries;
						} else {
							const size_t allowedCount = stateCount - excludedStates.size();
							if (totalEntries > entryLimit || allowedCount > entryLimit - totalEntries) {
								totalEntries = entryLimit + 1;
								break;
							}
							totalEntries += allowedCount;
							++wildcardCount;
							for (vector<int>::const_iterator eit=excludedStates.begin(); eit!=excludedStates.end(); ++eit)
								++excludedWildcardCounts[*eit];
						}
					}
					if (totalEntries <= entryLimit)
						for (size_t stateValue=0; stateValue<stateCount; ++stateValue)
							counts[stateValue] = exactCounts[stateValue] + wildcardCount - excludedWildcardCounts[stateValue];
				}
				if (totalEntries > vec->size() * 4u) continue;
				size_t maxBucket = 0;
				for (size_t i=0; i<counts.size(); ++i) maxBucket = std::max(maxBucket, counts[i]);
				if (maxBucket < bestMaxBucket) { bestMaxBucket = maxBucket; bestSelector = static_cast<int>(si); bestCounts.swap(counts); }
			}
			if (bestSelector >= 0 && bestMaxBucket * 4u <= vec->size() * 3u) {
				const PartnerSelector &selector = selectors[bestSelector];
				view.partnerStateRootComponentIndex = selector.rootComponent;
				view.partnerStateType = selector.partnerType;
				view.partnerStateBondComponentIndex = selector.partnerBondComponent;
				view.partnerStateComponentIndex = selector.stateComponent;
				view.byPartnerStateValue.resize(bestCounts.size());
				for (size_t stateValue=0; stateValue<bestCounts.size(); ++stateValue)
					view.byPartnerStateValue[stateValue].reserve(bestCounts[stateValue]);
				if (bestCounts.size() <= 256) {
					for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
						unsigned int r = *it;
						const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
						for (size_t stateValue=0; stateValue<bestCounts.size(); ++stateValue) {
							bool allowed = true;
							for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
								if (pit->componentIndex != selector.rootComponent || pit->partnerType != selector.partnerType ||
									pit->partnerComponentIndex != selector.partnerBondComponent ||
									pit->partnerStateComponentIndex != selector.stateComponent) continue;
								if (pit->kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED && pit->stateValue != static_cast<int>(stateValue)) { allowed = false; break; }
								if (pit->kind == MembershipPatternDependency::PARTNER_STATE_EXCLUDED && pit->stateValue == static_cast<int>(stateValue)) { allowed = false; break; }
							}
							if (allowed) view.byPartnerStateValue[stateValue].push_back(r);
						}
					}
				} else {
					for (vector<unsigned int>::const_iterator it=vec->begin(); it!=vec->end(); ++it) {
						unsigned int r = *it;
						const vector<MembershipRootPredicate> &ctx = membershipRootContexts[r];
						int requiredState = -1;
						bool impossible = false;
						vector<int> excludedStates;
						for (vector<MembershipRootPredicate>::const_iterator pit=ctx.begin(); pit!=ctx.end(); ++pit) {
							if (pit->componentIndex != selector.rootComponent || pit->partnerType != selector.partnerType ||
								pit->partnerComponentIndex != selector.partnerBondComponent ||
								pit->partnerStateComponentIndex != selector.stateComponent) continue;
							if (pit->kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED) {
								if (requiredState >= 0 && requiredState != pit->stateValue) impossible = true;
								requiredState = pit->stateValue;
							} else if (pit->kind == MembershipPatternDependency::PARTNER_STATE_EXCLUDED &&
									pit->stateValue >= 0 && static_cast<size_t>(pit->stateValue) < bestCounts.size() &&
									std::find(excludedStates.begin(), excludedStates.end(), pit->stateValue) == excludedStates.end())
								excludedStates.push_back(pit->stateValue);
						}
						if (impossible) continue;
						if (requiredState >= 0) {
							if (static_cast<size_t>(requiredState) < view.byPartnerStateValue.size() &&
									std::find(excludedStates.begin(), excludedStates.end(), requiredState) == excludedStates.end())
								view.byPartnerStateValue[requiredState].push_back(r);
						} else {
							for (size_t stateValue=0; stateValue<view.byPartnerStateValue.size(); ++stateValue)
								if (std::find(excludedStates.begin(), excludedStates.end(), static_cast<int>(stateValue)) == excludedStates.end())
									view.byPartnerStateValue[stateValue].push_back(r);
						}
					}
				}
			}
		}
		/* If both one-dimensional state views are selective, materialize their
		 * exact intersections only when the table is small.  This collapses an
		 * N x M generated rule family directly to the matching cell. */
		if (!view.byStateValue.empty() && !view.byPartnerStateValue.empty()) {
			const size_t rootStates = view.byStateValue.size();
			const size_t partnerStates = view.byPartnerStateValue.size();
			if (rootStates <= 4096u / partnerStates) {
				const size_t cells = rootStates * partnerStates;
				if (cells <= 4096u) {
					vector<size_t> counts(cells, 0);
					size_t totalEntries = 0;
					size_t maxBucket = 0;
					for (size_t rs=0; rs<rootStates; ++rs) {
						const vector<unsigned int> &a = view.byStateValue[rs];
						for (size_t ps=0; ps<partnerStates; ++ps) {
							const vector<unsigned int> &b = view.byPartnerStateValue[ps];
							size_t ai=0, bi=0, count=0;
							while (ai<a.size() && bi<b.size()) {
								if (a[ai] < b[bi]) ++ai;
								else if (b[bi] < a[ai]) ++bi;
								else { ++count; ++ai; ++bi; }
							}
							counts[rs * partnerStates + ps] = count;
							totalEntries += count;
							maxBucket = std::max(maxBucket, count);
						}
					}
					if (totalEntries <= vec->size() * 4u && maxBucket * 4u <= vec->size() * 3u) {
						view.statePartnerStride = partnerStates;
						view.byStatePartnerValue.resize(cells);
						for (size_t rs=0; rs<rootStates; ++rs) {
							const vector<unsigned int> &a = view.byStateValue[rs];
							for (size_t ps=0; ps<partnerStates; ++ps) {
								vector<unsigned int> &out = view.byStatePartnerValue[rs * partnerStates + ps];
								out.reserve(counts[rs * partnerStates + ps]);
								const vector<unsigned int> &b = view.byPartnerStateValue[ps];
								size_t ai=0, bi=0;
								while (ai<a.size() && bi<b.size()) {
									if (a[ai] < b[bi]) ++ai;
									else if (b[bi] < a[ai]) ++bi;
									else { out.push_back(a[ai]); ++ai; ++bi; }
								}
							}
						}
					}
				}
			}
		}
		const MembershipRootPredicate *common = 0;
		bool commonTopology = true;
		for (vector<unsigned int>::const_iterator it=vec->begin();
				it!=vec->end(); ++it) {
			unsigned int r = *it;
			if (r >= membershipRootContexts.size() || !membershipRootContextSafe[r] ||
					membershipRootContexts[r].empty() ||
					membershipRootContexts[r][0].kind != MembershipPatternDependency::TOPOLOGY) {
				commonTopology = false;
				break;
			}
			const MembershipRootPredicate &candidate = membershipRootContexts[r][0];
			if (common == 0) common = &candidate;
			else if (common->componentIndex != candidate.componentIndex ||
					common->partnerType != candidate.partnerType ||
					common->partnerComponentIndex != candidate.partnerComponentIndex) {
				commonTopology = false;
				break;
			}
		}
		if (commonTopology && common != 0) {
			view.hasCommonRootTopology = true;
			view.commonRootTopology = *common;
		}
		if (!view.byBoundMask.empty() || !view.byStateValue.empty() ||
				!view.byPartnerStateValue.empty() || !view.byStatePartnerValue.empty() ||
				view.hasCommonRootTopology)
			membershipCandidateViews.emplace(vec, std::move(view));
	};
	for (auto &kv : membershipStateRequiredCandidates) ensureView(&kv.second);
	for (auto &kv : membershipStateExcludedCandidates) ensureView(&kv.second);
	for (auto &kv : membershipBondFreeGainFallbackCandidates) ensureView(&kv.second);
	for (auto &kv : membershipBondBoundGainFallbackCandidates) ensureView(&kv.second);
	for (auto &kv : membershipTopologyGainFallbackCandidates) ensureView(&kv.second);
	for (auto &kv : membershipBondFreeGainCompositeCandidates) ensureView(&kv.second);
	for (auto &kv : membershipBondBoundGainCompositeCandidates) ensureView(&kv.second);
	for (auto &kv : membershipTopologyGainCompositeCandidates) ensureView(&kv.second);
	auto candidateViewFor = [&](const vector<unsigned int> *vec) -> const MembershipCandidateView * {
		auto it = membershipCandidateViews.find(vec);
		return it == membershipCandidateViews.end() ? 0 : &it->second;
	};

	/* Resolve composite gain hashes into small static tables.  Candidate-vector
	 * storage stays owned by the immutable maps above; these tables only retain
	 * pointers, so no reaction lists are duplicated. */
	for (auto it = membershipBondFreeGainFallbackCandidates.begin();
			it != membershipBondFreeGainFallbackCandidates.end(); ++it)
		membershipBondFreeGainLookups[it->first].fallback = &it->second;
	for (auto it = membershipBondBoundGainFallbackCandidates.begin();
			it != membershipBondBoundGainFallbackCandidates.end(); ++it)
		membershipBondBoundGainLookups[it->first].fallback = &it->second;
	for (auto it = membershipTopologyGainFallbackCandidates.begin();
			it != membershipTopologyGainFallbackCandidates.end(); ++it)
		membershipTopologyGainLookups[it->first].fallback = &it->second;
	for (auto &kv : membershipBondFreeGainLookups) kv.second.fallbackView = candidateViewFor(kv.second.fallback);
	for (auto &kv : membershipBondBoundGainLookups) kv.second.fallbackView = candidateViewFor(kv.second.fallback);
	for (auto &kv : membershipTopologyGainLookups) kv.second.fallbackView = candidateViewFor(kv.second.fallback);
	auto setFallbackCommonTopology = [&](MembershipGainLookup &lookup) {
		lookup.fallbackHasCommonTopology = false;
		const vector<unsigned int> *vec = lookup.fallback;
		if (lookup.fallbackView != 0 || vec == 0 || vec->size() < 2) return;
		const MembershipRootPredicate *common = 0;
		for (vector<unsigned int>::const_iterator it = vec->begin(); it != vec->end(); ++it) {
			unsigned int r = *it;
			if (r >= membershipRootContexts.size() || !membershipRootContextSafe[r] ||
					membershipRootContexts[r].empty() ||
					membershipRootContexts[r][0].kind != MembershipPatternDependency::TOPOLOGY)
				return;
			const MembershipRootPredicate &candidate = membershipRootContexts[r][0];
			if (common == 0) common = &candidate;
			else if (common->componentIndex != candidate.componentIndex ||
					common->partnerType != candidate.partnerType ||
					common->partnerComponentIndex != candidate.partnerComponentIndex)
				return;
		}
		if (common == 0) return;
		lookup.fallbackHasCommonTopology = true;
		lookup.fallbackCommonTopology = *common;
	};
	for (auto &kv : membershipBondFreeGainLookups) setFallbackCommonTopology(kv.second);
	for (auto &kv : membershipBondBoundGainLookups) setFallbackCommonTopology(kv.second);
	for (auto &kv : membershipTopologyGainLookups) setFallbackCommonTopology(kv.second);

	auto appendBondComposite = [&](
			unordered_map<MembershipComponentKey, MembershipGainLookup, MembershipComponentKeyHash> &lookups,
			const MembershipBondContextKey &key, const vector<unsigned int> *candidates) {
		MembershipComponentKey trigger(key.triggerType, key.triggerComponent);
		MembershipGainLookup &lookup = lookups[trigger];
		MembershipAnchorCandidateLookup *anchor = 0;
		for (auto &a : lookup.anchors) if (a.anchorComponent == key.anchorComponent) { anchor = &a; break; }
		if (anchor == 0) {
			MembershipAnchorCandidateLookup fresh; fresh.anchorComponent = key.anchorComponent;
			lookup.anchors.push_back(fresh); anchor = &lookup.anchors.back();
		}
		MembershipPartnerCandidateEntry entry;
		entry.partnerType = key.partnerType; entry.partnerComponent = key.partnerComponent;
		entry.candidates = candidates; entry.candidateView = candidateViewFor(candidates); anchor->entries.push_back(entry);
	};
	for (auto it = membershipBondFreeGainCompositeCandidates.begin();
			it != membershipBondFreeGainCompositeCandidates.end(); ++it)
		appendBondComposite(membershipBondFreeGainLookups, it->first, &it->second);
	for (auto it = membershipBondBoundGainCompositeCandidates.begin();
			it != membershipBondBoundGainCompositeCandidates.end(); ++it)
		appendBondComposite(membershipBondBoundGainLookups, it->first, &it->second);
	for (auto it = membershipTopologyGainCompositeCandidates.begin();
			it != membershipTopologyGainCompositeCandidates.end(); ++it) {
		const MembershipTopologyContextKey &key = it->first;
		MembershipTopologyKey trigger(key.triggerType, key.triggerComponent,
				key.triggerPartnerType, key.triggerPartnerComponent);
		MembershipGainLookup &lookup = membershipTopologyGainLookups[trigger];
		MembershipAnchorCandidateLookup *anchor = 0;
		for (auto &a : lookup.anchors) if (a.anchorComponent == key.anchorComponent) { anchor = &a; break; }
		if (anchor == 0) {
			MembershipAnchorCandidateLookup fresh; fresh.anchorComponent = key.anchorComponent;
			lookup.anchors.push_back(fresh); anchor = &lookup.anchors.back();
		}
		MembershipPartnerCandidateEntry entry;
		entry.partnerType = key.anchorPartnerType; entry.partnerComponent = key.anchorPartnerComponent;
		entry.candidates = &it->second; entry.candidateView = candidateViewFor(&it->second); anchor->entries.push_back(entry);
	}
	auto orderGainLookup = [](MembershipGainLookup &lookup) {
		std::sort(lookup.anchors.begin(), lookup.anchors.end(),
			[](const MembershipAnchorCandidateLookup &a, const MembershipAnchorCandidateLookup &b){ return a.anchorComponent < b.anchorComponent; });

		for (auto &anchor : lookup.anchors) {
			// Generated positional rules can put hundreds of partner components
			// under one root anchor. Preserve ties so the first exact match stays
			// unchanged even if different partner types share a component number.
			if (anchor.entries.size() > 8u)
				std::stable_sort(anchor.entries.begin(), anchor.entries.end(),
					[](const MembershipPartnerCandidateEntry &a,
						const MembershipPartnerCandidateEntry &b) {
						return a.partnerComponent < b.partnerComponent;
					});
		}
	};
	for (auto &kv : membershipBondFreeGainLookups) orderGainLookup(kv.second);
	for (auto &kv : membershipBondBoundGainLookups) orderGainLookup(kv.second);
	for (auto &kv : membershipTopologyGainLookups) orderGainLookup(kv.second);

	membershipDependencyIndexBuilt = true;
}

bool MoleculeType::membershipRootPredicateMatches(
		Molecule *m, const MembershipRootPredicate &d) const
{
	if (m == 0 || d.componentIndex < 0 ||
			d.componentIndex >= m->getMoleculeType()->getNumOfComponents())
		return false;
	switch (d.kind) {
	case MembershipPatternDependency::STATE_REQUIRED:
		return m->getComponentState(d.componentIndex) == d.stateValue;
	case MembershipPatternDependency::STATE_EXCLUDED:
		return m->getComponentState(d.componentIndex) != d.stateValue;
	case MembershipPatternDependency::BOND_FREE:
		return !m->isBindingSiteBonded(d.componentIndex);
	case MembershipPatternDependency::BOND_BOUND:
		return m->isBindingSiteBonded(d.componentIndex);
	case MembershipPatternDependency::TOPOLOGY: {
		/* Check the stored endpoint before dereferencing the partner. */
		if (m->getBondedMoleculeBindingSiteIndex(d.componentIndex) !=
				d.partnerComponentIndex)
			return false;
		Molecule *partner = m->getBondedMolecule(d.componentIndex);
		return partner != 0 && partner->getMoleculeType() == d.partnerType;
	}
	case MembershipPatternDependency::PARTNER_STATE_REQUIRED:
	case MembershipPatternDependency::PARTNER_STATE_EXCLUDED: {
		if (m->getBondedMoleculeBindingSiteIndex(d.componentIndex) !=
				d.partnerComponentIndex)
			return false;
		Molecule *partner = m->getBondedMolecule(d.componentIndex);
		if (partner == 0 || partner->getMoleculeType() != d.partnerType ||
				d.partnerStateComponentIndex < 0 ||
				d.partnerStateComponentIndex >= d.partnerType->getNumOfComponents())
			return false;
		const int state = partner->getComponentState(d.partnerStateComponentIndex);
		return d.kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED ?
				state == d.stateValue : state != d.stateValue;
	}
	}
	return false;
}

bool MoleculeType::membershipRootContextMatches(
		Molecule *m, unsigned int reactionIndex, bool skipFirstPredicate,
		bool skipOccupancyMasks, int skipStateComponent,
		int skipPartnerStateRootComponent, MoleculeType *skipPartnerStateType,
		int skipPartnerStateBondComponent, int skipPartnerStateComponent) const
{
	if (m == 0 || reactionIndex >= membershipRootContexts.size() ||
			reactionIndex >= membershipRootContextSafe.size() ||
			!membershipRootContextSafe[reactionIndex])
		return true;
	if (!skipOccupancyMasks) {
		const std::uint64_t boundMask = m->getBoundComponentMask();
		const std::uint64_t requiredBound = membershipRootRequiredBoundMasks[reactionIndex];
		const std::uint64_t requiredFree = membershipRootRequiredFreeMasks[reactionIndex];
		if ((boundMask & requiredBound) != requiredBound ||
				(boundMask & requiredFree) != 0)
			return false;
	}
	const vector<MembershipRootPredicate> &context =
		membershipRootContexts[reactionIndex];
	vector<MembershipRootPredicate>::const_iterator begin = context.begin();
	if (skipFirstPredicate && begin != context.end()) ++begin;
	for (vector<MembershipRootPredicate>::const_iterator it = begin;
			it != context.end(); ++it) {
		if (skipStateComponent >= 0 && it->componentIndex == skipStateComponent &&
				(it->kind == MembershipPatternDependency::STATE_REQUIRED ||
				 it->kind == MembershipPatternDependency::STATE_EXCLUDED))
			continue;
		if (skipPartnerStateRootComponent >= 0 &&
				it->componentIndex == skipPartnerStateRootComponent &&
				it->partnerType == skipPartnerStateType &&
				it->partnerComponentIndex == skipPartnerStateBondComponent &&
				it->partnerStateComponentIndex == skipPartnerStateComponent &&
				(it->kind == MembershipPatternDependency::PARTNER_STATE_REQUIRED ||
				 it->kind == MembershipPatternDependency::PARTNER_STATE_EXCLUDED))
			continue;
		if (!membershipRootPredicateMatches(m, *it)) return false;
	}
	return true;
}

void MoleculeType::appendMembershipCandidateVector(
		const vector<unsigned int> *candidates, Molecule *m, bool lossOnly,
		bool requireCurrentRootContext, const MembershipCandidateView *candidateView,
		const vector<std::uint64_t> *resolvedLossBitmap, bool lossBitmapResolved)
{
	if (candidates == 0) return;
	// Reject a shared topology failure before resolving state/occupancy views.
	// View selection only reads the molecule; it cannot change this predicate.
	bool commonTopologyProven = false;
	if (requireCurrentRootContext && candidateView != 0 &&
			candidateView->hasCommonRootTopology) {
		if (!membershipRootPredicateMatches(m, candidateView->commonRootTopology))
			return;
		commonTopologyProven = true;
	}
	bool occupancyProven = false;
	int stateComponentProven = -1;
	bool partnerStateProven = false;
	if (requireCurrentRootContext && candidateView != 0 && m != 0) {
		const vector<unsigned int> *occupancyCandidates = 0;
		const vector<unsigned int> *stateCandidates = 0;
		const vector<unsigned int> *partnerStateCandidates = 0;
		const vector<unsigned int> *combinedStateCandidates = 0;
		int rootStateValue = -1;
		int partnerStateValue = -1;
		unsigned int mask = static_cast<unsigned int>(m->getBoundComponentMask());
		if (mask < candidateView->byBoundMask.size())
			occupancyCandidates = &candidateView->byBoundMask[mask];
		if (candidateView->stateComponentIndex >= 0 &&
				candidateView->stateComponentIndex < numOfComponents) {
			rootStateValue = m->getComponentState(candidateView->stateComponentIndex);
			if (rootStateValue >= 0 && static_cast<size_t>(rootStateValue) <
					candidateView->byStateValue.size())
				stateCandidates = &candidateView->byStateValue[rootStateValue];
		}
		if (candidateView->partnerStateRootComponentIndex >= 0 &&
				candidateView->partnerStateRootComponentIndex < numOfComponents &&
				candidateView->partnerStateType != 0 &&
				m->getBondedMoleculeBindingSiteIndex(candidateView->partnerStateRootComponentIndex) ==
					candidateView->partnerStateBondComponentIndex) {
			Molecule *partner = m->getBondedMolecule(candidateView->partnerStateRootComponentIndex);
			if (partner != 0 && partner->getMoleculeType() == candidateView->partnerStateType &&
					candidateView->partnerStateComponentIndex >= 0 &&
					candidateView->partnerStateComponentIndex < candidateView->partnerStateType->getNumOfComponents()) {
				partnerStateValue = partner->getComponentState(candidateView->partnerStateComponentIndex);
				if (partnerStateValue >= 0 && static_cast<size_t>(partnerStateValue) < candidateView->byPartnerStateValue.size())
					partnerStateCandidates = &candidateView->byPartnerStateValue[partnerStateValue];
			}
		}
		if (rootStateValue >= 0 && partnerStateValue >= 0 &&
				candidateView->statePartnerStride != 0) {
			const size_t flat = static_cast<size_t>(rootStateValue) * candidateView->statePartnerStride +
					static_cast<size_t>(partnerStateValue);
			if (flat < candidateView->byStatePartnerValue.size())
				combinedStateCandidates = &candidateView->byStatePartnerValue[flat];
		}
		/* All views are exact ordered subsequences.  Select the smallest; any
		 * unselected predicate class is still checked by the normal root filter. */
		const vector<unsigned int> *best = occupancyCandidates;
		int bestKind = occupancyCandidates != 0 ? 1 : 0;
		if (stateCandidates != 0 && (best == 0 || stateCandidates->size() < best->size())) { best = stateCandidates; bestKind = 2; }
		if (partnerStateCandidates != 0 && (best == 0 || partnerStateCandidates->size() < best->size())) { best = partnerStateCandidates; bestKind = 3; }
		if (combinedStateCandidates != 0 && (best == 0 || combinedStateCandidates->size() < best->size())) { best = combinedStateCandidates; bestKind = 4; }
		if (best != 0) {
			candidates = best;
			if (bestKind == 1) occupancyProven = true;
			else if (bestKind == 2) stateComponentProven = candidateView->stateComponentIndex;
			else if (bestKind == 3) partnerStateProven = true;
			else if (bestKind == 4) { stateComponentProven = candidateView->stateComponentIndex; partnerStateProven = true; }
		}
	}
	auto rootContextMatchesCached = [&](unsigned int r) -> bool {
		if (!requireCurrentRootContext) return true;
		if (membershipRootContextChecked[r] != membershipCandidateGeneration) {
			membershipRootContextChecked[r] = membershipCandidateGeneration;
			membershipRootContextResult[r] =
				membershipRootContextMatches(m, r, commonTopologyProven,
						occupancyProven, stateComponentProven,
						partnerStateProven ? candidateView->partnerStateRootComponentIndex : -1,
						partnerStateProven ? candidateView->partnerStateType : 0,
						partnerStateProven ? candidateView->partnerStateBondComponentIndex : -1,
						partnerStateProven ? candidateView->partnerStateComponentIndex : -1) ? 1 : 0;
		}
		return membershipRootContextResult[r] != 0;
	};
	if (lossOnly && m != 0) {
		const vector<int> &active = m->getActiveReactionMembershipIndices();
		/* Broad loss lists are especially pathological in translation models:
		 * hundreds or thousands of rules may require a generic bound/unbound
		 * predicate, while this particular molecule participates in only a small
		 * number of local entries.  Both sets are exact, so intersect from the
		 * smaller side. Candidate vectors are built in monotonically increasing
		 * local-index order, making binary_search valid. */
		if (active.empty()) return;
		if (candidates->size() > active.size() *
				generalMembershipFilterLossActiveMultiplier()) {
			const vector<std::uint64_t> *bitmap = resolvedLossBitmap;
			if (!lossBitmapResolved) {
				auto bitmapIt = membershipLossCandidateBitmaps.find(candidates);
				bitmap = bitmapIt == membershipLossCandidateBitmaps.end()
						? 0 : &bitmapIt->second;
			}
			if (memprofEnabled())
				NFcore::memprofCandidateProbe(name, 0,
						static_cast<long long>(active.size()), 0);
			for (vector<int>::const_iterator ait = active.begin();
					ait != active.end(); ++ait) {
				if (*ait < 0) continue;
				unsigned int r = static_cast<unsigned int>(*ait);
				if (bitmap != 0) {
					if ((r >> 6) >= bitmap->size() ||
							((*bitmap)[r >> 6] &
							 (std::uint64_t(1) << (r & 63u))) == 0)
						continue;
				} else if (!std::binary_search(
						candidates->begin(), candidates->end(), r)) {
					continue;
				}
				if (membershipCandidateSeen[r] == membershipCandidateGeneration) continue;
				if (!rootContextMatchesCached(r)) continue;
				membershipCandidateSeen[r] = membershipCandidateGeneration;
				membershipCandidateScratch.push_back(r);
			}
			return;
		}
		// Memberships do not change during candidate preparation. Reuse a
		// type-local snapshot for all small loss lists in this update.
		if (membershipActiveSnapshotGeneration != membershipCandidateGeneration) {
			for (vector<int>::const_iterator ait = active.begin(); ait != active.end(); ++ait)
				if (*ait >= 0 && static_cast<size_t>(*ait) < membershipActiveSnapshot.size())
					membershipActiveSnapshot[*ait] = membershipCandidateGeneration;
			membershipActiveSnapshotGeneration = membershipCandidateGeneration;
		}
	}
	if (memprofEnabled())
		NFcore::memprofCandidateProbe(name,
				static_cast<long long>(candidates->size()), 0,
				requireCurrentRootContext ? static_cast<long long>(candidates->size()) : 0);
	for (vector<unsigned int>::const_iterator it = candidates->begin();
			it != candidates->end(); ++it) {
		unsigned int r = *it;
		if (membershipCandidateSeen[r] == membershipCandidateGeneration) continue;
		if (lossOnly && membershipActiveSnapshot[r] != membershipCandidateGeneration) continue;
		if (!rootContextMatchesCached(r)) continue;
		membershipCandidateSeen[r] = membershipCandidateGeneration;
		membershipCandidateScratch.push_back(r);
	}
}

void MoleculeType::appendMembershipBondFreeGainCandidates(
		const MembershipComponentKey &trigger, Molecule *m)
{
	auto fallback = membershipBondFreeGainFallbackCandidates.find(trigger);
	appendMembershipCandidateVector(
			fallback == membershipBondFreeGainFallbackCandidates.end()
				? 0 : &fallback->second, m, false, true);
	auto anchors = membershipBondFreeGainAnchorComponents.find(trigger);
	if (anchors == membershipBondFreeGainAnchorComponents.end() || m == 0)
		return;
	for (vector<int>::const_iterator ait = anchors->second.begin();
			ait != anchors->second.end(); ++ait) {
		int anchorComponent = *ait;
		if (anchorComponent < 0 ||
				anchorComponent >= m->getMoleculeType()->getNumOfComponents() ||
				!m->isBindingSiteBonded(anchorComponent))
			continue;
		Molecule *partner = m->getBondedMolecule(anchorComponent);
		if (partner == 0) continue;
		MembershipBondContextKey key(trigger.type, trigger.component,
				anchorComponent, partner->getMoleculeType(),
				m->getBondedMoleculeBindingSiteIndex(anchorComponent));
		auto composite = membershipBondFreeGainCompositeCandidates.find(key);
		appendMembershipCandidateVector(
				composite == membershipBondFreeGainCompositeCandidates.end()
					? 0 : &composite->second, m, false, true);
	}
}

void MoleculeType::appendMembershipBondBoundGainCandidates(
		const MembershipComponentKey &trigger, Molecule *m)
{
	/* Rules without a usable compact root topology anchor retain the existing
	 * root-context-filtered path. */
	auto fallback = membershipBondBoundGainFallbackCandidates.find(trigger);
	appendMembershipCandidateVector(
			fallback == membershipBondBoundGainFallbackCandidates.end()
				? 0 : &fallback->second, m, false, true);

	auto anchors = membershipBondBoundGainAnchorComponents.find(trigger);
	if (anchors == membershipBondBoundGainAnchorComponents.end() || m == 0)
		return;
	for (vector<int>::const_iterator ait = anchors->second.begin();
			ait != anchors->second.end(); ++ait) {
		int anchorComponent = *ait;
		if (anchorComponent < 0 ||
				anchorComponent >= m->getMoleculeType()->getNumOfComponents() ||
				!m->isBindingSiteBonded(anchorComponent))
			continue;
		Molecule *partner = m->getBondedMolecule(anchorComponent);
		if (partner == 0) continue;
		int partnerComponent =
			m->getBondedMoleculeBindingSiteIndex(anchorComponent);
		MembershipBondContextKey key(trigger.type, trigger.component,
				anchorComponent, partner->getMoleculeType(), partnerComponent);
		auto composite = membershipBondBoundGainCompositeCandidates.find(key);
		appendMembershipCandidateVector(
				composite == membershipBondBoundGainCompositeCandidates.end()
					? 0 : &composite->second, m, false, true);
	}
}

void MoleculeType::appendMembershipTopologyGainCandidates(
		const MembershipTopologyKey &trigger, Molecule *m)
{
	auto fallback = membershipTopologyGainFallbackCandidates.find(trigger);
	appendMembershipCandidateVector(
			fallback == membershipTopologyGainFallbackCandidates.end()
				? 0 : &fallback->second, m, false, true);

	auto anchors = membershipTopologyGainAnchorComponents.find(trigger);
	if (anchors == membershipTopologyGainAnchorComponents.end() || m == 0)
		return;
	for (vector<int>::const_iterator ait = anchors->second.begin();
			ait != anchors->second.end(); ++ait) {
		int anchorComponent = *ait;
		if (anchorComponent < 0 ||
				anchorComponent >= m->getMoleculeType()->getNumOfComponents() ||
				!m->isBindingSiteBonded(anchorComponent))
			continue;
		Molecule *partner = m->getBondedMolecule(anchorComponent);
		if (partner == 0) continue;
		int partnerComponent =
			m->getBondedMoleculeBindingSiteIndex(anchorComponent);
		MembershipTopologyContextKey key(
				trigger.type, trigger.component, trigger.partnerType,
				trigger.partnerComponent, anchorComponent,
				partner->getMoleculeType(), partnerComponent);
		auto composite = membershipTopologyGainCompositeCandidates.find(key);
		appendMembershipCandidateVector(
				composite == membershipTopologyGainCompositeCandidates.end()
					? 0 : &composite->second, m, false, true);
	}
}

void MoleculeType::prepareMembershipEventPlan(unsigned long long eventGeneration)
{
	if (system == 0) return;
	/* The hot membership path refreshes several molecules for the same event.
	 * Check the generation in the caller so this comparatively large function is
	 * entered only when the root-independent plan actually has to be rebuilt. */
	membershipEventPlanGeneration = eventGeneration;
	const vector<MembershipEventMutation> &eventMutations =
			system->getMembershipEventMutations();
	/* Multiply-add hash over the fields the plan depends on; collisions are
	 * resolved by the exact comparison below. */
	std::uint64_t key = 0x243f6a8885a308d3ULL;
	auto mix = [&key](std::uint64_t value) {
		key = (key ^ value) * 0x9e3779b97f4a7c15ULL;
		key ^= key >> 29;
	};
	for (vector<MembershipEventMutation>::const_iterator mit = eventMutations.begin();
			mit != eventMutations.end(); ++mit) {
		mix(static_cast<std::uint64_t>(mit->kind));
		mix(reinterpret_cast<std::uintptr_t>(mit->type1));
		mix(static_cast<std::uint64_t>(static_cast<std::int64_t>(mit->component1)));
		mix(reinterpret_cast<std::uintptr_t>(mit->type2));
		mix(static_cast<std::uint64_t>(static_cast<std::int64_t>(mit->component2)));
		mix(static_cast<std::uint64_t>(static_cast<std::int64_t>(mit->oldState)));
		mix(static_cast<std::uint64_t>(static_cast<std::int64_t>(mit->newState)));
	}
	auto sameMutations = [&eventMutations](const vector<MembershipEventMutation> &cached) {
		if (cached.size() != eventMutations.size()) return false;
		for (std::size_t i = 0; i < cached.size(); ++i) {
			const MembershipEventMutation &a = cached[i];
			const MembershipEventMutation &b = eventMutations[i];
			if (a.kind != b.kind || a.type1 != b.type1 || a.component1 != b.component1 ||
					a.type2 != b.type2 || a.component2 != b.component2 ||
					a.oldState != b.oldState || a.newState != b.newState)
				return false;
		}
		return true;
	};
	auto bucket = membershipEventPlanCache.find(key);
	if (bucket != membershipEventPlanCache.end()) {
		for (std::size_t i = 0; i < bucket->second.size(); ++i) {
			const MembershipEventPlanCacheEntry &entry = *bucket->second[i];
			if (sameMutations(entry.mutations)) {
				activeMembershipEventPlan = &entry.plan;
				activeMembershipLossUnion = &entry.lossUnion;
				activeMembershipLossTotal = entry.lossTotal;
				return;
			}
		}
	}
	buildMembershipEventPlan();
	activeMembershipEventPlan = &membershipEventCandidatePlan;
	activeMembershipLossUnion = &membershipEventLossUnion;
	activeMembershipLossTotal = membershipEventLossTotal;
	/* Bound the cache so models with unbounded mutation diversity cannot grow
	 * it without limit; uncached events simply rebuild their plan. */
	if (membershipEventPlanCacheSize < 65536) {
		std::unique_ptr<MembershipEventPlanCacheEntry> entry(
				new MembershipEventPlanCacheEntry());
		entry->mutations = eventMutations;
		entry->plan = membershipEventCandidatePlan;
		entry->lossUnion = membershipEventLossUnion;
		entry->lossTotal = membershipEventLossTotal;
		activeMembershipEventPlan = &entry->plan;
		activeMembershipLossUnion = &entry->lossUnion;
		activeMembershipLossTotal = entry->lossTotal;
		membershipEventPlanCache[key].push_back(std::move(entry));
		++membershipEventPlanCacheSize;
	}
}

void MoleculeType::buildMembershipEventPlan()
{
	membershipEventCandidatePlan.clear();

	auto addDirect = [&](const vector<unsigned int> *candidates,
			bool lossOnly, bool requireRoot) {
		if (candidates == 0 || candidates->empty()) return;
		MembershipEventCandidateAction action;
		action.kind = MembershipEventCandidateAction::DIRECT;
		action.candidates = candidates;
		if (requireRoot) {
			auto vit = membershipCandidateViews.find(candidates);
			if (vit != membershipCandidateViews.end()) action.candidateView = &vit->second;
		}
		action.lossOnly = lossOnly;
		action.requireRoot = requireRoot;
		if (lossOnly) {
			auto bitmapIt = membershipLossCandidateBitmaps.find(candidates);
			action.lossBitmap = bitmapIt == membershipLossCandidateBitmaps.end()
					? 0 : &bitmapIt->second;
			action.lossBitmapResolved = true;
		}
		membershipEventCandidatePlan.push_back(action);
	};
	auto addGainLookup = [&](MembershipEventCandidateAction::Kind kind,
			const MembershipGainLookup *lookup) {
		if (lookup == 0 || ((lookup->fallback == 0 || lookup->fallback->empty()) &&
				lookup->anchors.empty())) return;
		MembershipEventCandidateAction action;
		action.kind = kind;
		action.gainLookup = lookup;
		membershipEventCandidatePlan.push_back(action);
	};

	const vector<MembershipEventMutation> &mutations =
			system->getMembershipEventMutations();
	for (vector<MembershipEventMutation>::const_iterator mit = mutations.begin();
			mit != mutations.end(); ++mit) {
		const MembershipEventMutation &mutation = *mit;
		if (mutation.kind == MembershipEventMutation::STATE_CHANGE) {
			MembershipStateKey oldKey(mutation.type1, mutation.component1,
					mutation.oldState);
			MembershipStateKey newKey(mutation.type1, mutation.component1,
					mutation.newState);
			auto reqNew = membershipStateRequiredCandidates.find(newKey);
			addDirect(reqNew == membershipStateRequiredCandidates.end()
					? 0 : &reqNew->second, false, true);
			auto excOld = membershipStateExcludedCandidates.find(oldKey);
			addDirect(excOld == membershipStateExcludedCandidates.end()
					? 0 : &excOld->second, false, true);
			auto reqOld = membershipStateRequiredCandidates.find(oldKey);
			addDirect(reqOld == membershipStateRequiredCandidates.end()
					? 0 : &reqOld->second, true, false);
			auto excNew = membershipStateExcludedCandidates.find(newKey);
			addDirect(excNew == membershipStateExcludedCandidates.end()
					? 0 : &excNew->second, true, false);
			continue;
		}

		MembershipComponentKey c1(mutation.type1, mutation.component1);
		MembershipComponentKey c2(mutation.type2, mutation.component2);
		MembershipTopologyKey t12(mutation.type1, mutation.component1,
				mutation.type2, mutation.component2);
		MembershipTopologyKey t21(mutation.type2, mutation.component2,
				mutation.type1, mutation.component1);

		if (mutation.kind == MembershipEventMutation::BOND_ADD) {
			auto topo12Lookup = membershipTopologyGainLookups.find(t12);
			addGainLookup(MembershipEventCandidateAction::TOPOLOGY_GAIN,
				topo12Lookup == membershipTopologyGainLookups.end() ? 0 : &topo12Lookup->second);
			auto topo21Lookup = membershipTopologyGainLookups.find(t21);
			addGainLookup(MembershipEventCandidateAction::TOPOLOGY_GAIN,
				topo21Lookup == membershipTopologyGainLookups.end() ? 0 : &topo21Lookup->second);

			auto bound1Lookup = membershipBondBoundGainLookups.find(c1);
			addGainLookup(MembershipEventCandidateAction::BOND_BOUND_GAIN,
				bound1Lookup == membershipBondBoundGainLookups.end() ? 0 : &bound1Lookup->second);
			auto bound2Lookup = membershipBondBoundGainLookups.find(c2);
			addGainLookup(MembershipEventCandidateAction::BOND_BOUND_GAIN,
				bound2Lookup == membershipBondBoundGainLookups.end() ? 0 : &bound2Lookup->second);

			auto free1 = membershipBondFreeCandidates.find(c1);
			addDirect(free1 == membershipBondFreeCandidates.end() ? 0 : &free1->second,
					true, false);
			auto free2 = membershipBondFreeCandidates.find(c2);
			addDirect(free2 == membershipBondFreeCandidates.end() ? 0 : &free2->second,
					true, false);
		} else if (mutation.kind == MembershipEventMutation::BOND_DEL) {
			auto free1Lookup = membershipBondFreeGainLookups.find(c1);
			addGainLookup(MembershipEventCandidateAction::BOND_FREE_GAIN,
				free1Lookup == membershipBondFreeGainLookups.end() ? 0 : &free1Lookup->second);
			auto free2Lookup = membershipBondFreeGainLookups.find(c2);
			addGainLookup(MembershipEventCandidateAction::BOND_FREE_GAIN,
				free2Lookup == membershipBondFreeGainLookups.end() ? 0 : &free2Lookup->second);

			auto topo12 = membershipTopologyCandidates.find(t12);
			addDirect(topo12 == membershipTopologyCandidates.end() ? 0 : &topo12->second,
					true, false);
			auto topo21 = membershipTopologyCandidates.find(t21);
			addDirect(topo21 == membershipTopologyCandidates.end() ? 0 : &topo21->second,
					true, false);
			auto bound1 = membershipBondBoundCandidates.find(c1);
			addDirect(bound1 == membershipBondBoundCandidates.end() ? 0 : &bound1->second,
					true, false);
			auto bound2 = membershipBondBoundCandidates.find(c2);
			addDirect(bound2 == membershipBondBoundCandidates.end() ? 0 : &bound2->second,
					true, false);
		}
	}
	membershipEventLossTotal = 0;
	membershipEventLossUnion.assign((reactions.size() + 63) / 64, 0);
	for (vector<MembershipEventCandidateAction>::const_iterator ait =
			membershipEventCandidatePlan.begin();
			ait != membershipEventCandidatePlan.end(); ++ait) {
		if (ait->kind != MembershipEventCandidateAction::DIRECT || !ait->lossOnly ||
				ait->candidates == 0)
			continue;
		membershipEventLossTotal += ait->candidates->size();
		for (vector<unsigned int>::const_iterator cit = ait->candidates->begin();
				cit != ait->candidates->end(); ++cit)
			if ((*cit >> 6) < membershipEventLossUnion.size())
				membershipEventLossUnion[*cit >> 6] |= std::uint64_t(1) << (*cit & 63u);
	}
}

void MoleculeType::applyMembershipEventPlan(Molecule *m)
{
	const vector<MembershipEventCandidateAction> &plan =
			activeMembershipEventPlan != 0 ? *activeMembershipEventPlan
				: membershipEventCandidatePlan;
	/* Loss candidates are (union of loss-only lists) intersected with the
	 * molecule's active memberships.  When the lists are long relative to the
	 * active set, intersect once against the union instead of once per list. */
	bool lossListsHandled = false;
	if (m != 0 && activeMembershipLossUnion != 0 && activeMembershipLossTotal > 0) {
		const vector<int> &active = m->getActiveReactionMembershipIndices();
		if (activeMembershipLossTotal >
				active.size() * generalMembershipFilterLossActiveMultiplier()) {
			const vector<std::uint64_t> &lossUnion = *activeMembershipLossUnion;
			for (vector<int>::const_iterator ait = active.begin();
					ait != active.end(); ++ait) {
				if (*ait < 0) continue;
				unsigned int r = static_cast<unsigned int>(*ait);
				if ((r >> 6) >= lossUnion.size() ||
						(lossUnion[r >> 6] & (std::uint64_t(1) << (r & 63u))) == 0)
					continue;
				if (membershipCandidateSeen[r] == membershipCandidateGeneration) continue;
				membershipCandidateSeen[r] = membershipCandidateGeneration;
				membershipCandidateScratch.push_back(r);
			}
			lossListsHandled = true;
		}
	}
	for (vector<MembershipEventCandidateAction>::const_iterator ait =
			plan.begin(); ait != plan.end(); ++ait) {
		const MembershipEventCandidateAction &action = *ait;
		if (action.kind == MembershipEventCandidateAction::DIRECT) {
			if (lossListsHandled && action.lossOnly)
				continue;
			appendMembershipCandidateVector(action.candidates, m,
				action.lossOnly, action.requireRoot, action.candidateView,
				action.lossBitmap, action.lossBitmapResolved);
			continue;
		}

		const MembershipGainLookup *lookup = action.gainLookup;
		if (lookup == 0) continue;
		if (lookup->fallback != 0 && !lookup->fallback->empty() &&
				!(lookup->fallbackHasCommonTopology && m != 0 &&
				!membershipRootPredicateMatches(m, lookup->fallbackCommonTopology)))
			appendMembershipCandidateVector(lookup->fallback, m, false, true, lookup->fallbackView);
		if (m == 0 || lookup->anchors.empty()) continue;

		const vector<int> &bonded = m->getBondedComponentIndices();
		if (bonded.empty()) continue;

		auto applyAnchor = [&](const MembershipAnchorCandidateLookup &anchor) {
			int c = anchor.anchorComponent;
			if (c < 0 || c >= m->getMoleculeType()->getNumOfComponents() ||
					!m->isBindingSiteBonded(c)) return;
			Molecule *partner = m->getBondedMolecule(c);
			if (partner == 0) return;
			int pc = m->getBondedMoleculeBindingSiteIndex(c);
			MoleculeType *pt = partner->getMoleculeType();
			vector<MembershipPartnerCandidateEntry>::const_iterator first = anchor.entries.begin();
			const bool ordered = anchor.entries.size() > 8u;
			if (ordered)
				first = std::lower_bound(first, anchor.entries.end(), pc,
					[](const MembershipPartnerCandidateEntry &entry, int component) {
						return entry.partnerComponent < component;
					});
			for (vector<MembershipPartnerCandidateEntry>::const_iterator eit = first;
					eit != anchor.entries.end(); ++eit) {
				if (ordered && eit->partnerComponent != pc) break;
				if (eit->partnerType == pt && eit->partnerComponent == pc) {
					appendMembershipCandidateVector(eit->candidates, m, false, true, eit->candidateView);
					return;
				}
			}
		};

		/* Both lists are sorted.  Intersect from the molecule's sparse occupied
		 * component list when the static anchor set is broader. */
		if (lookup->anchors.size() > bonded.size() * 4u) {
			for (vector<int>::const_iterator bit = bonded.begin(); bit != bonded.end(); ++bit) {
				auto pos = std::lower_bound(lookup->anchors.begin(), lookup->anchors.end(), *bit,
					[](const MembershipAnchorCandidateLookup &a, int c){ return a.anchorComponent < c; });
				if (pos != lookup->anchors.end() && pos->anchorComponent == *bit) applyAnchor(*pos);
			}
		} else if (lookup->anchors.size() <= 4u) {
			for (vector<MembershipAnchorCandidateLookup>::const_iterator a = lookup->anchors.begin();
					a != lookup->anchors.end(); ++a) applyAnchor(*a);
		} else {
			/* Comparable sizes: one merge pass over the two ascending lists
			 * visits exactly the bonded anchors, in the same order as testing
			 * every anchor, without touching the bond array for unbonded ones. */
			vector<MembershipAnchorCandidateLookup>::const_iterator a = lookup->anchors.begin();
			const vector<MembershipAnchorCandidateLookup>::const_iterator aEnd = lookup->anchors.end();
			vector<int>::const_iterator b = bonded.begin();
			const vector<int>::const_iterator bEnd = bonded.end();
			while (a != aEnd && b != bEnd) {
				if (a->anchorComponent < *b) ++a;
				else if (*b < a->anchorComponent) ++b;
				else { applyAnchor(*a); ++a; ++b; }
			}
		}
	}
}

void MoleculeType::prepareMembershipCandidates(Molecule *m)
{
	if (!membershipDependencyIndexBuilt)
		buildMembershipDependencyIndex();
	if (++membershipCandidateGeneration == 0) {
		std::fill(membershipCandidateSeen.begin(), membershipCandidateSeen.end(), 0);
		std::fill(membershipActiveSnapshot.begin(), membershipActiveSnapshot.end(), 0);
		membershipActiveSnapshotGeneration = 0;
		std::fill(membershipRootContextChecked.begin(), membershipRootContextChecked.end(), 0);
		membershipCandidateGeneration = 1;
	}
	membershipCandidateScratch.clear();

	/* New molecules start with no mappings, so only gains are possible.  A full
	 * scan is nevertheless unnecessary when the runtime reactant role has a
	 * provably local root pattern: failing any root-local state/bond/topology
	 * predicate is a necessary-condition failure regardless of the rest of the
	 * connected pattern.  Unsafe/symmetric/connectedTo/compartment roles remain
	 * unconditional. Population types keep the legacy path until their count
	 * semantics are explicitly indexed. */
	if (m == 0 || population_type || system == 0) {
		for (unsigned int r = 0; r < reactions.size(); ++r) {
			membershipCandidateSeen[r] = membershipCandidateGeneration;
			membershipCandidateScratch.push_back(r);
		}
		return;
	}
	if (system->isNewMembershipMolecule(m)) {
		for (unsigned int r = 0; r < reactions.size(); ++r) {
			if (r < membershipRootContextSafe.size() &&
					membershipRootContextSafe[r] &&
					!membershipRootContextMatches(m, r))
				continue;
			membershipCandidateSeen[r] = membershipCandidateGeneration;
			membershipCandidateScratch.push_back(r);
		}
		return;
	}

	appendMembershipCandidateVector(&unconditionalMembershipCandidates, m, false);
	const unsigned long long eventGeneration =
		system->getMembershipMutationGeneration();
	if (membershipEventPlanGeneration != eventGeneration)
		prepareMembershipEventPlan(eventGeneration);
	applyMembershipEventPlan(m);
}

void MoleculeType::prepareForSimulation()
{
	/* The dependency index is only consumed by the opt-in membership filter/diff
	 * paths.  Historically it was built for every MoleculeType unconditionally,
	 * including default NFsim runs and types below the filter's own activation
	 * threshold.  Avoid that pure startup cost while preserving lazy construction
	 * in prepareMembershipCandidates() for any future caller that actually needs it. */
	const bool membershipDiffConfigured = generalMembershipDiffEnabled();
	const bool membershipFilterConfigured = generalMembershipFilterEnabled() &&
			(generalMembershipFilterForceEnabled() ||
			 reactions.size() >= generalMembershipFilterMinRegistrations());
	if (membershipDiffConfigured || membershipFilterConfigured)
		buildMembershipDependencyIndex();
	//cout<<"Preparing: "<<name<<endl;
	//Check each reaction and add this molecule as a reactant if we have to
	int r=0;
	for(rxnIter = reactions.begin(), r=0; rxnIter != reactions.end(); rxnIter++, r++ )
	{
		system->registerRxnIndex((*rxnIter)->getRxnId(), reactionPositions.at(r),r);
  	}


	// Our iterators that we will use to loop through every molecule.
	Molecule *mol;
	const bool sparseInitialMembership = membershipFilterConfigured &&
			!membershipDiffConfigured && !population_type;
	/* Many seed states contain thousands of identical small machinery molecules
	 * (e.g. free ribosomes). Their safe root-local candidate set depends only on
	 * local state and immediate bond topology, so cache it by an exact local
	 * signature instead of rescanning every registered reaction per copy. */
	const bool cacheInitialCandidates = sparseInitialMembership &&
			numOfComponents <= 16 && mList->size() >= 8;
	std::map<std::string, std::vector<unsigned int> > initialCandidateCache;
	auto initialMembershipSignature = [&](Molecule *candidate) {
		std::string key;
		key.reserve(static_cast<std::size_t>(numOfComponents) * 3 * sizeof(int));
		for (int c = 0; c < numOfComponents; ++c) {
			int values[3];
			values[0] = candidate->getComponentState(c);
			values[1] = -1;
			values[2] = -1;
			if (candidate->isBindingSiteBonded(c)) {
				Molecule *partner = candidate->getBondedMolecule(c);
				if (partner != 0) {
					values[1] = partner->getMoleculeType()->getTypeID();
					values[2] = candidate->getBondedMoleculeBindingSiteIndex(c);
				}
			}
			key.append(reinterpret_cast<const char *>(values), sizeof(values));
		}
		return key;
	};
  	for( int m=0; m<mList->size(); m++ )
  	{
  		//First prepare the molecule for simulation
  		mol = mList->at(m);
  		mol->prepareForSimulation();

  		//Check each observable and see if this molecule should be counted
  		this->addToObservables(mol);

		// Initial molecules have no mappings, so only gains are possible. A safe
		// root-local mismatch is therefore sufficient to skip the full template.
		if (cacheInitialCandidates) {
			std::string signature = initialMembershipSignature(mol);
			auto cached = initialCandidateCache.find(signature);
			if (cached == initialCandidateCache.end()) {
				std::vector<unsigned int> candidates;
				candidates.reserve(reactions.size());
				for (unsigned int ri = 0; ri < reactions.size(); ++ri) {
					if (ri < membershipRootContextSafe.size() &&
						membershipRootContextSafe[ri] &&
						!membershipRootContextMatches(mol, ri))
						continue;
					candidates.push_back(ri);
				}
				cached = initialCandidateCache.insert(
						std::make_pair(signature, candidates)).first;
			}
			const std::vector<unsigned int> &candidates = cached->second;
			for (std::vector<unsigned int>::const_iterator ci = candidates.begin();
					ci != candidates.end(); ++ci) {
				unsigned int ri = *ci;
				ReactionClass *initialRxn = reactions[ri];
				if (initialRxn->usesIncrementalMembership())
					initialRxn->tryToAddWithIndex(mol, reactionPositions[ri], ri);
				else
					initialRxn->tryToAdd(mol, reactionPositions[ri]);
			}
		} else {
			for(rxnIter = reactions.begin(), r=0; rxnIter != reactions.end(); rxnIter++, r++ )
			{
				if (sparseInitialMembership && r < (int)membershipRootContextSafe.size() &&
						membershipRootContextSafe[r] &&
						!membershipRootContextMatches(mol, r))
					continue;
				if ((*rxnIter)->usesIncrementalMembership())
					(*rxnIter)->tryToAddWithIndex(
							mol, reactionPositions.at(r), r);
				else
					(*rxnIter)->tryToAdd(mol, reactionPositions.at(r));
			}
		}
	}
}


/* ---- membership-walk instrumentation (NFSIM_MEMPROF=1) ----------------
 * The scaling of per-event cost with rule count implicates this walk, but
 * that inference is not a measurement.  These counters partition it: total
 * time in the generic loop, how many reactions are visited, how many survive
 * to a tryToAdd, how much time tryToAdd itself costs, and how often it
 * actually changes membership.  Compiled in unconditionally but gated at
 * runtime; the guard is a single load of a cached flag. */
namespace {
	bool memprofEnabled() {
		static int on = -1;
		if (on < 0) on = (getenv("NFSIM_MEMPROF") != 0) ? 1 : 0;
		return on == 1;
	}
	static inline double memprofNow() {
		/* std::chrono::steady_clock, matching profile.hh: clock_gettime and
		 * CLOCK_MONOTONIC do not exist on MSVC. */
		return std::chrono::duration<double>(
			std::chrono::steady_clock::now().time_since_epoch()).count();
	}
}
namespace NFcore {
	bool shadowOn();
	extern long long shadowEvent;
	void memprofAdd(const std::string &name, double, double, double,
			long long, long long, long long, long long);
	double memprofWalkTime = 0.0;
	double memprofCandidateTime = 0.0;
	double memprofTryTime = 0.0;
	long long memprofWalkCalls = 0;
	long long memprofCandidateCalls = 0;
	long long memprofCandidates = 0;
	long long memprofVisited = 0;
	long long memprofTryCalls = 0;
	long long memprofChanged = 0;
	struct MemprofType { double walk; double tryT; double candidateT; long long candidates;
			long long candidateVectorProbes; long long candidateActiveProbes;
			long long candidateRootChecks; long long visits; long long tries;
			long long changed; long long calls; };
	std::map<std::string, MemprofType> memprofByType;
	void memprofAdd(const std::string &name, double walk, double tryT, double candidateT,
			long long candidates, long long visits, long long tries, long long changed) {
		MemprofType &e = memprofByType[name];
		e.walk += walk; e.tryT += tryT; e.candidateT += candidateT;
		e.candidates += candidates; e.visits += visits;
		e.tries += tries; e.changed += changed; e.calls += 1;
	}
	void memprofCandidateProbe(const std::string &name, long long vectorProbes,
			long long activeProbes, long long rootChecks) {
		MemprofType &e = memprofByType[name];
		e.candidateVectorProbes += vectorProbes;
		e.candidateActiveProbes += activeProbes;
		e.candidateRootChecks += rootChecks;
	}
	void memprofReport() {
		if (getenv("NFSIM_MEMPROF") == 0) return;
		for (std::map<std::string, MemprofType>::const_iterator it =
				memprofByType.begin(); it != memprofByType.end(); ++it) {
			cout << "#MEMPROF_TYPE " << it->first
			     << " candidate_s=" << it->second.candidateT
			     << " candidates=" << it->second.candidates
			     << " cand_vec_probes=" << it->second.candidateVectorProbes
			     << " cand_active_probes=" << it->second.candidateActiveProbes
			     << " cand_root_checks=" << it->second.candidateRootChecks
			     << " walk_s=" << it->second.walk
			     << " try_s=" << it->second.tryT
			     << " calls=" << it->second.calls
			     << " visits=" << it->second.visits
			     << " tries=" << it->second.tries
			     << " changed=" << it->second.changed << endl;
		}
		cout << "#MEMPROF candidate_s=" << memprofCandidateTime
		     << " candidate_calls=" << memprofCandidateCalls
		     << " candidates=" << memprofCandidates
		     << " walk_s=" << memprofWalkTime
		     << " try_s=" << memprofTryTime
		     << " walk_calls=" << memprofWalkCalls
		     << " visited=" << memprofVisited
		     << " try_calls=" << memprofTryCalls
		     << " changed=" << memprofChanged << endl;
	}
}


namespace {
	/* MappingIdSet has no operator!=; compare contents element-wise.  This is
	 * the role-local exactness the v2 oracle depends on: the local reaction
	 * list is keyed (ReactionClass, reactantPosition), so comparing the set
	 * for one role detects a change in that role even when reactant list 0
	 * is untouched -- the collision-rule case that reactantLists[0] missed. */
	bool shadowSetsEqual(const NFcore::MappingIdSet &a,
			const NFcore::MappingIdSet &b) {
		if (a.size() != b.size()) return false;
		NFcore::MappingIdSet::const_iterator ia = a.begin();
		NFcore::MappingIdSet::const_iterator ib = b.begin();
		for (; ia != a.end(); ++ia, ++ib)
			if (*ia != *ib) return false;
		return true;
	}
}

const vector<unsigned int> &MoleculeType::getCompactPoolScaleCandidates()
{
	const std::size_t key = reactions.size() + 1;
	if (compactPoolScaleCandidatesKey != key) {
		compactPoolScaleCandidates.clear();
		for (unsigned int r = 0; r < reactions.size(); ++r) {
			int partnerComponent = -1;
			if (reactions[r]->supportsCompactPartnerPoolScale() &&
					reactions[r]->getCompactPartnerPoolInfo(
						reactionPositions.at(r), partnerComponent))
				compactPoolScaleCandidates.push_back(r);
		}
		compactPoolScaleCandidatesKey = key;
	}
	return compactPoolScaleCandidates;
}

void MoleculeType::updateRxnMembership(Molecule * m,
		ReactionClass *firedReaction, bool directProduct)
{
	const vector<unsigned char> *cachedDecisions = 0;
	const DirectMembershipDecisionCacheEntry *cachedDecisionEntry = 0;
	IncrementalMembershipChange membershipChange;
	bool hasMembershipChange = directProduct && firedReaction != 0 &&
		firedReaction->usesIncrementalMembership() &&
		firedReaction->getIncrementalMembershipChange(membershipChange);
	bool refineMembershipChange = hasMembershipChange &&
		m->getMoleculeType() == membershipChange.moleculeType1;
	if (refineMembershipChange && membershipChange.componentIndex1 >= 0 &&
			membershipChange.componentIndex1 < 64) {
		/* If the weighted molecule is full immediately before or after the
		 * event, every accepted context dependency on the changed site crosses
		 * its predicate.  The endpoint cache is already exact in that case. */
		std::uint64_t changedBit = std::uint64_t(1) <<
				membershipChange.componentIndex1;
		int componentCount = m->getMoleculeType()->getNumOfComponents();
		if (componentCount <= 64) {
			std::uint64_t fullMask = componentCount == 64
					? ~std::uint64_t(0)
					: ((std::uint64_t(1) << componentCount) - 1);
			std::uint64_t newMask = m->getBoundComponentMask();
			std::uint64_t oldMask = membershipChange.isBoundAfter1
					? (newMask & ~changedBit) : (newMask | changedBit);
			if (newMask == fullMask || oldMask == fullMask)
				refineMembershipChange = false;
		}
	}
	bool useCompactMembershipIndex = hasMembershipChange &&
		m->getMoleculeType() == membershipChange.moleculeType1 &&
		membershipChange.componentIndex1 >= 0 &&
		membershipChange.componentIndex1 < 64 &&
		static_cast<unsigned int>(membershipChange.componentIndex1) <
			compactEnergyCenterCandidateBits.size() &&
		static_cast<unsigned int>(membershipChange.componentIndex1) <
			compactEnergyContextCandidateBits.size() &&
		hasCompactEnergyMembershipIndex;
	auto refreshReactionMembership = [&](ReactionClass *rxn,
			unsigned int reactionIndex) {
		bool defer = this->system->isDeferringMembershipPropensityUpdates() &&
			rxn->supportsDeferredMembershipUpdate();
		if (defer) {
			double oldA = rxn->get_a();
			bool changed = rxn->tryToAddAndReportChangeWithIndex(
					m, reactionPositions.at(reactionIndex), reactionIndex);
			if (changed)
				this->system->deferMembershipPropensityUpdate(rxn, oldA);
			return;
		}
		double oldA = rxn->get_a();
		if (rxn->usesIncrementalMembership())
			rxn->tryToAddWithIndex(
					m, reactionPositions.at(reactionIndex), reactionIndex);
		else
			rxn->tryToAdd(m, reactionPositions.at(reactionIndex));
		double newA = rxn->update_a();
		this->system->update_A_tot(rxn, oldA, newA);
	};
	bool useCompactPartnerPoolIndex = hasMembershipChange && directProduct &&
		membershipChange.moleculeType1 != membershipChange.moleculeType2 &&
		m->getMoleculeType() == membershipChange.moleculeType2 &&
		membershipChange.componentIndex2 >= 0 &&
		static_cast<unsigned int>(membershipChange.componentIndex2) <
			compactPartnerCandidateBits.size() &&
		static_cast<unsigned int>(membershipChange.componentIndex2) <
			compactPartnerReactionIndices.size() &&
		!compactPartnerReactionIndices[membershipChange.componentIndex2].empty();
	bool compactMembershipDecisionsComplete = useCompactMembershipIndex &&
		membershipChange.moleculeType1 != membershipChange.moleculeType2 &&
		nonCompactMembershipCandidateBits.empty();
	if (!compactMembershipDecisionsComplete && directProduct &&
			firedReaction != 0 && firedReaction->usesIncrementalMembership()) {
		std::unordered_map<ReactionClass *, bool>::iterator safe =
			directMembershipDecisionCacheSafe.find(firedReaction);
		if (safe == directMembershipDecisionCacheSafe.end()) {
			bool typeInvariant = true;
			for (unsigned int r = 0; r < reactions.size(); ++r) {
				if (!reactions[r]->membershipDecisionIsTypeInvariant()) {
					typeInvariant = false;
					break;
				}
			}
			safe = directMembershipDecisionCacheSafe.emplace(
				firedReaction, typeInvariant).first;
		}
		if (safe->second) {
			std::unordered_map<ReactionClass *,
					DirectMembershipDecisionCacheEntry>::iterator cached =
				directMembershipDecisionCache.find(firedReaction);
			if (cached == directMembershipDecisionCache.end()) {
				DirectMembershipDecisionCacheEntry entry;
				entry.decisions.reserve(reactions.size());
				for (unsigned int r = 0; r < reactions.size(); ++r)
					entry.decisions.push_back(
						reactions[r]->shouldUpdateMembership(
								m, firedReaction, true));
				std::size_t affectedReactionCount = 0;
				for (unsigned int r = 0; r < entry.decisions.size(); ++r) {
					if (entry.decisions[r])
						++affectedReactionCount;
				}
				if (affectedReactionCount * 2 < entry.decisions.size()) {
					entry.reactionIndices.reserve(affectedReactionCount);
					for (unsigned int r = 0; r < entry.decisions.size(); ++r) {
						if (entry.decisions[r])
							entry.reactionIndices.push_back(r);
					}
					vector<unsigned char>().swap(entry.decisions);
					entry.useReactionIndices = true;
				}
				cached = directMembershipDecisionCache.emplace(
					firedReaction, entry).first;
			}
			cachedDecisionEntry = &cached->second;
			if (!cachedDecisionEntry->useReactionIndices)
				cachedDecisions = &cachedDecisionEntry->decisions;
		}
	}
	bool compactPartnerPoolChanged = false;
	bool compactPartnerPoolBatchScheduled = false;
	CompactPartnerPool *compactPartnerPool = 0;
	int oldCompactPartnerPoolSize = 0;
	const vector<std::uint64_t> *partnerCandidates = 0;
	if (useCompactPartnerPoolIndex) {
		int partnerComponent = membershipChange.componentIndex2;
		partnerCandidates = &compactPartnerCandidateBits[partnerComponent];
		const vector<unsigned int> &partnerReactions =
				compactPartnerReactionIndices[partnerComponent];
		unsigned int firstPartnerReaction = partnerReactions.front();
		compactPartnerPool = reactions[firstPartnerReaction]->
				getCompactPartnerPool();
		if (compactPartnerPool != 0)
			oldCompactPartnerPoolSize = compactPartnerPool->size();
		compactPartnerPoolChanged = reactions[firstPartnerReaction]->
				refreshCompactPartnerPool(
					m, reactionPositions[firstPartnerReaction]);
		if (compactPartnerPoolChanged && compactPartnerPool != 0 &&
				this->system->isDeferringMembershipPropensityUpdates() &&
				compactPartnerPool->supportsBatchUpdate()) {
			this->system->deferCompactPartnerPoolUpdate(
					compactPartnerPool, oldCompactPartnerPoolSize,
					compactPartnerPool->size());
			compactPartnerPoolBatchScheduled = true;
		}
	}
	bool allReactionsUseCompactPartnerPool =
			useCompactPartnerPoolIndex &&
			compactPartnerReactionIndices[membershipChange.componentIndex2].size() ==
				reactions.size();
	if (allReactionsUseCompactPartnerPool) {
		if (compactPartnerPoolChanged) {
			bool defer = this->system->isDeferringMembershipPropensityUpdates();
			if (defer && compactPartnerPoolBatchScheduled)
				return;
			const vector<unsigned int> &partnerReactions =
					compactPartnerReactionIndices[membershipChange.componentIndex2];
			for (vector<unsigned int>::const_iterator it =
					partnerReactions.begin(); it != partnerReactions.end(); ++it) {
				ReactionClass *rxn = reactions[*it];
				if (defer) {
					double oldA = rxn->get_a();
					this->system->deferMembershipPropensityUpdate(rxn, oldA);
				} else {
					double oldA = rxn->get_a();
					double newA = rxn->update_a();
					this->system->update_A_tot(rxn, oldA, newA);
				}
			}
		}
		return;
	}
	vector<CompactPartnerPool *> compactPools;
	vector<int> compactPoolOldSizes;
	vector<bool> compactPoolChanged;
	if (!useCompactPartnerPoolIndex) {
	const vector<unsigned int> &compactPoolScaleList =
			getCompactPoolScaleCandidates();
	for (vector<unsigned int>::const_iterator scaleIt =
			compactPoolScaleList.begin();
			scaleIt != compactPoolScaleList.end(); ++scaleIt) {
		unsigned int r = *scaleIt;
		ReactionClass *rxn = reactions.at(r);
		CompactPartnerPool *pool = rxn->getCompactPartnerPool();
		if (pool == 0 || !pool->supportsBatchUpdate())
			continue;
		bool allReactionsSupportScale = true;
		const vector<ReactionClass *> &registered =
				pool->getRegisteredReactions();
		for (vector<ReactionClass *>::const_iterator it = registered.begin();
				it != registered.end(); ++it) {
			if (*it == 0 || !(*it)->supportsCompactPartnerPoolScale()) {
				allReactionsSupportScale = false;
				break;
			}
		}
		if (!allReactionsSupportScale)
			continue;
		int poolIndex = -1;
		for (unsigned int p=0; p<compactPools.size(); p++) {
			if (compactPools.at(p) == pool) {
				poolIndex = static_cast<int>(p);
				break;
			}
		}
		if (poolIndex >= 0)
			continue;
		compactPools.push_back(pool);
		compactPoolOldSizes.push_back(pool->size());
		compactPoolChanged.push_back(
				rxn->refreshCompactPartnerPool(m,
					reactionPositions.at(r)));
	}
	for (unsigned int p=0; p<compactPools.size(); p++) {
		if (!compactPoolChanged.at(p))
			continue;
		if (this->system->isDeferringMembershipPropensityUpdates())
			this->system->deferCompactPartnerPoolUpdate(
					compactPools.at(p), compactPoolOldSizes.at(p),
					compactPools.at(p)->size());
		else
			this->system->updateCompactPartnerPoolBatch(
					compactPools.at(p), compactPoolOldSizes.at(p),
					compactPools.at(p)->size());
	}
	}

	if (cachedDecisionEntry != 0 &&
			cachedDecisionEntry->useReactionIndices &&
			!useCompactMembershipIndex) {
		for (vector<unsigned int>::const_iterator it =
				cachedDecisionEntry->reactionIndices.begin();
				it != cachedDecisionEntry->reactionIndices.end(); ++it) {
			unsigned int r = *it;
			ReactionClass *rxn = reactions.at(r);
			if (useCompactPartnerPoolIndex &&
					compactMembershipBitIsSet(*partnerCandidates, r)) {
				if (!compactPartnerPoolChanged)
					continue;
				bool defer = this->system->isDeferringMembershipPropensityUpdates();
				if (defer) {
					if (compactPartnerPoolBatchScheduled)
						continue;
					double oldA = rxn->get_a();
					this->system->deferMembershipPropensityUpdate(rxn, oldA);
				} else {
					double oldA = rxn->get_a();
					double newA = rxn->update_a();
					this->system->update_A_tot(rxn, oldA, newA);
				}
				continue;
			}
			if (refineMembershipChange &&
					!rxn->shouldUpdateMembershipForChange(
							m, membershipChange))
				continue;
			bool handledByCompactPool = false;
			int partnerComponent = -1;
			if (!compactPools.empty() &&
					rxn->supportsCompactPartnerPoolUpdate() &&
					rxn->getCompactPartnerPoolInfo(
						reactionPositions.at(r), partnerComponent)) {
				CompactPartnerPool *pool = rxn->getCompactPartnerPool();
				for (unsigned int p = 0; p < compactPools.size(); ++p) {
					if (compactPools.at(p) == pool) {
						handledByCompactPool = true;
						break;
					}
				}
			}
			if (handledByCompactPool)
				continue;
			refreshReactionMembership(rxn, r);
		}
		return;
	}

	if (useCompactMembershipIndex) {
		int changedComponent = membershipChange.componentIndex1;
		std::uint64_t changedBit = std::uint64_t(1) << changedComponent;
		std::uint64_t newMask = m->getBoundComponentMask();
		std::uint64_t oldMask = membershipChange.isBoundAfter1
				? (newMask & ~changedBit) : (newMask | changedBit);
		unsigned int minimumContextBits =
				compactEnergyContextMinimumRequiredBits[changedComponent];
		bool includeContext = minimumContextBits == 0 ||
			compactMembershipBitCount(newMask | oldMask) >=
				minimumContextBits;
		const vector<std::uint64_t> &centerCandidates =
				compactEnergyCenterCandidateBits[changedComponent];
		const vector<std::uint64_t> &contextCandidates =
				compactEnergyContextCandidateBits[changedComponent];
		const std::size_t wordCount = std::max(
				nonCompactMembershipCandidateBits.size(),
				std::max(centerCandidates.size(),
						includeContext ? contextCandidates.size() : std::size_t(0)));

		for (std::size_t wordIndex = 0; wordIndex < wordCount; ++wordIndex) {
			std::uint64_t candidates = wordIndex <
					nonCompactMembershipCandidateBits.size()
				? nonCompactMembershipCandidateBits[wordIndex] : 0;
			std::uint64_t contextCandidateBits = 0;
			if (wordIndex < centerCandidates.size())
				candidates |= centerCandidates[wordIndex];
			if (includeContext && wordIndex < contextCandidates.size())
				contextCandidateBits = contextCandidates[wordIndex];
			candidates |= contextCandidateBits;
			while (candidates != 0) {
				unsigned int bit = compactMembershipTrailingZeroCount(candidates);
				unsigned int r = static_cast<unsigned int>((wordIndex << 6) + bit);
				candidates &= candidates - 1;
				ReactionClass *rxn = reactions[r];
				std::uint64_t reactionBit = std::uint64_t(1) << bit;
				bool contextCandidate =
						(contextCandidateBits & reactionBit) != 0;
				bool centerCandidate = wordIndex < centerCandidates.size() &&
						(centerCandidates[wordIndex] & reactionBit) != 0;
				/* A context-only change cannot create a weighted-side mapping:
				 * the reaction center occupancy is unchanged.  Avoid probing an
				 * inactive compact rule. */
				if (contextCandidate && !centerCandidate &&
						m->getRxnListMappingId(r) < 0)
					continue;
				if (!compactMembershipDecisionsComplete) {
					if (cachedDecisions != 0) {
						if (!(*cachedDecisions)[r])
							continue;
					} else if (!rxn->shouldUpdateMembership(
								m, firedReaction, directProduct))
						continue;
				}
				if (refineMembershipChange &&
						!rxn->shouldUpdateMembershipForChange(
								m, membershipChange))
					continue;
				bool handledByCompactPool = false;
				int partnerComponent = -1;
				if (!compactPools.empty() &&
						rxn->supportsCompactPartnerPoolUpdate() &&
						rxn->getCompactPartnerPoolInfo(
							reactionPositions.at(r), partnerComponent)) {
					CompactPartnerPool *pool = rxn->getCompactPartnerPool();
					for (unsigned int p = 0; p < compactPools.size(); ++p) {
						if (compactPools.at(p) == pool) {
							handledByCompactPool = true;
							break;
						}
					}
				}
				if (handledByCompactPool)
					continue;
				refreshReactionMembership(rxn, r);
			}
		}
		return;
	}

	if (NFcore::shadowOn()) {
		/* Shadow-v2 works at the same granularity as NFsim membership itself:
		 * (runtime ReactionClass, reactantPosition) on each walked molecule.
		 * A multi-reactant rule can change membership for a molecule that was
		 * not itself mutated, so recording only mutated molecules or only
		 * reactant list 0 is not a valid correctness oracle. */
		cout << "@WALK " << NFcore::shadowEvent << " "
		     << m->getUniqueID() << " " << this->name << endl;

		/* Dump runtime registration once per MoleculeType.  Production
		 * dependency metadata should attach to these expanded runtime entries;
		 * the Python shadow tool only normalizes _sym<N> as diagnostic glue. */
		static std::set<const MoleculeType *> dumpedTypes;
		if (dumpedTypes.insert(this).second) {
			for (unsigned int r = 0; r < reactions.size(); ++r) {
				cout << "@REG " << this->name << " " << r << " "
				     << reactionPositions.at(r) << " "
				     << reactions[r]->getRxnId() << " "
				     << reactions[r]->getName() << endl;
			}
		}

		/* Current role-local memberships, captured before any tryToAdd.
		 * Loss candidates may be intersected with these entries: a local
		 * mapping can only disappear if it exists before the update. */
		for (unsigned int r = 0; r < reactions.size(); ++r) {
			if (!m->getRxnListMappingSet(r).empty())
				cout << "@MEMR " << NFcore::shadowEvent << " "
				     << m->getUniqueID() << " " << this->name << " "
				     << r << " " << reactionPositions.at(r) << " "
				     << reactions[r]->getRxnId() << " "
				     << reactions[r]->getName() << endl;
		}
	}
	const bool membershipDiff = generalMembershipDiffEnabled() &&
			firedReaction != 0 && system != 0 &&
			system->isMembershipMutationCaptureActive();
	const bool membershipFilter = generalMembershipFilterEnabled() &&
			!membershipDiff && firedReaction != 0 && system != 0 &&
			system->isMembershipMutationCaptureActive() &&
			(generalMembershipFilterForceEnabled() ||
			 reactions.size() >= generalMembershipFilterMinRegistrations());
	const bool membershipCandidateMode = membershipDiff || membershipFilter;
	const bool memprof = memprofEnabled();
	double mpCandidateTime = 0.0;
	long long mpCandidates = 0;
	if (membershipCandidateMode) {
		double candidateT0 = memprof ? memprofNow() : 0.0;
		prepareMembershipCandidates(m);
		if (memprof) {
			mpCandidateTime = memprofNow() - candidateT0;
			mpCandidates = static_cast<long long>(membershipCandidateScratch.size());
			NFcore::memprofCandidateTime += mpCandidateTime;
			NFcore::memprofCandidateCalls++;
			NFcore::memprofCandidates += mpCandidates;
		}
	}

	double memprofT0 = 0.0;
	long long mpVisits = 0, mpTries = 0, mpChanged = 0;
	double mpTryTime = 0.0;
	if (memprof) { memprofT0 = memprofNow(); NFcore::memprofWalkCalls++; }

	/* The dependency filter used to retain the O(number-of-registrations) loop
	 * and merely make most iterations cheap.  On Rasi-500 that still meant about
	 * 6.45 million rejected local entries for 624 events.  For ordinary
	 * (non-EnergyPattern) firings we can instead merge the sparse membership
	 * candidates with the precomputed set of entries whose propensity has
	 * non-membership runtime dependencies.  Sorting the candidate scratch list
	 * preserves the MoleculeType's native registration order, so match-list and
	 * A_tot updates occur in exactly the same order as the legacy full scan.
	 * Specialized incremental-energy paths stay on their existing code above. */
	const bool useSparseGeneralMembershipLoop = membershipFilter &&
			!NFcore::shadowOn() && !hasMembershipChange &&
			!useCompactMembershipIndex && !useCompactPartnerPoolIndex &&
			!refineMembershipChange && cachedDecisions == 0;
	if (useSparseGeneralMembershipLoop) {
		std::sort(membershipCandidateScratch.begin(),
				membershipCandidateScratch.end());
		size_t ci = 0, pi = 0;
		while (ci < membershipCandidateScratch.size() ||
				pi < membershipNonlocalPropensityCandidates.size()) {
			unsigned int candidateIndex = ci < membershipCandidateScratch.size()
					? membershipCandidateScratch[ci]
					: std::numeric_limits<unsigned int>::max();
			unsigned int propensityIndex = pi < membershipNonlocalPropensityCandidates.size()
					? membershipNonlocalPropensityCandidates[pi]
					: std::numeric_limits<unsigned int>::max();
			unsigned int r = std::min(candidateIndex, propensityIndex);
			bool isCandidate = candidateIndex == r;
			if (candidateIndex == r) ++ci;
			if (propensityIndex == r) ++pi;
			if (r >= reactions.size()) continue;
			if (memprof) { NFcore::memprofVisited++; mpVisits++; }

			ReactionClass *rxn = reactions[r];
			if (isCandidate && candidateTraceEnabled())
				cout << "#CAND " << name << " "
				     << (firedReaction ? firedReaction->getName() : string("?"))
				     << " " << rxn->getName() << endl;
			/* Preserve any reaction-class-specific rejection semantics even though
			 * BasicRxnClass returns true here. */
			if (!rxn->shouldUpdateMembership(m, firedReaction, directProduct))
				continue;
			bool useIndexedMembership = rxn->supportsDeferredMembershipUpdate();
			bool defer = this->system->isDeferringMembershipPropensityUpdates() &&
					useIndexedMembership;
			if (defer) {
				double deferredOldA = rxn->get_a();
				if (!isCandidate) {
					/* This entry is present only because its rate can change without a
					 * membership change.  Batch the rate refresh exactly as the full
					 * loop does. */
					this->system->deferMembershipPropensityUpdate(rxn, deferredOldA);
					continue;
				}
				double tryT0 = memprof ? memprofNow() : 0.0;
				bool changed = useIndexedMembership
					? rxn->tryToAddAndReportChangeWithIndex(
						m, reactionPositions[r], r)
					: rxn->tryToAddAndReportChange(
						m, reactionPositions[r]);
				if (memprof) {
					double dt = memprofNow() - tryT0;
					NFcore::memprofTryTime += dt; mpTryTime += dt;
					NFcore::memprofTryCalls++; mpTries++;
				}
				if (changed)
					this->system->deferMembershipPropensityUpdate(rxn, deferredOldA);
				continue;
			}

			double oldA = rxn->get_a();
			if (isCandidate) {
				double tryT0 = memprof ? memprofNow() : 0.0;
				/* The MoleculeType-local registration index is already known here.
				 * BasicRxnClass consumes it directly; other reaction classes inherit
				 * the virtual fallback to their existing tryToAdd implementation. */
				rxn->tryToAddWithIndex(m, reactionPositions[r], r);
				if (memprof) {
					double dt = memprofNow() - tryT0;
					NFcore::memprofTryTime += dt; mpTryTime += dt;
					NFcore::memprofTryCalls++; mpTries++;
				}
			}
			double newA = rxn->update_a();
			if (memprof && newA != oldA) { NFcore::memprofChanged++; mpChanged++; }
			this->system->update_A_tot(rxn, oldA, newA);
		}
		if (memprof) {
			double dt = memprofNow() - memprofT0;
			NFcore::memprofWalkTime += dt;
			NFcore::memprofAdd(this->name, dt, mpTryTime, mpCandidateTime, mpCandidates,
				mpVisits, mpTries, mpChanged);
		}
		return;
	}

	for( unsigned int r=0; r<reactions.size(); r++ )
	{
		if (memprof) { NFcore::memprofVisited++; mpVisits++; }
		ReactionClass * rxn=reactions.at(r);
		if (useCompactPartnerPoolIndex &&
				compactMembershipBitIsSet(*partnerCandidates, r)) {
			if (!compactPartnerPoolChanged)
				continue;
			bool defer = this->system->isDeferringMembershipPropensityUpdates();
			if (defer) {
				if (compactPartnerPoolBatchScheduled)
					continue;
				double oldA = rxn->get_a();
				this->system->deferMembershipPropensityUpdate(rxn, oldA);
			} else {
				double oldA = rxn->get_a();
				double newA = rxn->update_a();
				this->system->update_A_tot(rxn, oldA, newA);
			}
			continue;
		}
		if (!compactMembershipDecisionsComplete) {
			if (cachedDecisions != 0) {
				if (!(*cachedDecisions)[r])
					continue;
				} else if (firedReaction != 0 &&
						!rxn->shouldUpdateMembership(
								m, firedReaction, directProduct))
					continue;
			}
			if (refineMembershipChange &&
					!rxn->shouldUpdateMembershipForChange(
							m, membershipChange))
				continue;
			bool handledByCompactPool = false;
		int partnerComponent = -1;
		if (!compactPools.empty() &&
				rxn->supportsCompactPartnerPoolUpdate() &&
				rxn->getCompactPartnerPoolInfo(
					reactionPositions.at(r), partnerComponent)) {
			CompactPartnerPool *pool = rxn->getCompactPartnerPool();
			for (unsigned int p=0; p<compactPools.size(); p++) {
				if (compactPools.at(p) == pool) {
					handledByCompactPool = true;
					break;
				}
			}
		}
		if (handledByCompactPool)
			continue;
		if (!membershipCandidateMode && !NFcore::shadowOn() && !memprof) {
			/* Filter off: unchanged BNG3 refresh path. */
			refreshReactionMembership(rxn, r);
			continue;
		}
		const bool isCandidate = !membershipCandidateMode ||
			isPreparedMembershipCandidate(r);
		if (membershipFilter && !isCandidate &&
				rxn->propensityDependsOnlyOnMembership())
			continue;
		bool defer = this->system->isDeferringMembershipPropensityUpdates() &&
			rxn->supportsDeferredMembershipUpdate();
		if (defer) {
			double oldA = rxn->get_a();
			if (membershipFilter && !isCandidate) {
				/* A non-candidate cannot change this molecule's role-local
				 * membership, but a functional propensity may still depend on
				 * observables/functions changed elsewhere in the event.  Only
				 * suppress the deferred rate refresh when its semantics are
				 * membership-only. */
				if (!rxn->propensityDependsOnlyOnMembership())
					this->system->deferMembershipPropensityUpdate(rxn, oldA);
				continue;
			}
			bool changed = rxn->tryToAddAndReportChangeWithIndex(
					m, reactionPositions.at(r), r);
			if (membershipDiff && !isCandidate && changed) {
				cerr << "MEMFILTER DIFFERENTIAL MISS: event="
				     << NFcore::shadowEvent << " fired="
				     << (firedReaction ? firedReaction->getName() : string("?"))
				     << " molecule=" << m->getUniqueID()
				     << " type=" << name << " local=" << r
				     << " role=" << reactionPositions.at(r)
				     << " target=" << rxn->getName() << endl;
				abort();
			}
			if (changed)
				this->system->deferMembershipPropensityUpdate(rxn, oldA);
			continue;
		}
		double oldA = rxn->get_a();
		/* Role-local exact membership comparison.  listMatchIds() only
		 * inspects reactant list 0 and therefore misses changes in another
		 * role of a multi-reactant rule (e.g. the second ribosome in a
		 * collision pattern).  Molecule's MappingIdSet is already keyed by
		 * this local reaction entry, including reactantPosition. */
		const bool shadow = NFcore::shadowOn();
		MappingIdSet shadowBefore;
		MappingIdSet diffBefore;
		if (shadow) shadowBefore = m->getRxnListMappingSet(r);
		if (membershipDiff && !isCandidate)
			diffBefore = m->getRxnListMappingSet(r);
		if (!membershipFilter || isCandidate) {
			double tryT0 = memprof ? memprofNow() : 0.0;
			if (rxn->usesIncrementalMembership())
				rxn->tryToAddWithIndex(
						m, reactionPositions.at(r), r);
			else
				rxn->tryToAdd(m, reactionPositions.at(r));
			if (memprof) {
				double dt = memprofNow() - tryT0;
				NFcore::memprofTryTime += dt; mpTryTime += dt;
				NFcore::memprofTryCalls++; mpTries++;
			}
		}
		if (membershipDiff && !isCandidate) {
			MappingIdSet diffAfter = m->getRxnListMappingSet(r);
			if (!shadowSetsEqual(diffBefore, diffAfter)) {
				cerr << "MEMFILTER DIFFERENTIAL MISS: event="
				     << NFcore::shadowEvent << " fired="
				     << (firedReaction ? firedReaction->getName() : string("?"))
				     << " molecule=" << m->getUniqueID()
				     << " type=" << name << " local=" << r
				     << " role=" << reactionPositions.at(r)
				     << " target=" << rxn->getName() << endl;
				abort();
			}
		}
		double newA = rxn->update_a();
		if (membershipDiff && !isCandidate &&
				rxn->propensityDependsOnlyOnMembership() && newA != oldA) {
			cerr << "MEMFILTER PROPENSITY PREDICATE MISS: event="
			     << NFcore::shadowEvent << " fired="
			     << (firedReaction ? firedReaction->getName() : string("?"))
			     << " molecule=" << m->getUniqueID()
			     << " type=" << name << " local=" << r
			     << " role=" << reactionPositions.at(r)
			     << " target=" << rxn->getName()
			     << " oldA=" << oldA << " newA=" << newA << endl;
			abort();
		}
		if (shadow) {
			MappingIdSet shadowAfter = m->getRxnListMappingSet(r);
			if (!shadowSetsEqual(shadowAfter, shadowBefore))
				cout << "@CHGR " << NFcore::shadowEvent
				     << " " << m->getUniqueID()
				     << " " << this->name
				     << " " << r
				     << " " << reactionPositions.at(r)
				     << " " << rxn->getRxnId()
				     << " " << rxn->getName() << endl;
		}
		if (memprof && newA != oldA) { NFcore::memprofChanged++; mpChanged++; }
		this->system->update_A_tot(rxn,oldA,newA);
  	}
	if (memprof) {
		double dt = memprofNow() - memprofT0;
		NFcore::memprofWalkTime += dt;
		NFcore::memprofAdd(this->name, dt, mpTryTime, mpCandidateTime, mpCandidates,
				mpVisits, mpTries, mpChanged);
	}
}

void MoleculeType::updateConnectedRxnMembership(
		Molecule * m, ReactionClass * firedReaction, bool directProduct)
{
	// Preserve the MoleculeType's native reaction order so the connectivity path
	// mutates reactant containers in the same sequence as a full membership
	// refresh, while still using the precomputed connectivity matrix.
	for (unsigned int r=0; r<reactions.size(); r++) {
		rxn = reactions.at(r);
		if (!this->system->areReactionsConnected(
				firedReaction->getRxnId(), rxn->getRxnId())) {
			continue;
		}
		if (!rxn->shouldUpdateMembership(m, firedReaction, directProduct))
			continue;
		int pos = reactionPositions.at(r);
		double oldA = rxn->get_a();
		double oldAwithTotal = rxn->update_a();
		if (rxn->usesIncrementalMembership())
			rxn->tryToAddWithIndex(m, pos, r);
		else
			rxn->tryToAdd(m, pos);
		double newA = rxn->update_a();
		this->system->update_A_tot(rxn,oldA,newA);
		// Used for debugging to see which reaction rates changed
		// upon updating molecule membership
		// Arvind Rasi Subramaniam Nov 21, 2018
		if (!this->system->getTrackConnected()) continue;
		if (oldAwithTotal != newA) {
			this->system->getConnectedRxnFileStream() <<
			this->system->getGlobalEventCounter() << "\t" <<
			firedReaction->getName() << "\t" <<
					m->getMoleculeTypeName() << "\t" <<
					m->getUniqueID() << "\t" <<
					rxn->getName() << "\t" <<
					oldAwithTotal << "\t" << newA << endl;
		}
	}
}


int MoleculeType::getRxnIndex(ReactionClass * rxn, int rxnPosition)
{
	return system->getRxnIndex(rxn->getRxnId(),rxnPosition);

	//The old way!!  (that is slow if we have many rxns of course!)
	int r=0;
	for(rxnIter = reactions.begin(); rxnIter != reactions.end(); rxnIter++, r++ )
	{
		if((*rxnIter)==rxn)
			if(reactionPositions.at(r) == rxnPosition)
				return r;
	}
	cerr<<"Could not find this rxn: " << rxn->getName() << " in molecule Type: "<<name<<endl;
	exit(1);
}







void MoleculeType::removeFromObservables(Molecule *m)
{
	//cout<<"removing from observables:"<<m->getMoleculeTypeName()<<"_"<<m->getUniqueID()<<endl;
	//m->printDetails();

	//Check each observable and see if this molecule was counted, and if so, remove
	int ind=0;
  	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++ )
  	{
  		//Only subtract if m happened to be an observable... this saves us a compare call
  		//int matches = (*molObsIter)->isObservable(m);

  		// How many times does this observable match the molecule?
  		int matches = m->isObs(ind);
  		// subtract matches from observable
  		(*molObsIter)->subtract(matches);
		// set IsObs to zero, so if remove is called twice, we don't get negative counts.
  		m->setIsObs(ind,0);

  		ind++;
	}
}

void MoleculeType::removeFromRxns(Molecule * m)
{
	vector<CompactPartnerPool *> compactPools;
	vector<int> compactPoolOldSizes;
	vector<bool> compactPoolChanged;
	const vector<unsigned int> &compactPoolScaleList =
			getCompactPoolScaleCandidates();
	for (vector<unsigned int>::const_iterator scaleIt =
			compactPoolScaleList.begin();
			scaleIt != compactPoolScaleList.end(); ++scaleIt) {
		unsigned int r = *scaleIt;
		ReactionClass *rxn = reactions.at(r);
		CompactPartnerPool *pool = rxn->getCompactPartnerPool();
		if (pool == 0 || !pool->supportsBatchUpdate())
			continue;
		bool allReactionsSupportScale = true;
		const vector<ReactionClass *> &registered =
				pool->getRegisteredReactions();
		for (vector<ReactionClass *>::const_iterator it = registered.begin();
				it != registered.end(); ++it) {
			if (*it == 0 || !(*it)->supportsCompactPartnerPoolScale()) {
				allReactionsSupportScale = false;
				break;
			}
		}
		if (!allReactionsSupportScale)
			continue;
		int poolIndex = -1;
		for (unsigned int p=0; p<compactPools.size(); p++) {
			if (compactPools.at(p) == pool) {
				poolIndex = static_cast<int>(p);
				break;
			}
		}
		if (poolIndex >= 0)
			continue;
		compactPools.push_back(pool);
		compactPoolOldSizes.push_back(pool->size());
		rxn->remove(m, reactionPositions.at(r));
		compactPoolChanged.push_back(pool->size() != compactPoolOldSizes.back());
	}
	for (unsigned int p=0; p<compactPools.size(); p++) {
		if (compactPoolChanged.at(p))
			this->system->updateCompactPartnerPoolBatch(
					compactPools.at(p), compactPoolOldSizes.at(p),
					compactPools.at(p)->size());
	}

	int r=0;
	for(rxnIter = reactions.begin(); rxnIter != reactions.end(); rxnIter++, r++ )
	{
		ReactionClass *rxn = *rxnIter;
		bool handledByCompactPool = false;
		int partnerComponent = -1;
		if (!compactPools.empty() &&
			rxn->supportsCompactPartnerPoolUpdate() &&
			rxn->getCompactPartnerPoolInfo(
				reactionPositions.at(r), partnerComponent)) {
			CompactPartnerPool *pool = rxn->getCompactPartnerPool();
			for (unsigned int p=0; p<compactPools.size(); p++) {
				if (compactPools.at(p) == pool) {
					handledByCompactPool = true;
					break;
				}
			}
		}
		if (handledByCompactPool)
			continue;
		double oldA = (*rxnIter)->get_a();
		(*rxnIter)->remove(m, reactionPositions.at(r));
		double newA = (*rxnIter)->update_a();
		this->system->update_A_tot((*rxnIter),oldA,newA);
  	}
}




//TypeI local function: this molecule type depends on the value of this
//evaluated function
int MoleculeType::addLocalFunc_TypeI(LocalFunction *lf) {
	locFuncs_typeI.push_back(lf);
	return locFuncs_typeI.size()-1;

}

//TypeII local function: this molecule type, when updated, changes the
//value of this function
int MoleculeType::addLocalFunc_TypeII(LocalFunction *lf) {
	locFuncs_typeII.push_back(lf);
	return locFuncs_typeII.size()-1;

}
















void MoleculeType::addAllToObservables()
{
	/////  WARNING:: when calling this function, be sure to clear all observables
	/////  first, because this function will not clear observables.

//	cout<<"+++++++++ "<<this->getName()<<endl;

	//Check each observable and see if this molecule should be counted
	Molecule *mol;  int o=0;  int matches=0;
  	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++)
  	{
  		//cout<<"comparing to obs: "<<(*molObsIter)->getName()<<endl;

  		for( int m=0; m<mList->size(); m++ )
  		{
  			mol = mList->at(m);
  			matches = (*molObsIter)->isObservable(mol);
  			(*molObsIter)->add(matches);
  			mol->setIsObs(o,matches);
  			//cout<<"matches:"<<matches<<endl;
  		}
  		o++;
	}

}




void MoleculeType::addToObservables(Molecule *m)
{
	//Check each observable and see if this molecule should be counted
	int o=0;
  	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++)
  	{
		//cout<<"Comparing(in add: ";
		//cout<<m->getUniqueID()<<")"<<endl;

		int matches = (*molObsIter)->isObservable(m);
		m->setIsObs(o,matches);

		(*molObsIter)->add(matches);
		o++;
	}
	
}


void MoleculeType::outputMolObsNames(NFstream &fout)
{
	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++ )
		fout<<"\t"<<(*molObsIter)->getName();
}

void MoleculeType::outputMolObsCounts(NFstream &fout)
{
	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++ )
		fout<<"\t"<<(*molObsIter)->getCount();
}

void MoleculeType::printMolObsNames()
{
	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++)
		cout<<"\t"<<(*molObsIter)->getName();
}

void MoleculeType::printMolObsCounts()
{
	for(molObsIter = molObs.begin(); molObsIter != molObs.end(); molObsIter++ )
		cout<<"\t"<<(*molObsIter)->getCount();
}


void MoleculeType::printAllMolecules()
{
	for( int m=0; m<mList->size(); m++ ) {
		mList->at(m)->printDetails();
	}

}


void MoleculeType::printDetails() const
{
	cout<<"Molecule Type: "<< name << " type ID: " << type_id <<endl;

	cout<<"   -components ( ";
	for(int c=0; c<numOfComponents; c++) {

		cout<<compName[c];
		if(!isIntegerCompState[c]) {
			for(unsigned int s=0; s<possibleCompStates.at(c).size(); s++) {
				cout<<"~"<<possibleCompStates.at(c).at(s);
			}
		} else {
			cout<<"~integer[0-"<<possibleCompStates.at(c).at(possibleCompStates.at(c).size()-1)<<"]";
		}
		if(c<(numOfComponents-1)) cout<<", ";
	}
	cout<<" )"<<endl;

	//Output the local functions...
	cout<<"  Type I local functions include:";
	if(locFuncs_typeI.size()==0) cout<<"  none.";
	for(unsigned int ti=0; ti<locFuncs_typeI.size(); ti++) {
		cout<<"  "<<locFuncs_typeI.at(ti)->getNiceName();
	} cout<<endl;
	cout<<"  Type II local functions include:";
	if(locFuncs_typeII.size()==0) cout<<"  none.";
	for(unsigned int tii=0; tii<locFuncs_typeII.size(); tii++) {
		cout<<"  "<<locFuncs_typeII.at(tii)->getNiceName();
	} cout<<endl;


	cout<<"   -has "<< mList->size() <<" molecules."<<endl;
	cout<<"   -has "<< reactions.size() <<" reactions"<<endl;
//	cout<<"        of which "<< indexOfDORrxns.size() <<" are DOR rxns. "<<endl;
	cout<<"   -has "<< molObs.size() <<" molecules observables " <<endl;
}


// friend functions
// template<class T>
// NFstream& operator<<(NFstream& nfstream, const T& value)
// {
//     if (nfstream.useFile_)
// 	nfstream.file_ << value;
//     else
// 	nfstream.str_ << value;

//     return nfstream;
// }
