import BNG.Runtime

namespace BNG

/-!
# Connected-complex semantics

BNGL uses molecular graph connectivity as part of the language:

* molecules written inside one top-level pattern with `.` describe one complex;
* top-level reactants separated by `+` must be distinct complexes;
* `DeleteMolecules` and `MoveConnected` operate on connected components, not
  just on one molecule record.

Production simulators maintain fast connectivity data structures.  The formal
reference implementation deliberately uses a tiny bounded graph traversal.
The traversal has explicit fuel (`mix.molecules.length`) so termination is
obvious and does not depend on a clever graph library.
-/

/-- Concrete molecule neighbours induced by the current bond graph. -/
def Mixture.neighbors (mix : Mixture) (id : MoleculeInstanceId) : List MoleculeInstanceId :=
  let fromBond (edge : RuntimeBond) : List MoleculeInstanceId :=
    if edge.a.molecule == id then [edge.b.molecule]
    else if edge.b.molecule == id then [edge.a.molecule]
    else []
  mix.bonds.flatMap fromBond

/-- One breadth/depth-agnostic expansion step. -/
def Mixture.expandFrontier (mix : Mixture)
    (seen frontier : List MoleculeInstanceId) : List MoleculeInstanceId :=
  frontier.flatMap mix.neighbors |>.filter (fun id => !(seen.contains id))

/--
Reference connected-component traversal.

The fuel is normally the number of molecules.  No simple path can discover
more distinct molecules than that, so extra recursion would add nothing.
-/
def Mixture.connectedFromFuel (mix : Mixture) :
    Nat → List MoleculeInstanceId → List MoleculeInstanceId → List MoleculeInstanceId
  | 0, seen, _ => seen
  | fuel + 1, seen, [] => seen
  | fuel + 1, seen, frontier =>
      let fresh := mix.expandFrontier seen frontier
      let seen' := (seen ++ fresh).foldl
        (fun acc id => if acc.contains id then acc else acc ++ [id]) seen
      mix.connectedFromFuel fuel seen' fresh

/-- Molecule IDs in the connected complex containing `start`. -/
def Mixture.connectedFrom (mix : Mixture) (start : MoleculeInstanceId) : List MoleculeInstanceId :=
  match mix.findMolecule? start with
  | none => []
  | some _ => mix.connectedFromFuel mix.molecules.length [start] [start]

/-- Are two concrete molecules in the same current molecular complex? -/
def Mixture.sameComplex (mix : Mixture) (a b : MoleculeInstanceId) : Bool :=
  (mix.connectedFrom a).contains b

/-- Delete a complete connected molecular complex. -/
def Mixture.deleteComplex? (mix : Mixture) (start : MoleculeInstanceId) : Option Mixture :=
  let doomed := mix.connectedFrom start
  if doomed.isEmpty then none
  else
    some {
      mix with
      molecules := mix.molecules.filter (fun m => !(doomed.contains m.id))
      bonds := mix.bonds.filter (fun edge =>
        !(doomed.contains edge.a.molecule) && !(doomed.contains edge.b.molecule)) }

/-- Move every molecule currently connected to `start` into one compartment. -/
def Mixture.moveComplex? (mix : Mixture) (start : MoleculeInstanceId)
    (destination : CompartmentId) : Option Mixture :=
  let ids := mix.connectedFrom start
  if ids.isEmpty then none
  else
    some {
      mix with
      molecules := mix.molecules.map (fun m =>
        if ids.contains m.id then { m with compartment := some destination } else m) }

/-- The empty mixture has no connected component at any ID. -/
theorem connectedFrom_empty (id : MoleculeInstanceId) :
    ({ molecules := [], bonds := [], nextMoleculeId := ⟨0⟩ } : Mixture).connectedFrom id = [] := by
  rfl

end BNG

namespace BNG

/-- Keep exactly the selected concrete molecules and internal bonds among them. -/
def Mixture.restrictToMolecules (mix : Mixture) (ids : List MoleculeInstanceId) : Mixture :=
  { mix with
    molecules := mix.molecules.filter (fun m => ids.contains m.id)
    bonds := mix.bonds.filter (fun edge =>
      ids.contains edge.a.molecule && ids.contains edge.b.molecule) }

/-- Extract the complete connected complex containing `start`. -/
def Mixture.complexContaining (mix : Mixture) (start : MoleculeInstanceId) : Mixture :=
  mix.restrictToMolecules (mix.connectedFrom start)

end BNG

namespace BNG

/-- Compare two molecule-ID collections extensionally, ignoring order. -/
def sameMoleculeIdSet (xs ys : List MoleculeInstanceId) : Bool :=
  allUnique xs && allUnique ys && xs.length == ys.length &&
    allContained xs ys && allContained ys xs

end BNG
