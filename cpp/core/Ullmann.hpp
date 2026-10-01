#ifndef BNGCORE_ULLMANN_HPP_
#define BNGCORE_ULLMANN_HPP_

#include "BNGcore.hpp"

namespace BNGcore
{

    /////////////////
    // UllmannBase //
    /////////////////
    
    class UllmannBase
    {   
        public:
            // structors
            UllmannBase  ( const PatternGraph & _Ga, const PatternGraph & _Gb  );
            virtual ~UllmannBase ( );
          
            virtual size_t  find_mappings ( List <Map> & maps ) { return 0; };

        protected:       
            void  initialize_M_vec ( );
            void  copy_M ( ullmann_M_t & orig, ullmann_M_t & copy );

            void  print_M ( ullmann_M_t & M );

            // Ga is the subgraph, Gb is the graph
            const PatternGraph &  Ga;
            const PatternGraph &  Gb;            
            // number of nodes in each graph
            const size_t   pa;
            const size_t   pb;
            // permutation matrix M
            ullmann_M_t                  M;
            // stack of intermediate permutation matrices 
            std::vector< ullmann_M_t >   M_vec;
            // tracking structures (F=targets, H=maps are defined in Ullmann 1976)
            node_container_t  targets;
            std::vector<bool> targets_mask;
            Map               map;

            // Deterministic row order for the M matrix.
            //
            // `M` is a `std::map<Node*, ...>`, whose iteration order is
            // ascending ADDRESS. `find_maps` used to seed its recursion at
            // `M.begin()` and step with `++row_iter`, so the order in which
            // pattern nodes were assigned - and therefore the order in which
            // subgraph isomorphisms were emitted - was a function of heap
            // addresses, i.e. of ASLR. Downstream that order decides the
            // emission order of reactions, so the same model file could
            // produce different .net output in different processes whenever
            // two reactions tied on everything the writer prints.
            //
            // This vector holds the rows in `Ga` order instead. `Ga` is a
            // `std::vector<Node*>`, so its iteration order is insertion order
            // and is stable across processes and runs. Callers walk
            // `M.find(rowOrder_[d])` instead of `++row_iter`, leaving the map
            // itself and its `find`/`insert` call sites untouched.
            std::vector <Node*>  rowOrder;
    };         




    //////////////////
    // UllmannSGIso //
    //////////////////
    
    // Subgraph Isomorphism using Ullmann's 1976 method (basically)
    class UllmannSGIso : public UllmannBase
    {
        public:
            // structors
            UllmannSGIso  ( const PatternGraph & Ga, const PatternGraph & Gb  ) : UllmannBase ( Ga, Gb ) {};
            virtual ~UllmannSGIso ( ) {};

            // find subgraph isomorphisms
            virtual size_t  find_maps ( List <Map> & maps );
            // Set maximum number of maps to find (0 = unlimited). Stops early once limit reached.
            void set_max_maps ( size_t max ) { max_maps_ = max; };

        protected:
            // Depth is an index into UllmannBase::rowOrder, not an iterator
            // into the address-ordered M map; see that member for why.
            size_t   next_node ( size_t d, List <Map> & sg_iso_maps );
            bool     find_next_match ( col_iter_t & col_iter, const col_iter_t & col_end );
            bool     build_M0  ( );
            bool     refine_M  ( );
            bool     refine_M ( row_iter_t & row_iter, col_iter_t & col_iter );
            size_t   max_maps_ = 0;  // 0 = unlimited
    };   
   

}


#endif /* BNGCORE_ULLMANN_HPP_ */
