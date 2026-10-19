/*!\file compartment.hh
    \brief Compartment class for cBNGL spatial models
*/

#ifndef COMPARTMENT_HH_
#define COMPARTMENT_HH_

#include <string>

using namespace std;

namespace NFcore
{
	//! Represents a spatial compartment in cBNGL models
	/*!
	    Compartments define spatial regions where molecules can exist.
	    Each compartment has a unique ID, spatial dimensions (2D or 3D),
	    and a size (area or volume).
	    
	    @author NFsim cBNGL Team
	*/
	class Compartment
	{
		public:
			//! Constructor
			/*!
			    @param id Unique compartment identifier (e.g., "c0", "cytoplasm")
			    @param spatialDimensions 2 for membrane/surface, 3 for volume
			    @param size Volume (3D) or area (2D) of the compartment
			    @param parent Optional parent compartment for nested structures
			*/
			Compartment(
				string id, 
				int spatialDimensions, 
				double size, 
				Compartment* parent = 0
			);
			
			//! Destructor
			~Compartment();
			
			//! Get the compartment ID
			string getId() const { return id; }
			
			//! Get spatial dimensions (2 or 3)
			int getSpatialDimensions() const { return spatialDimensions; }
			
			//! Get the size (volume or area)
			double getSize() const { return size; }
			
			//! Alias for getSize() - returnsibling volume or area
			double getVolume() const { return size; }
			
			//! Get parent compartment (for nested compartments)
			Compartment* getParent() const { return parent; }
			
			//! Set parent compartment
			void setParent(Compartment* p) { parent = p; }

			//! Set the size (volume or area)
			/*!
			    Resets the compartment size, e.g. after a parameter-backed
			    volume changes via System::updateSystemWithNewParameters().
			    Non-finite or non-positive sizes print a warning (as the
			    constructor does) but are still stored so callers can
			    fail closed downstream.
			*/
			void setSize(double newSize);

			//! Name of the System parameter this size tracks ("" = static)
			/*!
			    When non-empty and the named parameter exists,
			    System::updateCompartmentSizesFromParameters() copies the
			    parameter value into the size before reaction propensities
			    are refreshed. Use System::setCompartmentSizeParameter()
			    to establish the link, or set it explicitly for loaders
			    that resolve a plain-identifier volume expression.
			*/
			void setSizeParameterName(const string& name) { sizeParameterName = name; }
			string getSizeParameterName() const { return sizeParameterName; }
			
			//! Check if this compartment is inside another
			/*!
			    For nested compartments, checks if this is a child of 'other' (directly or transitively)
			    @param other The potential parent compartment
			    @return true if this compartment is inside 'other'
			*/
			bool isInside(Compartment* other) const;

			//! Whether two compartments are equal or directly adjacent in the hierarchy.
			bool adjacent(Compartment* other) const;
			
			//! Print compartment details for debugging
			void printDetails() const;
			
		private:
			string id;                    //!< Compartment identifier
			int spatialDimensions;        //!< 2 for membrane, 3 for volume
			double size;                  //!< Volume (3D) or area (2D)
			string sizeParameterName;     //!< System parameter tracked by size ("" = static)
			Compartment* parent;          //!< Parent compartment for nesting (optional)
	};
}

#endif /* COMPARTMENT_HH_ */
