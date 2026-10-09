# Resolved: `priority` as a model identifier

Reviewed 2026-10-07 at [main `e1836c32`](https://github.com/RuleWorld/BNG3/tree/e1836c3274e685996d5e86883761e00e98257e09).
The earlier generator/environment blocker is historical. The grammar, visitor
and committed generated parser contain the fix. Do not apply the saved patch
to the current tree.

## Implemented behavior

[BNGParser.g4](../../cpp/parser/BNGParser.g4) accepts `PRIORITY` in
`keyword_as_mol_name`, `arg_name` and the named `observable_name` context.
`observable_ref` also uses that context, so `priority()` can reference an
observable. [BNGAstVisitor.cpp](../../cpp/parser/BNGAstVisitor.cpp) reads
`observable_name()->getText()`; accepting the token does not discard the name.
The [generated parser](../../cpp/parser/generated/BNGParser.cpp) is committed
and is what the build compiles.

[test_parser_units.cpp](../../tests/cpp/test_parser_units.cpp) has focused
contracts for:

- molecule, molecule-type and parameter names spelled `priority`;
- retention of an observable named `priority`;
- observable references, the rule modifier `priority=5`, and event priority
  and assignment fields in the same model.

The field and modifier syntax remains distinct from identifier positions.
These parser contracts establish representation, not native event execution;
dynamic events remain explicitly rejected by compilation
([#157](https://github.com/RuleWorld/BNG3/issues/157)).

## Historical provenance

The [original analysis](https://github.com/RuleWorld/BNG3/blob/e1836c3274e685996d5e86883761e00e98257e09/docs/known-blocked/priority-keyword-parser-fix.md)
and saved patch remain available in Git history. The unavailable-JRE
observation and restriction on `priority()` belong to that historical analysis;
they are not current blockers or instructions to regenerate the parser again.
