import BNG.Util

namespace BNG

/-!
# Typed IDs

BNG3's proposed compiler IR resolves names once and then lets backends use IDs.
Lean is especially good at expressing that idea because *different kinds of
IDs are literally different types*.

For example, `ParameterId 3` cannot accidentally be passed to a function that
expects a `MoleculeTypeId`.  In C++ this is approximated with tagged wrappers;
in Lean the type checker enforces it everywhere.
-/

structure ParameterId where value : Nat
  deriving Repr, DecidableEq, BEq

structure FunctionId where value : Nat
  deriving Repr, DecidableEq, BEq

structure MoleculeTypeId where value : Nat
  deriving Repr, DecidableEq, BEq

structure ComponentTypeId where value : Nat
  deriving Repr, DecidableEq, BEq

structure StateId where value : Nat
  deriving Repr, DecidableEq, BEq

structure ObservableId where value : Nat
  deriving Repr, DecidableEq, BEq

structure CompartmentId where value : Nat
  deriving Repr, DecidableEq, BEq

structure ReactionRuleId where value : Nat
  deriving Repr, DecidableEq, BEq

structure EnergyPatternId where value : Nat
  deriving Repr, DecidableEq, BEq

structure SeedSpeciesId where value : Nat
  deriving Repr, DecidableEq, BEq

structure PopulationMapId where value : Nat
  deriving Repr, DecidableEq, BEq

/-- Occurrence of a molecule *inside one pattern*. -/
structure PatternMoleculeId where value : Nat
  deriving Repr, DecidableEq, BEq

/-- Occurrence of a site *inside one molecule occurrence*. -/
structure PatternSiteId where value : Nat
  deriving Repr, DecidableEq, BEq

/-- Identity of one explicit bond inside one pattern. -/
structure BondGroupId where value : Nat
  deriving Repr, DecidableEq, BEq

end BNG
