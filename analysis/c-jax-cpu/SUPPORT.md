# Bounded support statement — installed CPU JAX SSA immigration–death (#473)

Owner: Agent C (independent lane). One previously unqualified real input class,
executed against an installed subject at exact main `0d42c6666525debeed61a6e7731fedefd1196df6`.

## Installed subject digest

Staged installed package (isolated with `python -S` so the editable finder pointing
at the primary checkout is not active; verified `bionetgen.__file__` and
`_bionetgen_cpp.__file__` resolve to the staged tree):

- native extension `sha256` `8676310507a10bd36abac32e3a3a26d7c6df7232b2b63377bee713766ef845e4`
- `python/bionetgen/jax_ssa.py` `sha256` `e240b430df25aee16c4e414b0316659cbe09df8c6a062ff45916743c85604a9a`
- `python/bionetgen/jax_ode.py` `sha256` `45a3822da0a2ede184d124d63d1454b437da7fcf85c3a292d1f11c8667671aea`
- JAX `0.11.2`, jaxlib `0.11.2`, numpy `2.5.2`, device `cpu:0` (`JAX_PLATFORMS=cpu`)

## Predeclared case and receipt

`PREDECLARED_PLAN.md` (sha256 `fa89be33…`, written before any new stochastic run)
declares the law, seed and error control. Receipt `c-jax-case.json` records:

| check | predeclared control | observed | result |
|---|---|---|---|
| transient mean | `|mean-4(1-e^-0.5t)| <= 3*SE+0.05` (batch 4096, 21 grid points) | max error 0.0620 <= allowed 0.1450 | PASS |
| stationary CDF | KS to Poisson(4) <= DKW(0.001,8192)=0.02154 | KS 0.00530; mean 4.017, var 4.026 | PASS |
| wrong-law power | KS to Poisson(6) > DKW | KS 0.339 >> 0.02154 | rejected |
| invariants | all populations >= 0 | true | PASS |

Fixed seed base `20261118`, batch budgets 4096/8192, `t_end=20 s` (10 relaxation
time constants). No seed, budget, alpha, law or tolerance was changed after the
run. `0 -> A()` (zero-order creation) plus `A() -> 0` (first-order death) is a
real mass-action input class absent from the existing JAX SSA tests.

## Downstream results

- New installed test module `tests/python/test_jax_ssa_immigration_death.py`: **2 passed** against the staged subject.
- Wired into `tests/validation/release/cases/issue-473/test_jax_backends_release.py::test_release_jax_ssa`.
- Full installed JAX baseline on the same subject: **62 passed / 0 failed**
  (existing 60 + new 2), confirming no regression.
- Existing moment/seed-isolation tests are reused, not duplicated; unavailable-extra
  diagnostics (`test_jax_ssa_unavailable_without_optional_dependencies`,
  `test_jax_ssa_import_safety`) remain separate and were not counted as an installed run.

## Bounded support statement

The installed CPU JAX direct SSA backend **supports this immigration–death input
class** (zero-order creation + first-order decay) under the predeclared transient
mean and stationary Poisson law with the stated fixed seed and run budgets. No
product defect was demonstrated, so no product repair is required and this is a
test/oracle-only addition. This is a one-class result: it does not establish
full `release-jax-ssa`, does not cover functional/time-dependent SSA rates (the
flattening intentionally fails closed on them), and makes no GPU claim. A owns
final #473 integration and dispatch.
