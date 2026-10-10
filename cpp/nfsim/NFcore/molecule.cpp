#include <cstdlib>
#include <iostream>
#include "NFcore.hh"
#include "compartment.hh"
#include <limits>
#include <queue>


using namespace std;
using namespace NFcore;

namespace {

unsigned long long profileMoleculeSignature(int id)
{
	unsigned long long value = static_cast<unsigned long long>(id);
	value += 0x9e3779b97f4a7c15ULL;
	value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
	value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
	return value ^ (value >> 31);
}

inline void appendRecycledListNode(list<Molecule *> &members, Molecule *molecule,
		list<Molecule *> *recycledNodes)
{
	if (recycledNodes == 0 || recycledNodes->empty()) {
		members.push_back(molecule);
		return;
	}
	list<Molecule *>::iterator node = recycledNodes->begin();
	*node = molecule;
	members.splice(members.end(), *recycledNodes, node);
}

}

int Molecule::uniqueIdCount = 0;





// Molecule Constructor
//
//
Molecule::Molecule(MoleculeType * parentMoleculeType, int listId, Compartment * compartment)
{
	if(DEBUG) cout<<"-creating molecule instance of type " << parentMoleculeType->getName() << endl;
	this->parentMoleculeType = parentMoleculeType;
	this->compartment = compartment;

	// set population type (1 for particle type, 0 for population type)
	this->population_count = ( parentMoleculeType->isPopulationType()  ?  0  :  1 );

	//First initialize the component states and bonds
	this->numOfComponents = parentMoleculeType->getNumOfComponents();
	/* One fused allocation for the four per-site arrays; see siteBlock. */
	{
		const size_t n = (size_t) numOfComponents;
		const size_t bondBytes  = ((n * sizeof(Molecule *) + 7) / 8) * 8;
		const size_t compBytes  = ((n * sizeof(int) + 7) / 8) * 8;
		const size_t idxBytes   = ((n * sizeof(int) + 7) / 8) * 8;
		const size_t visitBytes = n * sizeof(bool);
		this->siteBlock = new char [bondBytes + compBytes + idxBytes + visitBytes];
		char *blk = this->siteBlock;
		this->bond           = reinterpret_cast<Molecule **>(blk); blk += bondBytes;
		this->component      = reinterpret_cast<int *>(blk);       blk += compBytes;
		this->indexOfBond    = reinterpret_cast<int *>(blk);       blk += idxBytes;
		this->hasVisitedBond = reinterpret_cast<bool *>(blk);
	}
	for(int c=0; c<numOfComponents; c++)
		component[c] = parentMoleculeType->getDefaultComponentState(c);
	for(int b=0; b<numOfComponents; b++) {
		bond[b]=0; indexOfBond[b]=NOBOND;
		hasVisitedBond[b] = false;
	}
	boundComponentMask = 0;


	hasVisitedMolecule = false;
	hasEvaluatedMolecule = false;
	isMatchedTo=0;
	nReactions = 0;
	useComplex = parentMoleculeType->getSystem()->isUsingComplex();
	isPrepared = false;
	isObservable = 0;
	localFunctionValues=0;
	//isDead = true;

	//register this molecule with moleculeType and get some ID values
	ID_complex = this->parentMoleculeType->createComplex(this);
	ID_type = this->parentMoleculeType->getTypeID();
	ID_unique = Molecule::uniqueIdCount++;
	this->listId = listId;
	isAliveInSim = false;
}

// Molecule Deconstructor
//
//
Molecule::~Molecule()
{
	if(DEBUG) cout <<"   -destroying molecule instance of type " << parentMoleculeType->getName() << endl;
	parentMoleculeType = 0;

	delete [] isObservable;
	delete [] siteBlock;
	bond = 0; component = 0; indexOfBond = 0; hasVisitedBond = 0;

	if(localFunctionValues!=0)
		delete [] localFunctionValues;
}

void Molecule::removeActiveReactionMembershipIndex(int rxnIndex)
{
	for (vector<int>::iterator it = activeReactionMembershipIndices.begin();
			it != activeReactionMembershipIndices.end(); ++it) {
		if (*it == rxnIndex) {
			*it = activeReactionMembershipIndices.back();
			activeReactionMembershipIndices.pop_back();
			return;
		}
	}
}


namespace NFcore {
	bool shadowOn();
	extern long long shadowEvent;
	void shadowMutBond(Molecule *m1, int c1, Molecule *m2, int c2, bool added);
	void shadowMutState(Molecule *m, int c, int oldValue, int newValue);
}


void Molecule::prepareForSimulation()
{
	if(isPrepared) return;
	nReactions = parentMoleculeType->getReactionCount();
	int mappingCount = parentMoleculeType->getReactionMappingCount();
	activeReactionMembershipIndices.clear();
	rxnListMappings.init(mappingCount);

	isPrepared = true;

	//We do not belong to any observable... yet.
	isObservable=new int [parentMoleculeType->getNumOfMolObs()];
	for(int o=0;o<parentMoleculeType->getNumOfMolObs(); o++) {
		isObservable[o]=0;
	}


}








void Molecule::setUpLocalFunctionList()
{
	if (parentMoleculeType->getNumOfTypeIFunctions() > 0)
	{
		localFunctionValues=new double[parentMoleculeType->getNumOfTypeIFunctions()];
		for(int lf=0; lf<parentMoleculeType->getNumOfTypeIFunctions(); lf++) {
			localFunctionValues[lf]=0;
		}
	}
}




//Used so that this molecule can remember what its local function was
//evaluated to.  Only TypeI local functions are set up in this way
void Molecule::setLocalFunctionValue(double newValue,int localFunctionIndex) {
	if(localFunctionIndex<0 || localFunctionIndex>=parentMoleculeType->getNumOfTypeIFunctions()) {
		cout<<"Error in Molecule: trying to set the value of a local function, but the\n";
		cout<<"index provided was out of bounds!  I shall quit now."<<endl;
		exit(1);
	}
	//cout<<"here, mol: "<<this->getMoleculeTypeName()<<"_"<<this->getUniqueID()<<endl;
	//cout<<"localfunctionIndex given: "<< localFunctionIndex<<endl;
	//cout<<"n_localfunctionValue given: "<< localFunctionIndex<<endl;

	//cout<<"localFunctionValues="<<endl;
	//for(int k=0; k<parentMoleculeType->getNumOfTypeIFunctions(); k++) {
	//	cout<<"  "<<localFunctionValues[k]<<endl;
	//}
	//cout<<"done."<<endl;

	localFunctionValues[localFunctionIndex] = newValue;
}


double Molecule::getLocalFunctionValue(int localFunctionIndex) {
	if(localFunctionIndex<0 || localFunctionIndex>=parentMoleculeType->getNumOfTypeIFunctions()) {
		cout<<"Error in Molecule: trying to get the value of a local function, but the\n";
		cout<<"index provided was out of bounds!  I shall quit now."<<endl;
		exit(1);
	}
	return localFunctionValues[localFunctionIndex];
}


LocalFunction * Molecule::getLocalFunction(int localFunctionIndex) {
	if(localFunctionIndex<0 || localFunctionIndex>=parentMoleculeType->getNumOfTypeIFunctions()) {
			cout<<"Error in Molecule: trying to get the local function, but the\n";
			cout<<"index provided was out of bounds!  I shall quit now."<<endl;
			exit(1);
		}
	return parentMoleculeType->getTypeILocalFunction(localFunctionIndex);
}



void Molecule::updateRxnMembership(ReactionClass * r, bool useConnectivity,
		bool directProduct)
{
	System *profileSystem = parentMoleculeType != 0
		? parentMoleculeType->getSystem() : 0;
	if (r != 0 && profileSystem != 0 && profileSystem->isProfileReactionActive())
		profileSystem->recordProfileMembershipUpdate();

	if (useConnectivity) {
		parentMoleculeType->updateConnectedRxnMembership(
				this, r, directProduct);
	}
	else {
		parentMoleculeType->updateRxnMembership(
				this, r, directProduct);
	}
}

void Molecule::updateTypeIIFunctions()
{
	for (int i=0; i<parentMoleculeType->getNumOfTypeIIFunctions(); i++) {
		parentMoleculeType->getTypeIILocalFunction(i)->evaluateOn(this, LocalFunction::SPECIES);
	}
}

void Molecule::updateTypeIIFunctions( vector <Complex *> & productComplexes )
{
	for (int i=0; i<parentMoleculeType->getNumOfTypeIIFunctions(); i++) {
		vector <Complex *>::iterator complexIter;
		for ( complexIter = productComplexes.begin(); complexIter != productComplexes.end(); ++complexIter ) {
			parentMoleculeType->getTypeIILocalFunction(i)->evaluateOn( (*complexIter)->getFirstMolecule(), LocalFunction::SPECIES);
		}
	}
}

void Molecule::updateDORRxnValues()
{
	ReactionClass *rxn=0; int rxnIndex=-1, rxnPos=-1;
	//cout<<"Looping over :"<<parentMoleculeType->getNumOfDORrxns()<<" dor rxns "<<endl;
	for(int i=0; i<parentMoleculeType->getNumOfDORrxns(); i++) {
		rxn=parentMoleculeType->getDORrxn(i);
		rxnIndex=parentMoleculeType->getDORrxnIndex(i);
		rxnPos=parentMoleculeType->getDORrxnPosition(i);
		//cout<<"\t\ti="<<i<<" rxn="<<rxn->getName()<<" rxnIndex="<<rxnIndex<<" rxnPos="<<rxnPos<<endl;

		if(isPrepared) {
			//If we are in this reaction, then we have to update our value...
			if(getRxnListMappingId(rxnIndex)>=0) {
				//iterate over all mappings
				const MappingIdSet& tempSet = getRxnListMappingSet(rxnIndex);
				//iterate over all agent-mappings  for the same reaction
				for(MappingIdSet::const_iterator it= tempSet.begin();it!= tempSet.end(); ++it){

				//Careful here!  remember to update the propensity of this
				//reaction in the system after we notify of the rate factor change!
					double oldA = rxn->get_a();
					rxn->notifyRateFactorChange(this,rxnPos,*it);
					parentMoleculeType->getSystem()->update_A_tot(rxn,oldA,rxn->update_a());
				}
			}
		}
	}
}

void Molecule::removeFromObservables()
{
	parentMoleculeType->removeFromObservables(this);
}
void Molecule::addToObservables()
{
	parentMoleculeType->addToObservables(this);
}


// set population
bool Molecule::setPopulation( int count )
{
	if ( isPopulationType()  &&  (count >= 0) )
	{
		population_count = count;
		return true;
	}
	else return false;
}

// get popualtion
int Molecule::getPopulation() const
{
	return population_count;
}

// get compartment ID for cBNGL
string Molecule::getCompartmentId() const
{
	return compartment ? compartment->getId() : "";
}

// increase population by one
bool Molecule::incrementPopulation()
{
	if ( isPopulationType() )
	{
		++population_count;
		return true;
	}
	else return false;
}

// decrease population by one
bool Molecule::decrementPopulation()
{
	if ( isPopulationType()  &&  (population_count > 0) )
	{
		--population_count;
		return true;
	}
	else return false;

}


void Molecule::setComponentState(int cIndex, int newValue)
{
	if (this->component[cIndex] != newValue) {
		if (parentMoleculeType != 0 && parentMoleculeType->getSystem() != 0)
			parentMoleculeType->getSystem()->recordMembershipStateMutation(
					this, cIndex, this->component[cIndex], newValue);
		NFcore::shadowMutState(this, cIndex, this->component[cIndex], newValue);
	}
	this->component[cIndex]=newValue;
	if (useComplex)
		// Need to manually unset canonical flag since we're not calling a Complex method
		getComplex()->unsetCanonical();

	//if(listeners.size()>0) cout<<"Molecule State has changed..."<<endl;
	//Let all the listeners know that the state of a molecule has changed...
	//for(listenerIter = listeners.begin(); listenerIter != listeners.end(); listenerIter++ )
	//	(*listenerIter)->notify(this,stateIndex);
}
void Molecule::setComponentState(string cName, int newValue) {
	this->component[this->parentMoleculeType->getCompIndexFromName(cName)]=newValue;

	if (useComplex)
		// Need to manually unset canonical flag since we're not calling a Complex method
		getComplex()->unsetCanonical();

}


void Molecule::printDetails() {
	this->printDetails(cout);
}
void Molecule::printDetails(ostream &o)
{
	int degree = 0;
	o<<"++ Molecule instance of type: " << parentMoleculeType->getName();
	o<< " (uId="<<ID_unique << ", tId=" << ID_type << ", cId=" << ID_complex<<", degree="<<degree<<")"<<endl;
	o<<"      components: ";
	for(int c=0; c<numOfComponents; c++)
	{
		// Do not print non-bonded states so that mRNA representations are compact
		// Arvind Rasi Subramaniam
		if (bond[c] == 0) continue;
		if(c!=0)o<<"                  ";
		o<< parentMoleculeType->getComponentName(c) <<"=";
		o<<parentMoleculeType->getComponentStateName(c,component[c]);
		o<<"\tbond=";
		if(bond[c]==nullptr) o<<"empty";
		else {
			o<<bond[c]->getMoleculeTypeName()<<"_"<<bond[c]->getUniqueID();
			o<<"("<<bond[c]->getMoleculeType()->getComponentName(this->indexOfBond[c])<<")";
		}

		o<<endl;
	}

	o.flush();
	if(parentMoleculeType->getNumOfTypeIFunctions()>0) {
		o<<"      loc funcs:";
		for(int lf=0; lf<parentMoleculeType->getNumOfTypeIFunctions(); lf++) {
			if(lf!=0) o<<"                  ";
			o<<"  "<<parentMoleculeType->getTypeILocalFunction(lf)->getNiceName();
			o<<"="<<localFunctionValues[lf]<<"\n";
		}
	}
}

/**
 * Prints to screen, see printDetails(ostram )
 * @author Arvind Rasi Subramaniam
 */
void Molecule::printBondDetails() {
	this->printBondDetails(cout);
}

/**
 * Print all bonded states and their details to output stream
 *
 * Iterates through all components of a molecule type and prints
 * only those components with a bond including the binding partner
 * and the site of attachment.
 *
 * Same function written separately for printing to cout and NFStream
 * @param o - Stream to write to
 * @author Arvind Rasi Subramaniam
 */
void Molecule::printBondDetails(ostream &o) {
	o << parentMoleculeType->getName() << "\t" << ID_unique;
	o.flush();
}

/**
 * Same as printBondDetails(ostream )
 * but writes to NFStream file instead of ostream
 * @author Arvind Rasi Subramaniam
 */
void Molecule::printBondDetails(NFstream &o)
{
	if (parentMoleculeType->getSystem()->getRxnNumberTrack()) {
		o << parentMoleculeType->getTypeID() << "\t" << ID_unique;
	} else {
		o << parentMoleculeType->getName() << "\t" << ID_unique;
	}
	if (parentMoleculeType->getSystem()->getTrackConnected()) {
		o<<"\t";
		for(int c=0; c<numOfComponents; c++)
		{
			if(bond[c] == NULL) {continue;}
			else {
				o<<"||";
				o << parentMoleculeType->getComponentName(c);
				if (parentMoleculeType->getComponentStateName(c,component[c]) != "NO_STATE") {
					o<< "-" << parentMoleculeType->getComponentStateName(c,component[c]);
				}
				o<<":";
				o<<bond[c]->getMoleculeType()->getComponentName(this->indexOfBond[c]);
				o<<"-"<<bond[c]->getMoleculeTypeName()<<"_"<<bond[c]->getUniqueID();
			}
		}
	}
	o.flush();
}

//Get the number of molecules this molecule is bonded to
int Molecule::getDegree()
{
	return static_cast<int>(bondedComponentIndices.size());
}

// Get a label for this molecule or one of it's components (labels are not unique)
//   cIndex==-1  =>  get label for molecule, "m:typename"
//   cIndex>=0   =>  get label for component cIndex, "c:name~state"
string Molecule::getLabel ( int cIndex ) const
{
    string label("");
    if ( cIndex < 0 )
    {	// molecule label
        label += "m:" + getMoleculeTypeName();
        if (compartment != nullptr) {
            label += "@" + compartment->getId();
        }
    }
    else
    {	// component label
        label += "c:" + (   getMoleculeType()->isEquivalentComponent(cIndex)
        		          ? getMoleculeType()->getEquivalenceClassComponentNameFromComponentIndex(cIndex)
        		          : getMoleculeType()->getComponentName(cIndex) )
        		      + "~" + getMoleculeType()->getComponentStateName(cIndex, getComponentState(cIndex));
    }
    return label;
}


/* ---- shadow mutation tracking (NFSIM_SHADOW=1) ------------------------
 * Records the mutations an event performs -- changed component, and both the
 * old and new bond endpoints -- so a hypothetical topology-aware candidate
 * set can be constructed and compared against what the full membership scan
 * actually changed.  Nothing is skipped; this is diagnostic only. */
namespace NFcore {
	bool shadowOn() {
		static int on = -1;
		if (on < 0) on = (getenv("NFSIM_SHADOW") != 0) ? 1 : 0;
		return on == 1;
	}
	long long shadowEvent = 0;
	void shadowMutBond(Molecule *m1, int c1, Molecule *m2, int c2, bool added) {
		if (!shadowOn()) return;
		cout << "@MUTB " << shadowEvent
		     << " " << m1->getUniqueID()
		     << " " << m1->getMoleculeType()->getName()
		     << " " << m1->getMoleculeType()->getComponentName(c1)
		     << " " << m2->getUniqueID()
		     << " " << m2->getMoleculeType()->getName()
		     << " " << m2->getMoleculeType()->getComponentName(c2)
		     << " " << (added ? "add" : "del") << endl;
	}
	void shadowMutState(Molecule *m, int c, int oldValue, int newValue) {
		if (!shadowOn() || oldValue == newValue) return;
		cout << "@MUTS " << shadowEvent
		     << " " << m->getUniqueID()
		     << " " << m->getMoleculeType()->getName()
		     << " " << m->getMoleculeType()->getComponentName(c)
		     /* State NAMES, not internal integer indices: the dependency
		      * index is keyed on the XML state string, so logging the
		      * integer made every state dependency silently incomparable
		      * and suppressed loss-side state candidates entirely. */
		     << " " << m->getMoleculeType()->getComponentStateName(c, oldValue)
		     << " " << m->getMoleculeType()->getComponentStateName(c, newValue)
		     << endl;
	}
}

void Molecule::bind(Molecule *m1, int cIndex1, Molecule *m2, int cIndex2)
{
	System *profileSystem = m1 != 0 && m1->getMoleculeType() != 0
		? m1->getMoleculeType()->getSystem() : 0;
	bool profile = profileSystem != 0 && profileSystem->isProfileReactionActive();
	ProfileTime profileStart = profile ? profileNow() : ProfileTime();

	if(m1->bond[cIndex1]!=nullptr || m2->bond[cIndex2]!=nullptr) {
		cerr<<endl<<endl<<"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"<<endl;
		cerr<<"Your universal traversal limit was probably set too low, so some updates were not correct!\n\n";

		cerr<<"Trying to bond "<< m1->getMoleculeTypeName() << "_"<<m1->getUniqueID()<<"(";
		cerr<<m1->getMoleculeType()->getComponentName(cIndex1)<<") & ";
		cerr<< m2->getMoleculeTypeName()<<"_"<<m2->getUniqueID()<<"(";
		cerr<<m2->getMoleculeType()->getComponentName(cIndex2)<<")\n";
		cerr<<" to sites that are already occupied!  Check rxn rules!!\n";
		cerr<<"\n";
		m1->printDetails(cerr);
		m2->printDetails(cerr);
		exit(1);
	}

	m1->bond[cIndex1] = m2;
	m2->bond[cIndex2] = m1;

	m1->indexOfBond[cIndex1] = cIndex2;
	m2->indexOfBond[cIndex2] = cIndex1;
	if (profile)
		profileSystem->recordProfileTopologyMutation();
	if (profileSystem != 0)
		profileSystem->recordMembershipBondMutation(
				m1, cIndex1, m2, cIndex2, true);
	NFcore::shadowMutBond(m1, cIndex1, m2, cIndex2, true);
	if (cIndex1 < 64)
		m1->boundComponentMask |= (std::uint64_t(1) << cIndex1);
	if (cIndex2 < 64)
		m2->boundComponentMask |= (std::uint64_t(1) << cIndex2);
	m1->bondedComponentIndices.insert(
			std::lower_bound(m1->bondedComponentIndices.begin(),
				m1->bondedComponentIndices.end(), cIndex1), cIndex1);
	m2->bondedComponentIndices.insert(
			std::lower_bound(m2->bondedComponentIndices.begin(),
				m2->bondedComponentIndices.end(), cIndex2), cIndex2);

	//Handle Complexes
	if(m1->useComplex)
	{
		if(m1->getComplex()!=m2->getComplex())
		{
			// NOTE: mergeWithList will handle canonical flags
			m1->getComplex()->mergeWithList(m2->getComplex());
		}
		else
			// Need to manually unset canonical flag since we're not calling a Complex method
			m1->getComplex()->unsetCanonical();
	}
	if (profile)
		profileSystem->recordProfileBind(profileElapsedSeconds(profileStart));
}

void Molecule::bind(Molecule *m1, string compName1, Molecule *m2, string compName2)
{
	int cIndex1 = m1->getMoleculeType()->getCompIndexFromName(compName1);
	int cIndex2 = m2->getMoleculeType()->getCompIndexFromName(compName2);
	Molecule::bind(m1, cIndex1, m2, cIndex2);
}

// AS2023 - unbind can return the index of the molecule and component it
// selected for the unbinding for tracking purposes
vector<int> Molecule::unbind(Molecule *m1, int cIndex)
{
	System *profileSystem = m1 != 0 && m1->getMoleculeType() != 0
		? m1->getMoleculeType()->getSystem() : 0;
	bool profile = profileSystem != 0 && profileSystem->isProfileReactionActive();
	ProfileTime profileStart = profile ? profileNow() : ProfileTime();

	//get the other molecule bound to this site
	//cout<<"I am here. "<<bSiteIndex<<endl;
	Molecule *m2 = m1->bond[cIndex];
	if(m2==NULL)
	{
		cerr<<endl<<endl<<"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"<<endl;
		cerr<<"Your universal traversal limit was probably set too low, so some updates were not correct!"<<endl;
		cerr<<"Trying to unbind a binding site that is not bound!!  Check rxn rules, and traversal limits! Quitting."<<endl;
		cerr<<endl<<endl<<"The molecule is:"<<endl;
		m1->printDetails(cerr);
		cerr<<endl<<"The site trying to be unbound was: ";
		cerr<<m1->getMoleculeType()->getComponentName(cIndex)<<endl;
		exit(3);
	}


	int cIndex2 = m1->indexOfBond[cIndex];

	//break the bond (older compilers don't let you assign NOBOND to type molecule)
	m1->bond[cIndex] = 0; //NOBOND;
	m2->bond[cIndex2] = 0; //NOBOND;

	m1->indexOfBond[cIndex] = NOINDEX;
	m2->indexOfBond[cIndex2] = NOINDEX;
	if (profile)
		profileSystem->recordProfileTopologyMutation();
	if (profileSystem != 0)
		profileSystem->recordMembershipBondMutation(
				m1, cIndex, m2, cIndex2, false);
	NFcore::shadowMutBond(m1, cIndex, m2, cIndex2, false);
	if (cIndex < 64)
		m1->boundComponentMask &=
				~(std::uint64_t(1) << cIndex);
	if (cIndex2 < 64)
		m2->boundComponentMask &=
				~(std::uint64_t(1) << cIndex2);
	vector<int>::iterator occupied1 = std::lower_bound(
			m1->bondedComponentIndices.begin(), m1->bondedComponentIndices.end(), cIndex);
	if (occupied1 != m1->bondedComponentIndices.end() && *occupied1 == cIndex)
		m1->bondedComponentIndices.erase(occupied1);
	vector<int>::iterator occupied2 = std::lower_bound(
			m2->bondedComponentIndices.begin(), m2->bondedComponentIndices.end(), cIndex2);
	if (occupied2 != m2->bondedComponentIndices.end() && *occupied2 == cIndex2)
		m2->bondedComponentIndices.erase(occupied2);

	//Handle Complexes
	if(m1->useComplex)
	{
		// NOTE: mergeWithList will handle canonical flags
		m1->getComplex()->updateComplexMembership(m1);
	}

	//cout<<" UnBinding!  mol1 complex: ";
	//m1->getComplex()->printDetails();
	
	// AS2023 - this now returns what is unbound in a vector
	vector<int> tpl;
	tpl.push_back(m2->getUniqueID());
	tpl.push_back(cIndex2);
	if (profile)
		profileSystem->recordProfileUnbind(profileElapsedSeconds(profileStart));
	return tpl;
}

vector<int> Molecule::unbind(Molecule *m1, char * compName)
{
	int cIndex = m1->getMoleculeType()->getCompIndexFromName(compName);
	return Molecule::unbind(m1,cIndex);
}








// queue <Molecule *> Molecule::q;
// queue <int> Molecule::d;
// list <Molecule *>::iterator Molecule::molIter;
template <bool PROFILE, bool TRACKING, bool TRACK_TRUNCATION>
bool Molecule::breadthFirstSearchImpl(
		list <Molecule *> &members, Molecule *m, int depth,
		string *logstr, System *profileSystem,
		list <Molecule *> *recycledNodes)
{
	static queue <Molecule *> q;
	static queue <int> d;
	static list <Molecule *>::iterator molIter;
	ProfileTime profileStart = ProfileTime();
	unsigned long long moleculesVisited = 0;
	unsigned long long edgeVisits = 0;
	unsigned long long componentMinimumMoleculeId =
		std::numeric_limits<unsigned long long>::max();
	unsigned long long componentMaximumMoleculeId = 0;
	unsigned long long componentSignature = 0;
	bool traversalTruncated = false;
	if (PROFILE) profileStart = profileNow();

	// Reset queues to be safe (though they should be empty)
	while(!q.empty()) q.pop();
	while(!d.empty()) d.pop();

	if(m==0) {
		// Defensive check: mapping may be missing for some transformations (e.g., internal bond reconnection).
		// Avoid crashing the entire simulation; just skip traversal.
		cerr<<"Warning: Molecule::breadthFirstSearch called with m==null; skipping traversal.\n";
		return false;
	}

	//Create the queues (for effeciency, now queues are a static attribute of Molecule...)
	//queue <Molecule *> q;
	//queue <int> d;
	int currentDepth = 0;

	//cout<<"traversing on:"<<endl;
	//m->printDetails();

	//First add this molecule
	q.push(m);
	appendRecycledListNode(members, m, recycledNodes);
	d.push(currentDepth+1);
	m->hasVisitedMolecule=true;

	//Look at children until the queue is empty
	while(!q.empty())
	{
		//Get the next parent to look at (currentMolecule)
		Molecule *cM = q.front();
		currentDepth = d.front();
		q.pop();
		d.pop();
		if (PROFILE) {
			++moleculesVisited;
			unsigned long long moleculeId =
				static_cast<unsigned long long>(cM->getUniqueID());
			if (moleculeId < componentMinimumMoleculeId)
				componentMinimumMoleculeId = moleculeId;
			if (moleculeId > componentMaximumMoleculeId)
				componentMaximumMoleculeId = moleculeId;
			componentSignature ^= profileMoleculeSignature(cM->getUniqueID());
		}
		if (TRACKING && !logstr->empty()) {
			*logstr += "          [\"Delete\"," +
					to_string(cM->getUniqueID()) + "],\n";
		}

		//Make sure the depth does not exceed the limit we want to search
		if((depth!=ReactionClass::NO_LIMIT) && (currentDepth>=depth)) {
			if (TRACK_TRUNCATION) {
				for (vector<int>::const_iterator bit =
						cM->bondedComponentIndices.begin();
						bit != cM->bondedComponentIndices.end(); ++bit) {
					Molecule *neighbor = cM->bond[*bit];
					if (neighbor != 0 && !neighbor->hasVisitedMolecule) {
						traversalTruncated = true;
						break;
					}
				}
			}
			continue;
		}

		// Iterate only occupied sites.  Large polymer-like molecule types can
		// declare hundreds or thousands of components but usually have low degree.
		for (vector<int>::const_iterator bit = cM->bondedComponentIndices.begin();
				bit != cM->bondedComponentIndices.end(); ++bit)
		{
			const int c = *bit;
			Molecule *neighbor = cM->bond[c];
			if (neighbor == 0) continue; // defensive: sparse list must mirror bond[]
			if (PROFILE) ++edgeVisits;
			if(!neighbor->hasVisitedMolecule)
			{
				neighbor->hasVisitedMolecule=true;
				appendRecycledListNode(members, neighbor, recycledNodes);
				q.push(neighbor);
				d.push(currentDepth+1);
			}
		}
	}

	//clear the has visitedMolecule values
	for( molIter = members.begin(); molIter != members.end(); molIter++ )
		(*molIter)->hasVisitedMolecule=false;
	if (PROFILE)
		profileSystem->recordProfileConnectivity(profileElapsedSeconds(profileStart),
				moleculesVisited, edgeVisits, componentMinimumMoleculeId,
				componentMaximumMoleculeId, componentSignature);
	return traversalTruncated;
}

bool Molecule::breadthFirstSearch(list <Molecule *> &members, Molecule *m, int depth,
		list <Molecule *> *recycledNodes)
{
	System *profileSystem = m != 0 && m->getMoleculeType() != 0
		? m->getMoleculeType()->getSystem() : 0;
	if (profileSystem != 0 && profileSystem->isProfileReactionActive())
		return breadthFirstSearchImpl<true, false, true>(
				members, m, depth, 0, profileSystem, recycledNodes);
	return breadthFirstSearchImpl<false, false, true>(
				members, m, depth, 0, 0, recycledNodes);
}

// AS2023 - alternative call sig for logging that includes a log string
void Molecule::breadthFirstSearch(list <Molecule *> &members, Molecule *m, int depth, string &logstr)
{
	System *profileSystem = m != 0 && m->getMoleculeType() != 0
		? m->getMoleculeType()->getSystem() : 0;
	if (profileSystem != 0 && profileSystem->isProfileReactionActive()) {
		breadthFirstSearchImpl<true, true, false>(
				members, m, depth, &logstr, profileSystem, 0);
		return;
	}
	breadthFirstSearchImpl<false, true, false>(
			members, m, depth, &logstr, 0, 0);
}





bool Molecule::traverseBondedNeighborhood(list <Molecule *> &members, int traversalLimit,
		list <Molecule *> *recycledNodes)
{
	//always call breadth first search, it is a bit faster
	//if(traversalLimit>=0)
		return Molecule::breadthFirstSearch(
				members, this, traversalLimit, recycledNodes);
	//else
	//	this->depthFirstSearch(members);
}

// AS2023 - alternative call sig for logging that includes a log string
void Molecule::traverseBondedNeighborhood(list <Molecule *> &members, int traversalLimit, string &logstr)
{
	//always call breadth first search, it is a bit faster
	//if(traversalLimit>=0)
		Molecule::breadthFirstSearch(members, this, traversalLimit, logstr);
	//else
	//	this->depthFirstSearch(members);
}

//Isn't ever called really, but is availabe.  Note that it cannot use traversal limits
//because it is depth first
void Molecule::depthFirstSearch(list <Molecule *> &members)
{
	if(this->hasVisitedMolecule==true) {
		return;
	}

	this->hasVisitedMolecule=true;
	members.push_back(this);

	int cMax = this->numOfComponents;
	for(int c=0; c<cMax; c++)
	{
		if(hasVisitedBond[c]==true) continue;
		if(this->isBindingSiteBonded(c))
		{
			Molecule *neighbor = this->getBondedMolecule(c);
			neighbor->hasVisitedBond[indexOfBond[c]]=true;
			hasVisitedBond[c]=true;
			neighbor->depthFirstSearch(members);
		}
	}

	//clear things out
	hasVisitedMolecule = false;
	for(int c=0; c<numOfComponents; c++)
		hasVisitedBond[c] = false;
}


void Molecule::printMoleculeList(list <Molecule *> &members)
{
	cout<<"List of molecules contains: "<<endl;
	list <Molecule *>::iterator molIter;
	for( molIter = members.begin(); molIter != members.end(); molIter++ ) {
		cout<<"   -"<<(*molIter)->getMoleculeTypeName();
		cout<<"_u"<<(*molIter)->getUniqueID()<<endl;
	}
}
