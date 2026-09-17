import BNG.Rule

namespace BNG

/-!
# Explicit backend capability contracts

A formal semantics is only useful if unsupported lowering fails loudly.
Backends therefore get a small capability description and a deterministic
rejection reason rather than silently dropping a feature.
-/

inductive BackendKind where
  | network
  | nfsim
  | nfnext
  deriving Repr, DecidableEq, BEq

inductive UnsupportedReason where
  | filters
  | localScopes
  | deleteMolecules
  | moveConnected
  | matchOnce
  | totalRate
  | priority
  | productOnlyComponentEdit
  | clearBonds
  | moveCompartment
  deriving Repr, DecidableEq, BEq

/-- NFnext generic lowering currently handles local graph edits but not every BNGL rule modifier. -/
def nfnextUnsupportedReasons (d : RuleDirection) : List UnsupportedReason :=
  let filters := if d.filters.isEmpty then [] else [.filters]
  let scopes := if d.localScopes.isEmpty then [] else [.localScopes]
  let modifiers := d.modifiers.flatMap (fun modifier =>
    match modifier with
    | .deleteMolecules => [.deleteMolecules]
    | .moveConnected => [.moveConnected]
    | .matchOnce => [.matchOnce]
    | .totalRate => [.totalRate]
    | .priority _ => [.priority])
  let productOnly := d.mutations.any (fun mutation =>
    match mutation with
    | .changeState (.byType _ _) _ => true
    | .clearBonds (.byType _ _) => true
    | .createBond (.byType _ _) _ => true
    | .createBond _ (.byType _ _) => true
    | .deleteBond (.byType _ _) _ => true
    | .deleteBond _ (.byType _ _) => true
    | _ => false)
  let clears := d.mutations.any (fun mutation =>
    match mutation with | .clearBonds _ => true | _ => false)
  let moves := d.mutations.any (fun mutation =>
    match mutation with | .moveCompartment _ _ => true | _ => false)
  filters ++ scopes ++ modifiers ++
    (if productOnly then [.productOnlyComponentEdit] else []) ++
    (if clears then [.clearBonds] else []) ++
    (if moves then [.moveCompartment] else [])

/-- Can the current generic NFnext lowering represent this direction without semantic loss? -/
def nfnextSupported (d : RuleDirection) : Bool :=
  (nfnextUnsupportedReasons d).isEmpty

end BNG
