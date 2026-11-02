import CRNT.Interop.NetworkData

open CRNT Lean

/-- Decode the versioned NetworkData contract and reconstruct its native Network. -/
def main : IO Unit := do
  let input ← (← IO.getStdin).readToEnd
  match Json.parse input >>= fromJson? (α := NetworkData) with
  | .ok data =>
      let network := data.toNetwork
      IO.println (Json.mkObj
        [("numSpecies", toJson data.numSpecies),
         ("numReactions", toJson network.numReactions)])
  | .error error =>
      IO.eprintln s!"invalid NetworkData: {error}"
      IO.Process.exit 1
