> Final backend policy is recorded in [DECISIONS.md](../DECISIONS.md); release
> scope is in the [capability inventory](../CAPABILITY_UNION_INVENTORY.md).
> [Current progress](../CURRENT_PROGRESS.md) tracks qualification evidence.

# ADR 0003: Native default and supported optional BNGsim backend

Status: Accepted by maintainer; supersedes the earlier intended BNGsim-default policy.

Native BNG3 ODE/SSA/PLA/PSA solvers are the default. BNGsim is a supported optional backend. The required architecture is one common compiled-model, capability, protocol, lifetime and result interface for finite and network-free simulators, including optional JAX, GPU and third-party backends. The shared contract and routing remain implementation work owned by #178; this decision does not claim that the interfaces are complete. Explicit selection must be honored, unavailable installations must produce clear errors, and unsupported semantics must not be approximated. See the [issue-keyed qualification table](../CURRENT_PROGRESS.md) for exact-main evidence.

CompiledModel owns resolved model semantics. The backend adapter consumes them rather than reinterpreting BNGL. Shared option and rate contracts remove duplicated policy in ActionDispatch, OdeIntegrator, exporters and finite-backend routing. Backend-specific mutable state remains separate.

BNGsim remains an external pinned dependency. Its optional installation does not make its release support experimental. Native solvers remain maintained. Method and backend are separate choices; network-free execution uses its own implementation of the common interface.

Issue #144 owns BNGsim completion; #178 and the common-backend implementation issue own interface consolidation. Each backend is accepted by its inventory checks against canonical source behavior or independent analytic/specification expectations. Default NFnext promotion follows #149 and DECISIONS.md.

See [decisions](../DECISIONS.md), [inventory](../CAPABILITY_UNION_INVENTORY.md) and the [previous ADR](../archive/ADR-0003-before-native-default.md).
