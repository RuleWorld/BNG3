# Blocked: `priority` cannot be used as a model identifier

## The bug

`priority` is declared as a lexer keyword (`BNGLexer.g4:211`, before `STRING` at
`:252`) because it is a load-bearing BNG2 rule modifier — `... rate priority=5` —
and a `bng3_events` field (`priority: 10`).

The consequence is that a molecule, observable, or parameter literally named
`priority` does not parse. It is a long-standing limitation, not a regression:
the keyword has been reserved since it was introduced.

Three name positions are affected:

| Position | Rule | Status |
|---|---|---|
| molecule / molecule-type name | `keyword_as_mol_name` (`BNGParser.g4:115-124`) | `priority` absent |
| observable name | `observable_def` (`:217-229`) | `STRING` only |
| expression identifier (`param_name`) | `arg_name` (`:565-572`) | `priority` absent |

## A second defect, found while fixing the first

`BNGAstVisitor` reads the observable name as the `STRING` token of
`Observable_defContext`. Simply widening the grammar would have made the
`priority` name parse and then been **silently dropped**, because the visitor
would not see the token it reads. The fix therefore has to introduce a named
subrule (`observable_name : STRING | PRIORITY ;`) rather than inline
`(STRING | PRIORITY)`, so the visitor can read the name unambiguously. Without
that, this "fix" would trade a parse error for silent data loss.

## Why this is not applied

The generated parser is committed (`cpp/parser/generated/*`) and is what the
build compiles. Changing `BNGParser.g4` therefore has no effect until the
parser is regenerated, and the visitor change breaks the build immediately,
because the new context class does not exist yet.

Regeneration is not possible in the environment that produced this analysis:

- the ANTLR generator is not vendored anywhere in the repository;
- `java` on this machine is the macOS stub — no JRE is installed, so the
  generator cannot run even if the `antlr-4.13.1-complete.jar` were fetched.

The repo's own archive already records this constraint:
`docs/archive/reports/ir-migration-2026-09-14/README_IR_MIGRATION_ELI15.md:292`
("this runtime does not contain the ANTLR generator/runtime needed to safely
regenerate it").

The patch is therefore **saved but not applied**:
`docs/known-blocked/priority-keyword-parser-fix.patch` (`git apply` from the
repository root, then regenerate with ANTLR 4.13.1 — the version the committed
generated files declare).

## Why the change is safe for the modifier

The `priority=5` modifier is only reachable in `rule_modifiers`, which is
reached after a complete rate law, never at a molecule-name position. Allowing
`PRIORITY` as a name therefore does not make the two readings ambiguous, and the
accompanying test asserted this by inspecting the parse tree rather than merely
checking that no error was reported:

- `A(x) -> A(x) k1 priority=5` → `(rule_modifiers priority = (expression (literal 5)))`
- `A(x) -> A(x) k1 priority=priority` → modifier whose value is an `arg_name`
- `priority -> A(x) k1` → `(species_def (molecule_pattern (keyword_as_mol_name priority)))`
- `begin observables / priority priority` → `(observable_def (observable_name priority) ...)`

## Known limits of the patch

Not fixed, and deliberately so:

- An observable named `priority` can be **declared** but not **referenced**:
  `observable_ref` (`:625`) is `STRING LPAREN ...`, so `priority()` in a rate law
  does not parse. This is pre-existing and applies to every `arg_name` keyword
  at baseline, not just `priority`.
- A bare observable name with no pattern list does not parse. Also
  pre-existing, and it fails identically for ordinary names.
