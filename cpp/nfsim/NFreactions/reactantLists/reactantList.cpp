#include "reactantList.hh"


using namespace NFcore;

ReactantList::ReactantList(unsigned int reactantIndex, TransformationSet *ts,
		unsigned int init_capacity, System *system)
{
	this->anyMultiMoleculeComplex = false;

	this->n_mappingSets = 0;
	/* Ordinary reaction lists historically reserve 25 MappingSets eagerly.
	 * Generated rule families usually use only a small fraction of that reserve,
	 * so expose the historical reserve for same-binary capacity sweeps. */
	if (init_capacity == 25) {
		/* One pointer slot covers inactive and single-match lists while the existing
		 * geometric growth path handles wider lists. MappingSets are materialized
		 * only when a slot becomes active. */
		init_capacity = 1;
		const char *capacityOverride = getenv("NFSIM_REACTANT_LIST_INITIAL_CAPACITY");
		if (capacityOverride != 0) {
			char *end = 0;
			long parsed = strtol(capacityOverride, &end, 10);
			if (end != capacityOverride && *end == '\0' && parsed >= 1 && parsed <= 1000000)
				init_capacity = static_cast<unsigned int>(parsed);
		}
	}
	this->capacity = init_capacity;
	this->reactantIndex = reactantIndex;
	this->ts=ts;
	this->system=system;
	this->mappingSets = new MappingSet *[init_capacity];
	this->msPositionMap = new unsigned int [init_capacity];
	for(int i=0; i<this->capacity; i++)
	{
		mappingSets[i]=0;
		msPositionMap[i]=i;
	}
}

ReactantList::~ReactantList()
{
	for(int i=0; i<capacity; i++)
	{
		delete mappingSets[i];
		msPositionMap[i]=0;
	}
	delete [] mappingSets;
	delete [] msPositionMap;
	this->n_mappingSets = 0;
	this->capacity = 0;
}


void ReactantList::pickRandom(MappingSet *&ms, NfsimRNG& rng)
{
	/* Draw first in every case: the RNG stream must advance identically to the
	 * eager-allocation behavior, including when the list is empty. */
	unsigned int rand = rng.random_int(0, n_mappingSets);
	if (n_mappingSets == 0) {
		/* An empty list still has to hand back a blank MappingSet: the firing
		 * path reads the picked mapping to detect the null event. Slot 0 is
		 * materialized on demand here and reused by the next push. */
		if (mappingSets[0] == 0)
			mappingSets[0] = ts->generateBlankMappingSet(reactantIndex, 0);
		ms = mappingSets[0];
		return;
	}
	ms = mappingSets[rand];
}


void ReactantList::pickRandomFromPopulation(MappingSet *&ms, NfsimRNG& rng)
{
	int rand = rng.random_int(0, getPopulation());

	int cum = 0;
	int ii = 0;
	while ( ii < n_mappingSets )
	{
		cum += mappingSets[ii]->getPopulation();
		if ( cum > rand ) break;
		++ii;
	}
	// A bit of error checking
	if ( ii == n_mappingSets )
	{
		cerr<<"!! Some problem picking population-weighted mappingSets from ReactionList!" << endl;
		exit(1);
	}
	ms = mappingSets[ii];
}


int ReactantList::getPopulation() const
{
	int pop = 0;
	for ( int ii=0;  ii < n_mappingSets;  ++ii )
	{
		pop += mappingSets[ii]->getPopulation();
	}
	return pop;
}


MappingSet * ReactantList::pushNextAvailableMappingSet()
{
	bool profile = system != 0 && system->isProfileReactionActive();
	if (profile) system->recordProfileMappingPush();

	//Check if we are going to exceed capacity
	if(n_mappingSets>=capacity)
	{
		int oldCapacity = capacity;
		ProfileTime profileStart = profile ? profileNow() : ProfileTime();
		int newCapacity;
		if(capacity>400000) {
			newCapacity = capacity+50000;
		} else {
			newCapacity=capacity*2;
		}

		//Copy everything over to new arrays that are double the size
		MappingSet ** new_mappingSets = new MappingSet *[newCapacity];
		unsigned int * new_msPositionMap = new unsigned int [newCapacity];
		for(int i=0; i<capacity; i++)  {
			new_mappingSets[i] = mappingSets[i];
			new_msPositionMap[i] = msPositionMap[i];
		}
		for(int i=capacity; i<newCapacity; i++)  {
			new_mappingSets[i] = 0;
			new_msPositionMap[i] = i;
		}

		//Swap the copied data with the real data and double the capacity
		delete [] mappingSets;
		delete [] msPositionMap;
		mappingSets = new_mappingSets;
		msPositionMap = new_msPositionMap;
		capacity=newCapacity;
		if (profile)
			system->recordProfileReactantListExpansion(
				static_cast<unsigned long long>(newCapacity - oldCapacity),
				profileElapsedSeconds(profileStart));
	}

	// Materialize a mapping set only when its reusable slot is first needed.
	MappingSet *&slot = mappingSets[n_mappingSets];
	if (slot == 0)
		slot = ts->generateBlankMappingSet(reactantIndex, n_mappingSets);
	++n_mappingSets;
	return slot;
}


void ReactantList::popLastMappingSet()
{
	if(n_mappingSets<=0) {
		printDetails();
		cout.flush();
		cerr<<"Trying to pop from an empty ReactantList!!"<<endl;
		exit(1);
	}
	if (system != 0 && system->isProfileReactionActive())
		system->recordProfileMappingPop();

	//Clear out the mappingSet (just in case) and decrease the count
	unsigned int clone = mappingSets[n_mappingSets-1]->getClonedMapping();
	mappingSets[n_mappingSets-1]->clear();
	n_mappingSets--;

	if(clone!=MappingSet::NO_CLONE) {
		this->removeMappingSet(clone);
	}
}



MappingSet * ReactantList::getMappingSet(unsigned int mappingSetId) const {

	//Get the mappingSet position
	int pos = msPositionMap[mappingSetId];

	//might want to do some error checking here to be safe, but oh well.

	//give the mapping set back
	return mappingSets[pos];

}

MappingSet * ReactantList::getWriteableMappingSet(unsigned int mappingSetId) {

	//Get the mappingSet position
	int pos = msPositionMap[mappingSetId];

	//might want to do some error checking here to be safe, but oh well.

	//give the mapping set back
	return mappingSets[pos];

}

MappingSet * ReactantList::getMappingSetByIndex(unsigned int index) const {
	if (index < n_mappingSets) {
		return mappingSets[index];
	}
	return NULL;
}

void ReactantList::removeMappingSet(unsigned int mappingSetId)
{
	//Make sure this mappingSet is not empty
	if(n_mappingSets==0) {
		printDetails();
		cout.flush();
		cerr<<"Trying to remove from an empty ReactantList!!"<<endl;
		exit(1);
	}
	if (system != 0 && system->isProfileReactionActive())
		system->recordProfileMappingRemove();

	//First, get the position of the mappingSet we need to remove
	int pos = msPositionMap[mappingSetId];

	//Make sure the position is valid (not out of bounds of the List)
	if(pos+1>(n_mappingSets)) {
		cout<<"Error in ReactantList:  you can't remove a mappingSet that has been cleared! (trying to remove: "<< mappingSetId << " in pos " << pos <<" but size is: "<<size()<<endl;
		printDetails();

		return;
	}

	//If the array has only one element, or we just happened to select the last element,
	//then just remove the last element without a swap
	if( pos+1 == (n_mappingSets) ) {
		popLastMappingSet();
		return;
	}

	//Otherwise, we have to swap with the last element in the list
	MappingSet *tempMappingSet = mappingSets[pos];
	mappingSets[pos] = mappingSets[n_mappingSets-1];
	mappingSets[n_mappingSets-1] = tempMappingSet;

	//Careful here!  We have to swap values in the msPositionMap
	//so that msPositionMap[mappingId] points correctly to where
	//that MappingSet now lives.  Notice that this is a different
	//swap than above in the MappingSets array!
	msPositionMap[mappingSetId] = n_mappingSets-1;
	msPositionMap[mappingSets[pos]->getId()] = pos;

	//Remember to remove
	n_mappingSets--;

	//Make sure we clear what we don't need
	unsigned int clone = tempMappingSet->getClonedMapping();
	tempMappingSet->clear();



	//Now, IF this mapping set had a clone, we have to remove it as well
	if(clone!=MappingSet::NO_CLONE) {
		this->removeMappingSet(clone);
	}
}


void ReactantList::printDetails() const
{
	//Used for debuggin'...
	cout<<"ReactantList that contains: "<<size()<<" MappingSets and has a capacity for "<<capacity<<" total sets."<<endl;

	for(int i=0; i<capacity; i++)
	{
		if(i<10) cout<<" ";
		cout<<"["<<i<<"]: "<<msPositionMap[i];
		if(i<(n_mappingSets)) {
			//cout<<"\t\tpos="<<i<<"(mol=";
			//if(mappingSets[i]->get(0)!=NULL) {
				cout<<"\t\tpos="<<i<<"(mol="<<mappingSets[i]->get(0)->getMolecule()->getUniqueID()<<") ";
			//}
		}

		if(i==n_mappingSets-1) cout<<"  _"<<endl;
		else cout<<endl;
		if (mappingSets[i]) mappingSets[i]->printDetails();
	}
	cout<<endl;
}
