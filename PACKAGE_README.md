# BNG3 Lean formalization package

Contents:

- `BNG3-main/` — full modified BNG3 source tree.
- `FORMALIZATION_REPORT.md` — implementation/status report.
- `BNG3_Lean_formalization.patch` — unified diff against the user-provided original BNG3 tree.

Primary formal project: `BNG3-main/formal/lean/`.

Validation command:

```bash
cd BNG3-main/formal/lean
./scripts/validate_all.sh
```

In the packaging environment the static/formal-source checks and the real C++
NFnext conformance harness pass.  Lean itself is not installed there, so
`lake build` remains a required external validation gate.
