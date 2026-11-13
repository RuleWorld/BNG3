# Issue #140: Type Simulation Protocol Actions and Share Option Semantics

This directory contains the independent release acceptance suite for **Issue #140** (B03: Type simulation protocol actions and share option semantics) and **Issue #178** (G08: Consolidate action, numerical and exporter semantic decisions).

## Acceptance Checks

- `release-entrypoints`: Python (`bionetgen.run`, `bionetgen.load().simulate()`), CLI (`bng_cpp`), and BNGL action blocks return equivalent independent expected results and files.
- `release-actions`: Each simulation action and shared option has default, explicit, invalid, and interaction cases compared against independent expected semantics (and pinned BNG2 where available).
- `release-capability-coverage-140`: Complete independent evaluation of all assigned inventory rows for simulation actions and options.

## Covered Inventory Rows

- `action.simulate_pla`
- `action.simulate_pla.method`
- `action.simulate_psa`
- `action.simulate_psa.method`
- `action.simulate.suffix`
- `action.simulate.sparse`
- `action.simulate.max_sim_steps`
- `action.simulate.check_product_scale`
- `action.simulate.pla_config`
- `action.simulate.poplevel`
- `action.simulate.verbose`
- `action.simulate.save_progress`
- `action.simulate.print_end`
- `action.simulate.print_on_stop`
- `action.simulate.print_n_species_active`
- `action.simulate.netfile`
- `action.simulate.argfile`

## Independent Oracles and Bounds

1. **Analytic First-Order Conversion Law**:
   For $A \xrightarrow{k} B$ with $k=0.4$, $A(0)=10$, $B(0)=0$:
   - $A(t) = 10 e^{-0.4 t}$
   - $B(t) = 10 (1 - e^{-0.4 t})$
   - Absolute tolerance bound for ODE trajectories: $10^{-6}$.

2. **Stochastic Invariant Conservation**:
   For SSA, PLA, and PSA stochastic simulation:
   - Total mass is conserved: $A(t) + B(t) = 10$ at all output timepoints.
   - Non-negative integer/particle counts: $A(t) \ge 0$, $B(t) \ge 0$.

3. **Entrypoint Parity**:
   The output grid, observable values, and generated file artifacts (.gdat) match across:
   - CLI: `bng_cpp <model>.bngl`
   - Python Modern API: `bionetgen.run(model, method=..., t_end=..., n_steps=...)`
   - Python Object API: `bionetgen.load(model).simulate(method=..., ...)`
