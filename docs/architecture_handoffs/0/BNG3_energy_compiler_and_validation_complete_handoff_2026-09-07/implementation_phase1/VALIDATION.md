# Validation record

## Exact source target

`RuleWorld/BNG3@3bc7b4ff131f8927421bc8eae170e3b248b75318`
(PR #2, `codex/bng3-integration-foundations`).

## Passed here

- `EnergyDeltaPlan.cpp` + smoke executable:
  `g++ -std=c++17 -Wall -Wextra -Werror -pedantic` — pass.
- `CompiledRateLaw.cpp`, `CompiledRule.cpp`, `CompiledModel.cpp` + smoke
  executable against API-compatible AST stubs — pass.
- reaction-center energy index standalone compile/run under `-Werror` — pass.
- binding/state energy-plan bridge compile against API-compatible NFcore stubs — pass.
- final patch parse/apply check against exact changed source contexts — pass.
- `git diff --check` after applying patch — pass.

## Not runnable here

- complete repository build;
- CTest suite;
- `test_energy_compiler` linked against real BNG3;
- independent native-NFsim fixed-seed/distributional parity;
- BNG2 network-generation oracle suite.

Reason: the VM shell had no outbound DNS to clone the repository, while the
connected GitHub integration returned HTTP 403 for branch/ref/content writes.
GitHub source reads remained available and were used to ground every integration
hunk in PR #2's exact head.
