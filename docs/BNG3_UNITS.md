# BNG3 physical units and dimensional analysis

BNG3 supports physical-unit annotations as model metadata and checks their
dimensional consistency during semantic compilation. The feature is designed
around the SBML Core unit model: a unit has a physical dimension, a scale/factor
and a reusable name. SBML-Multi uses exactly the same Core unit attributes and
definitions; it does not introduce a Multi-specific unit vocabulary.

## Syntax

The normative BNGL spelling is an explicit trailing annotation:

```text
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin units
    timeUnits = second
    substanceUnits = item
    volumeUnits = fL
    unit per_s = second^-1
  end units

  begin parameters
    KD = 100 [nM]
    koff = 0.02 [per_s]
    kon = koff / KD
  end parameters

  begin compartments
    cell 3 1 [fL]
  end compartments

  begin seed species
    A()@cell 1 [M]
  end seed species
end model
```

Annotations are interpreted only in parameter, compartment and seed-species
declaration contexts. Names such as `s`, `M`, `L`, `nM`, and `item` therefore
remain ordinary BNGL identifiers everywhere else. Unit declarations are
normalized at the parser front door into model metadata, so the checked-in
ANTLR grammar does not acquire globally reserved lexer tokens. The BNG3 writer
emits the same `begin units` block and bracket annotations, preserving a
parse/write/parse round trip.

The initial vocabulary includes SBML-compatible `mole`, `item`, `metre`,
`litre`, `second`, metric length/volume prefixes, and molar prefixes (`M`,
`mM`, `uM`, `nM`, and `pM`). Compound expressions support multiplication,
division, parenthesized products and signed integer powers. User definitions
use `unit name = expression`.

`units="off"` preserves legacy behavior and rejects physical annotations.
`units="permissive"` enables inference while retaining unknown dynamic
quantities as unknown. `units="strict"` rejects incomplete or unsupported
inference. If a model has unit metadata but no explicit mode, BNG3 uses
permissive analysis; an otherwise unannotated model remains unit-free.

## Semantic and execution contract

The compiler tracks substance, length and time dimensions, retains the
mole/item base identity, and carries numeric factors separately from the
dimension. It infers units through parameter dependencies and checks
addition/subtraction/comparison compatibility, power exponents, dimensionless
math functions, function branch arguments, compartment volume dimensions,
seed quantities and elementary mass-action rate molecularity.

The compiler does not silently turn a concentration into a count. Converting a
concentration seed to a network count requires a declared three-dimensional
compartment volume and a positive `NumberPerQuantityUnit` bridge. Converting an
elementary rate constant likewise uses the reaction molecularity and the
reaction compartment. These contexts are applied when lowering the native
network, and the ODE/PLA/PSA paths consume the resulting ordinary numeric
network. `NumberPerQuantityUnit` is consumed by the explicit conversion layer;
it is not multiplied again by the legacy compartment scaling path.

Mole/item conversion fails closed without an explicit bridge. This is
intentional: dimension equality alone does not establish a numerical mapping
between a chemical amount and a molecule count. Unsupported arbitrary or
nonlinear rate-law conversions remain unlowered rather than being assigned a
mass-action factor by guesswork.

The current backend capability boundary is explicit:

* native network, ODE, PLA and PSA lowering supports the validated
  concentration/count and elementary-rate paths;
* the direct NFsim adapter reports physical units as unsupported until its
  count-rate bridge is independently integrated and validated;
* unknown functions, dynamic seed quantities, missing compartment context and
  unsupported imported unit terms are diagnostics or hard failures, not
  implicit dimensionless values.

## SBML Core and SBML-Multi mapping

The shared `bng::io::sbml_units` emitter maps model defaults to SBML Core
`timeUnits`, `substanceUnits`, `volumeUnits`, `areaUnits`, `lengthUnits` and
`extentUnits`, emits valid `UnitDefinition` entries with explicit `kind`,
`exponent`, `multiplier` and `scale`, and attaches `units` to parameters,
compartments and seed species. A concentration seed is written as
`initialConcentration` with `hasOnlySubstanceUnits="false"`; an amount seed is
written as `initialAmount` with `hasOnlySubstanceUnits="true"`. Generated
count-based networks explicitly use SBML `item` units.

The Core and Multi writers call this same emitter. Multi-specific elements
continue to describe molecular components, states and binding sites; no
`multi:units` attribute or alternate unit conversion is emitted. The reader
imports Core unit definitions, defaults and object-level unit references before
reconstructing the executable model. Unsupported base kinds and malformed
multiplier/scale/exponent data fail closed.

Unit-free SBML continues to emit the historical `substance` item definition and
does not acquire unit annotations. Legacy `substanceUnits(Number|Concentration)`
and `NumberPerQuantityUnit` remain accepted compatibility metadata; they are
not reinterpreted as a new global unit syntax.

## Design decision and review outcome

The implementation deliberately keeps unit syntax out of the global BNGL
identifier grammar, keeps units in the typed AST/compiled metadata rather than
in runtime matcher objects, and makes context-dependent conversions explicit.
The critical review rejected three tempting shortcuts: treating every
substance dimension as interchangeable, caching one rate conversion for all
reaction orders/compartments, and emitting a separate SBML-Multi unit system.
Those shortcuts would either change legacy numerical behavior or produce SBML
documents whose Core semantics disagree with BNG3 execution. The remaining
unsupported boundaries are recorded above and covered by capability diagnostics
and regression tests.
