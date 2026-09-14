import Lake
open Lake DSL

package «bng3-semantics» where
  version := v!"0.1.0"

/--
The formalization intentionally depends only on Lean's standard library.
That keeps the semantic kernel small and makes it easier to embed in CI later.
-/
@[default_target]
lean_lib BNG where
  roots := #[`BNG]
