"""Synthetic reaction networks of a chosen shape, for GPU work measurement.

The two networks that ship with the repository are both degenerate from an
accelerator's point of view: one has 2 reactions, the other has 4, so a device
lane performs a handful of lanes of arithmetic per work item. Every conclusion
drawn from them is a conclusion about dispatch overhead, not about the
accelerator. This module writes networks with a chosen number of reactions and
a chosen number of events per trajectory, so a GPU measurement can be placed at
a specific point on the (reactions x events) plane instead of being guessed at.

Everything here emits BNGL text and nothing else: no simulation, no timing, no
engine import. `ModelSpec` is a pure description, `to_bngl` is a pure function
of it, and the same spec always yields byte-identical BNGL. That matters for the
harness, which re-derives the model in every worker process and must be able to
assert that every process saw the same network.

Shape parameters:
    species     number of species in the pool
    reactions   exact number of network reactions after generation
    event_density
                target mean SSA reaction events per trajectory. The model is
                generated first, then `calibrate_event_density` runs a short
                probe batch and rescales every rate constant so the measured
                density lands near the target. Calibration is a search, so it
                reports the density it actually achieved rather than the one
                requested.

The reaction mix is deliberately heterogeneous: a unimolecular chain (cheap,
serial), bimolecular association (cost grows with population, so it stresses
the device's arithmetic rather than its thread count), and first-order decay.
"""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    """A reproducible description of a synthetic network.

    Attributes:
        name: model id, also the base filename.
        species: number of species in the pool.
        reactions: number of network reactions to emit.
        event_density: target mean events per trajectory, or 0 for unscaled.
        t_end: simulation horizon in model time units.
        n_steps: output grid resolution.
        pop: initial population per species.
        volume: compartment volume (mass-action stochastic scaling).
        rates: the per-channel base rate constants.
        chain_fraction: share of reactions that are unimolecular chain steps.
        decay_fraction: share of reactions that are first-order decays.
        seed: BNGL seed, fixed so the same spec always produces the same file.
    """

    name: str = "synth"
    species: int = 8
    reactions: int = 32
    event_density: float = 0.0
    t_end: float = 1.0
    n_steps: int = 10
    pop: int = 100
    volume: float = 1.0
    rates: dict[str, float] = field(
        default_factory=lambda: {"chain": 1.0, "assoc": 0.001, "decay": 0.5}
    )
    chain_fraction: float = 0.4
    decay_fraction: float = 0.2
    seed: int = 12345

    def scaled(self, factor: float) -> "ModelSpec":
        """Return a copy with every rate constant multiplied by `factor`."""
        return ModelSpec(
            name=self.name,
            species=self.species,
            reactions=self.reactions,
            event_density=self.event_density,
            t_end=self.t_end,
            n_steps=self.n_steps,
            pop=self.pop,
            volume=self.volume,
            rates={k: v * factor for k, v in self.rates.items()},
            chain_fraction=self.chain_fraction,
            decay_fraction=self.decay_fraction,
            seed=self.seed,
        )

    def key(self) -> str:
        """A stable identifier for caching the generated file."""
        parts = [
            self.name,
            f"s{self.species}",
            f"r{self.reactions}",
            f"d{self.event_density:g}",
            f"t{self.t_end:g}",
            f"n{self.n_steps}",
            f"p{self.pop}",
            f"v{self.volume:g}",
            f"k{','.join(f'{k}{v:.12g}' for k, v in sorted(self.rates.items()))}",
            f"c{self.chain_fraction:g}",
            f"x{self.decay_fraction:g}",
            f"seed{self.seed}",
        ]
        return "_".join(parts)


def to_bngl(spec: ModelSpec) -> str:
    """Render `spec` as BNGL model text (no actions block).

    The returned text is a pure function of `spec`, which the harness relies on:
    two worker processes given the same spec must see the same network, and the
    harness compares digests to prove it.
    """
    if spec.species < 1:
        raise ValueError(f"species must be >= 1, got {spec.species}")
    if spec.reactions < 1:
        raise ValueError(f"reactions must be >= 1, got {spec.reactions}")
    if not 0.0 <= spec.chain_fraction <= 1.0:
        raise ValueError(f"chain_fraction out of range: {spec.chain_fraction}")
    if not 0.0 <= spec.decay_fraction <= 1.0:
        raise ValueError(f"decay_fraction out of range: {spec.decay_fraction}")

    n_chain = int(round(spec.reactions * spec.chain_fraction))
    if n_chain > 0 and spec.species < 2:
        raise ValueError(
            f"a chain reaction needs at least 2 distinct species to move "
            f"molecules between, got {spec.species}; set chain_fraction=0 "
            f"for a single-species network"
        )
    n_decay = int(round(spec.reactions * spec.decay_fraction))
    n_assoc = spec.reactions - n_chain - n_decay
    if n_assoc < 0:
        # Rounding overshoot: shrink decay then chain until the mix fits.
        overflow = -n_assoc
        take = min(overflow, n_decay)
        n_decay -= take
        overflow -= take
        n_chain -= min(overflow, n_chain)
        n_assoc = 0

    names = [f"S{i}" for i in range(spec.species)]
    lines: list[str] = [
        f"# Synthetic network: {spec.key()}",
        "begin model",
        "begin parameters",
        f"    k_chain  {spec.rates['chain']:.12g}",
        f"    k_assoc  {spec.rates['assoc']:.12g}",
        f"    k_decay  {spec.rates['decay']:.12g}",
        f"    vol      {spec.volume:.12g}",
        "end parameters",
        "begin compartments",
        "    C vol",
        "end compartments",
        "begin molecule types",
    ]
    lines += [f"    {n}()" for n in names]
    lines += ["end molecule types", "begin seed species"]
    lines += [f"    {n}()  {spec.pop}" for n in names]
    lines += ["end seed species", "begin observables"]
    # One observable per species keeps the statistical comparison well posed:
    # comparing observable g across two runs compares the same functional.
    lines += [f"    Molecules  Obs_{n}  {n}()" for n in names]
    lines += ["end observables", "begin reaction rules"]

    # Chain steps: a ring, so every species is reachable and no rule is
    # degenerate. Modulo arithmetic keeps the count exact for any species count.
    for i in range(n_chain):
        a = names[i % spec.species]
        b = names[(i + 1) % spec.species]
        if a == b:
            a, b = names[i % spec.species], names[(i + 1 + 1) % spec.species]
        lines.append(f"    {a}() -> {b}()  k_chain")

    # Associations: distinct species pairs, homogeneous pairs excluded so the
    # mass-action propensity is a clean k*n*(n-1) rather than a dimerisation.
    for i in range(n_assoc):
        a = names[i % spec.species]
        b = names[(i + spec.species // 2 + 1 + i // spec.species) % spec.species]
        if a == b:
            b = names[(i + 1) % spec.species]
            if b == a:
                b = names[(i + 2) % spec.species]
        lines.append(f"    {a}() + {b}() -> {a}()  k_assoc")

    # Decays.
    for i in range(n_decay):
        lines.append(f"    {names[i % spec.species]}() -> 0  k_decay")

    lines += ["end reaction rules", "end model", ""]
    return "\n".join(lines)


def write_spec(spec: ModelSpec, directory: str | None = None) -> str:
    """Materialise `spec` to a `.bngl` file and return its path.

    Uses a content-derived name, so writing the same spec twice yields the same
    path and the harness can cache aggressively without risking a stale file
    being picked up under a new spec's key.
    """
    directory = directory or tempfile.gettempdir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{spec.key()}.bngl")
    text = to_bngl(spec)
    # Always rewrite: an interrupted earlier run may have left a partial file.
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


# --------------------------------------------------------------------------
# Event-density calibration
# --------------------------------------------------------------------------


@dataclass
class CalibrationResult:
    """What the density search achieved, as distinct from what it requested."""

    spec: ModelSpec
    target_density: float
    achieved_density: float
    probe_events: int
    probe_batch: int
    iterations: int
    converged: bool
    path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_density": self.target_density,
            "achieved_density": self.achieved_density,
            "probe_events": self.probe_events,
            "probe_batch": self.probe_batch,
            "iterations": self.iterations,
            "converged": self.converged,
            "path": self.path,
            "spec_key": self.spec.key(),
        }


def calibrate_event_density(
    spec: ModelSpec,
    probe_batch: int = 128,
    iterations: int = 6,
    tolerance: float = 0.15,
    directory: str | None = None,
    threads: int = 2,
) -> CalibrationResult:
    """Rescale `spec`'s rates so a trajectory fires about `event_density` events.

    Mean SSA event count is *almost* linear in the rate constants for small
    populations but not exactly, because the population distribution shifts as
    rates change. The search therefore uses the standard multiplicative update
    `factor *= target / measured` and stops when the measured density is within
    `tolerance` (relative) of the target. It reports the achieved density, and
    `converged=False` is a normal outcome for a target the network cannot reach
    (e.g. asking for fewer events than the initial population's decay floor).

    Requires an importable engine module; the probe is a real CPU batch, not an
    estimate, so the reported density is measured rather than modelled.
    """
    from . import engine_import  # local import: keeps this module pure BNGL

    cpp = engine_import.load_engine()
    target = float(spec.event_density)
    current = spec
    achieved = 0.0
    probe_events = 0
    used = 0

    if target <= 0.0:
        path = write_spec(current, directory)
        return CalibrationResult(current, target, 0.0, 0, 0, 0, True, path)

    for used in range(1, max(1, iterations) + 1):
        path = write_spec(current, directory)
        model = cpp.parse_file(path)
        network = cpp.generate_network(model)
        metrics = cpp.simulate_batch_ssa_cpu(
            model,
            network,
            batch_size=probe_batch,
            t_end=current.t_end,
            n_steps=current.n_steps,
            threads=threads,
            base_seed=current.seed,
        )
        probe_events = int(metrics["total_events"])
        achieved = probe_events / float(probe_batch)
        if achieved <= 0.0:
            # No events at all: rates are far too low to be observable.
            current = current.scaled(10.0)
            continue
        rel = abs(achieved - target) / target
        if rel <= tolerance:
            break
        # Damped update: a full correction over-corrects when the density
        # response is superlinear, and oscillates without the damping.
        correction = target / achieved
        current = current.scaled(min(4.0, max(0.25, correction**0.85)))

    path = write_spec(current, directory)
    rel = abs(achieved - target) / target if target > 0 else 0.0
    return CalibrationResult(
        spec=current,
        target_density=target,
        achieved_density=achieved,
        probe_events=probe_events,
        probe_batch=probe_batch,
        iterations=used,
        converged=rel <= tolerance,
        path=path,
    )


# --------------------------------------------------------------------------
# Named shapes
# --------------------------------------------------------------------------


def shape_grid(
    reactions: tuple[int, ...] = (2, 4, 16, 64, 256, 1024),
    event_density: float = 200.0,
    species: int = 16,
    t_end: float = 1.0,
) -> list[ModelSpec]:
    """A ladder of networks that crosses the accelerator's plausible crossover.

    Reaction count is the axis on which a device lane stops being starved of
    work; event density is the axis on which the host pool stops being cheap.
    The two shipped fixtures sit at the (2, 130) and (4, 9) corners of this
    plane, which is why they cannot separate the two effects.
    """
    out = []
    for r in reactions:
        # Keep the species pool at or above the reaction count so the network
        # stays non-degenerate; association rules need distinct pairs.
        s = max(species, min(r, 64))
        out.append(
            ModelSpec(
                name=f"synth_r{r}_d{int(event_density)}",
                species=s,
                reactions=r,
                event_density=event_density,
                t_end=t_end,
                n_steps=10,
                pop=max(20, min(200, event_density // 4)),
            )
        )
    return out


def shape_models(
    reactions: int, event_density: float, species: int = 16, t_end: float = 1.0
) -> ModelSpec:
    """Convenience constructor for one calibrated synthetic network."""
    s = max(species, min(reactions, 64))
    return ModelSpec(
        name=f"synth_r{reactions}_d{int(event_density)}",
        species=s,
        reactions=reactions,
        event_density=event_density,
        t_end=t_end,
        n_steps=10,
        pop=max(20, min(200, event_density // 4)),
    )


def expected_reaction_range(spec: ModelSpec) -> tuple[int, int]:
    """Bounds on the network reaction count the spec can produce.

    Exact, not estimated: every emitted rule is distinct by construction, and
    BNGL's network generation preserves one reaction per distinct rule.
    """
    return (spec.reactions, spec.reactions)


def describe(spec: ModelSpec) -> str:
    """One-line human description for report headers."""
    return (
        f"{spec.name} [S={spec.species} R={spec.reactions} "
        f"t_end={spec.t_end:g} pop={spec.pop} vol={spec.volume:g} "
        f"chain={spec.rates['chain']:.4g} assoc={spec.rates['assoc']:.4g} "
        f"decay={spec.rates['decay']:.4g}]"
    )


def bn_summary(net: Any) -> str:
    """Format a generated network's species/reaction counts."""
    return f"S={net.num_species} R={net.num_reactions}"


def reaction_share(spec: ModelSpec) -> dict[str, float]:
    """Fraction of reactions in each channel, for the report."""
    total = float(spec.reactions)
    n_chain = int(round(spec.reactions * spec.chain_fraction))
    n_decay = int(round(spec.reactions * spec.decay_fraction))
    n_assoc = max(0, spec.reactions - n_chain - n_decay)
    return {
        "chain": n_chain / total,
        "assoc": n_assoc / total,
        "decay": n_decay / total,
    }


def density_for(t_end: float, target: float) -> float:
    """Scale factor helper: what rate multiplier roughly yields `target` events."""
    return math.sqrt(max(target, 1.0) / max(t_end, 1e-9))