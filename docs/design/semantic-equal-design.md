# Exact model equality — D04 / #156

Audit: BNG3 `918a5fb1`. This is a design for review, not an implemented algorithm or a proof of the production implementation. Current `python/bionetgen/bngir.py:3070` compares serialized dictionaries. Its own docstring says it does not test mathematical equivalence. Renaming, rule reordering and splitting therefore require a replacement.

## Definition

For ordinary discrete, memoryless BNGL kinetics, let a model define a reachable mixture state space S, initial law μ, transition generator Q, observable map O, function interpretations F and protocol P. Models a and b are equal when one consistent bijection of molecule types, sites and state labels induces a state bijection φ such that:

- φ pushes μa to μb;
- for distinct states x,y, Qa(x,y) = Qb(φx,φy), aggregating every rule and embedding with that destination;
- Oa(x)=Ob(φx), and function interpretations agree after the same renaming;
- protocols have the same ordered interventions, guards, timing, output semantics and initial/reset behavior under φ.

Initial distributions, units and externally bound parameter values are part of the input. Equality of parameterized models quantifies over the declared common parameter domain; equality after binding parameters compares those bindings. These are two explicit input modes, not two weaker equivalence relations. Unreachable mixtures do not affect equality of the initialized process, but total user-callable functions remain part of F as requested. Do not turn a difference on an unreachable mixture into a counterexample to process equality.

Self-loop reaction firings do not change the ordinary state-process generator. If reaction-count output, tagged events or protocol behavior observes those firings, extend the state with that information before comparison. Likewise, equal ODE vector fields alone do not imply equal jump processes: `A→B` at 2k and `2A→2B` with a tuned drift have different jump laws.

**Necessary correction to the CTMC premise:** a deterministic delayed rule is not a homogeneous CTMC on molecular mixtures. Time-dependent hazards, timed interventions, continuous variables and algebraic/delay equations also require richer semantics. Preserve the requested exact process equality by defining equality of the full initialized path law and observable/protocol interpretation. Include time, pending completions, history, continuous state and algebraic constraints as required. Do not relabel a mixture-only CTMC comparison as covering these features. This is a mathematical clarification for review, not a feature exclusion.

## Exact result contract

The implementation will return `True` only with a verified equivalence certificate and `False` only with a verified inequivalence certificate. A boolean-facing `semantic_equal` will raise `EqualityUndecided` when proof search does not decide the case; an accompanying diagnostic will identify obligations and preserve the proof search state. No timeout is False. No sampling result is True. The logical relation stays exact.

A terminating, complete boolean algorithm for every requested expression/process feature cannot be promised. The release will implement the decision procedures below, exact proof/counterexample methods for the other cases, and explicit unresolved outcomes. Review this API consequence together with the maintainer's request to document undecidable features.

## 1. Finite generated network

A finite reaction network can still have infinitely many count states (e.g. `0→A`). Distinguish a finite species/reaction set from a finite reachable CTMC.

1. Obtain a complete finite network plus a completion certificate, not a network truncated by a maximum size/iteration limit. Compare against pinned BNG2 independently.
2. Enumerate type/site/state renamings consistent with signatures and species graphs. Canonical graph labels prune candidates; independent isomorphism verification checks the candidate mapping.
3. Normalize each jump vector and sum all hazards yielding that vector. For mass action, use exact rational coefficients in a falling-factorial polynomial basis, with the source convention's automorphism factors included. Do not require one-to-one reaction-list correspondence: split rules and different reaction expressions can define the same generator.
4. Compare initial state, observable and function expressions, units and protocols under the candidate map.
5. If the reachable state space has a proved finite bound, enumerate it to a fixed point and compare exact transition tables. A finite-state fixed point provides completeness for this branch. Without such a bound, comparing symbolic hazards on all count states is a sound stronger certificate. Failure of that stronger certificate is not proof of inequality on reachable states; seek an actual reachable counterexample or invariant proof.

**Termination/exactness argument.** Finite bounded reachable-state enumeration terminates because each state is visited once; finite renaming enumeration terminates. Rational/polynomial normalization terminates by a fixed monomial ordering and exact arithmetic. For unconstrained count lattices, polynomial identity is decidable by coefficient comparison. For reachable-state restrictions, a supplied complete finite reachability certificate or an independently checked invariant argument is required. Do not infer completeness merely from network generation finishing.

## 2. No finite network: common rule refinement

Represent a rule as typed precondition graph, embedding predicate, graph edit, per-embedding hazard and observation effects. For each renaming candidate, form common refinements of overlapping preconditions from both models; partition embeddings by their finite local context, equality/disequality constraints, and predicates. Prove that each partition is disjoint and exhaustive and carry exact embedding/automorphism multiplicities. Group refinements with the same instantiated edit and sum their hazards.

For fixed finite signatures and strictly local finite-pattern tests/edits whose distinguishing context has a proven finite bound, there are finitely many typed overlap partitions. Enumerate them, verify their partition certificate and normalize rates. A complete certificate proves generator equality for every finite host mixture, and hence the initialized process, subject to common well-posedness/explosion semantics. Creation does not itself make overlap enumeration infinite when its created graph and tests are finite. Whole-connected-component effects, unbounded connectivity predicates and local functions over unbounded complexes need additional arguments; do not assume a finite context bound.

Neutral rule refinement in Kappa supplies a basis for the multiplicity-preserving transformation, not a universal terminating decision algorithm for BNGL. Danos et al. explicitly discuss potentially infinite ground expansion. The proposed BNGL refinement checker must prove its own treatment of each BNGL predicate, edit and rate feature. [Rule-based modelling, symmetries, refinements](https://fontana.hms.harvard.edu/sites/fontana.hms.harvard.edu/files/documents/FMSB_08.pdf).

When finite refinement cannot be certified, enumerate candidate proof certificates and finite reachable counterexample traces in parallel. A valid proof settles equality; a validated trace/rate discrepancy settles inequality. Neither search is guaranteed to terminate for all models. Preserve these exact methods rather than substitute observables-only equality.

## 3. Feature algorithms and proof obligations

| Feature | Exact method to implement | Termination and correctness argument / limit |
|---|---|---|
| Renaming, rule order, site order, bond IDs | Enumerate finite signature bijections; canonicalize typed graphs; compare certificates | Finite syntax gives finite permutations. Bond IDs are binders; verify connectivity rather than numeric labels. |
| Symmetry / automorphisms | Count injective embeddings modulo the exact source stabilizer; carry rational coefficients through refinement | Finite-pattern automorphism enumeration terminates. Validate against hand-enumerated small graphs and BNG2; no division-by-factorial heuristic. |
| Split/merged rules | Group by normalized target edit/jump and sum hazards on every disjoint refinement cell | Finite certified refinement and decidable coefficient domain terminate; preserves the generator by additivity. |
| Functional rates | Inline acyclic function definitions with capture-avoiding bindings; compare exact normalized expressions with domain obligations | Rational expressions are compared after cross multiplication plus equal definedness domains. Polynomial/semialgebraic guards admit real-algebraic decision procedures. General elementary identity is not decidable in all cases. |
| Local functions / DOR | Include molecule/species scope, embedding-dependent counts, traversal and selected reactant bindings in refinement | Finite local context permits a finite partition. Functions inspecting unbounded connected components require a proven invariant or certificate; a finite completeness proof is not presently established for full BNGL. |
| Time / TFUN | Normalize exact knots, interpolation, endpoints, extrapolation and file contents; split finite time domains at breakpoints | Finite tables with rational data and piecewise polynomial laws decide algebraically. Arbitrary time expressions inherit symbolic limits; paths and file names are not semantic values. |
| Compartments / volume scaling | Include hierarchy, dimensionality, location, volumes and conversion factors in state and rate normalization | Static finite compartment structures with rational/algebraic factors terminate. Dynamic volumes require equality of the coupled continuous dynamics, not just initial-volume substitution. |
| Energy patterns | Refine energy-count changes caused by each edit; compare the resulting forward/reverse hazards | Finite local energy deltas permit finite exact comparison. Equal symbolic exponent arguments are sufficient certificates; no unproved assumption that a CAS decides all exponential identities. |
| Barrier patterns | Include transition-context barrier matching and multiplicities in hazard derivation | Finite context and decidable expressions terminate; compare rates, not only equilibrium ratios. A common barrier shift can preserve equilibrium but change dynamics. |
| Driven reservoirs | Include reservoir work, stoichiometric exchange and protocol-dependent driving in hazards | Fixed symbolic affinities use expression certificates. Equal steady-state distributions alone do not prove equal currents or path laws. |
| Delayed consuming rules | Compare initiation transitions, reactant reservation, delay laws, queue ordering and completion transitions on augmented state | Finite-state augmented queues or a verified bisimulation certificate can decide the case. Deterministic delays introduce real clocks; arbitrary history-dependent delays have no general complete terminating method provided here. |
| NonConsuming delays | Compare initiation propensity, availability checks, completion consumption/production, cancellation and history | Check against the specified delay convention independently. Matching delay text alone is insufficient. Same exact-method limits as consuming delays. |
| Population maps / hybrid | Compare particle/population representation with a verified state correspondence, embedding multiplicities, conversion transitions and observables | A bijective representation change is equality. Many-to-one aggregation requires a proof that it represents the same declared state process; lumpability alone changes the state space and must not silently replace this definition. |
| Include/exclude, MatchOnce, DeleteMolecules, MoveConnected, TotalRate | Treat predicates and edit footprints as first-class refinement conditions; sum normalized total rather than per-match rates where required | Finite predicates terminate after finite partitions. Connected deletion/movement require whole-component semantics and a certificate for unbounded contexts. |
| Initial state / fixed species / constraints | Compare initial law, fixed flags and admissible-state invariants alongside transitions | Finite explicit initial data decide; arbitrary symbolic initial laws inherit expression limits. |
| Observables | Compare pattern-count functions and thresholds under state renaming, including Molecules versus Species and local scopes | Finite graphs/count polynomials decide on finite states; symbolic pattern count identity requires complete refinement certificates. |
| Protocols and SBML events | Compare guard, root, priority, persistence, trigger-time values, simultaneous assignments and queue transitions | Finite-state protocol automata decide by finite transition comparison; arbitrary hybrid systems require proof certificates. |
| Rate/algebraic rules, fast reactions | Compare exact vector fields, algebraic solution branches, consistent initialization and resulting path laws | Polynomial vector-field identity is decidable; general solution/flow equivalence is not established by syntactic matching. Singular algebraic models must first have defined source semantics. |
| Units / metadata / exports | Normalize unit dimensions and exact scale factors; include only metadata that changes execution or user-observed protocol | Finite dimensional algebra terminates. Preserve all metadata in lossless BNGIR separately; byte-for-byte metadata equality is not process equality. |

## 4. Why unrestricted termination is unavailable

The scalar identity problem already creates an obstruction. Richardson proved undecidability for an elementary expression class with rational constants, π, log(2), addition, multiplication, composition, sine, exponential and absolute value. BNGL exposes corresponding real-expression operations, but applying the theorem to a particular input domain requires checking that domain: it is not automatically a theorem about expressions evaluated only at integer molecule counts. Time-dependent functions range over real time and create the relevant concern. We will document expression-domain assumptions explicitly. [Richardson, original paper](https://www.math.tecnico.ulisboa.pt/~lgodin/Seminario/richardson.pdf).

A fixed terminating rewrite system decides equality of its normal forms only when completeness for the admitted expression theory is proved. Otherwise identical forms are a sound positive certificate; different forms mean unresolved, not unequal. Floating-point sampling is useful for finding candidate counterexamples, which must then be certified exactly or with rigorous intervals.

The general refinement proposal also needs separate reachability, connectivity and history proofs. This design does not claim an undecidability theorem for every BNGL sublanguage without a reduction. Where no complete procedure is established, its status is an unproved completeness obligation. Implement the exact certificate machinery and the proven decidable cases, and expose that distinction in diagnostics.

## 5. Independent test catalogue

Each family below receives an equal pair and a differing pair. Tests are authored in the independent framework; product implementation agents cannot change answers/tolerances.

| Case ID | Known equal | Known different / decisive witness |
|---|---|---|
| EQ-rename | Consistent type/site/state renaming, arbitrary bond labels | Change one bound site or initial state |
| EQ-order | Reorder declarations/rules and independent pattern terms | Reorder two noncommuting protocol setters |
| EQ-split | `A→B` rate k versus duplicate channels k/3 and 2k/3 | Sum rates to 4k/3 |
| EQ-refine | Wildcard internal state rule versus exhaustive U/P partition | Omit P, with initial P witness |
| EQ-symmetry | Symmetric dimer and its certified embedding partition | Remove 1/2 factor; inspect dimer propensity at n=2 |
| EQ-functions | Rational identity with identical pole domain | Cancel x/x to 1 when x=0 remains admissible |
| EQ-local | Renamed local observable with identical molecule scope | Change species scope to molecule scope in a multimer |
| EQ-time | Same piecewise-linear TFUN with redundant collinear knot | Change knot endpoint or extrapolation |
| EQ-volume | Units and rate rescaled consistently | Double-apply volume to a bimolecular propensity |
| EQ-energy | Energy syntax rearranged with equal exact transition deltas | Equal equilibrium ratio but all rates doubled |
| EQ-barrier | Equivalent barrier partitions | Shift barrier on one channel and compare exact hazard |
| EQ-reservoir | Opposite reaction orientation with work sign reversed | Reverse reaction without reversing reservoir work |
| EQ-delay | Rename a consuming delayed model including queue variables | Same initiation, different completion delay |
| EQ-nonconsuming | Equivalent NonConsuming queue descriptions | Consuming versus nonconsuming with intervening depletion |
| EQ-population | Certified bijective particle/count encoding | Drop conversion multiplicity for two indistinguishable particles |
| EQ-modifiers | Equivalent exhaustive include/exclude partition | DeleteMolecules versus whole-species deletion in a trimer |
| EQ-observables | Same pattern sum after renaming | Molecules versus Species observable on a dimer |
| EQ-events | Equivalent event guards/assignments and priority ordering | Trigger-time versus execution-time assignment value |
| EQ-infinite | Local polymer rule and certified finite refinement | Change terminal growth propensity on a reachable chain |
| EQ-reachability | Add a rule enabled only by an unreachable species | Seed that species and obtain a rate witness |
| EQ-noop | Add unobserved self-loop channels | Enable reaction-count output observing those channels |
| EQ-unknown | Symbolic identity without an available proof certificate | Must raise EqualityUndecided, never return False |
| EQ-serialization | Same model across BNGIR 0.1/0.2 and BNGL | Lose unit, delayed modifier or observable kind |

For finite examples, a separate brute-force rational transition enumerator supplies the answer, cross-checked with hand derivations and canonical source behavior. For refinement examples, a separately checked partition/embedding certificate supplies the answer. Stochastic distribution tests detect implementation errors but never serve as proof of equality. Add adversarial invalid-certificate tests and known mutations in symmetry, volume, delay, priority and scope. No observables-only substitute is proposed.
