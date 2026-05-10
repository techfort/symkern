# Capability Library Direction

## Why This Direction Exists

Symkern now has the beginnings of reusable compiled slices and machine-level abstractions. If it continues to generate backends, rewrite patterns, and optimized slices, it needs a structured way to remember what was generated, why it exists, and when it should be reused.

This direction turns isolated generated artifacts into a managed capability library.

## Core Idea

Symkern should evolve toward a machine-indexed registry of reusable capabilities.

A capability is not just a code snippet. A capability is a reusable execution or optimization unit with:

- a machine identity
- a slice signature
- preconditions and output contract
- backend realizations
- empirical performance history
- provenance from the runs that produced it
- a measured notion of where it is effective

## What Counts As A Capability

Examples:

- an invented abstraction over a stable opcode pattern
- a compiled backend for a numeric slice
- a ranking backend for structured candidate selection
- a rewrite that consistently improves cost or quality for a known plan shape
- a retrieval rule that maps a plan slice to an already-proven backend target

## Required Architecture

This direction needs three layers.

### 1. Artifact Storage

This is the physical layer:

- generated source files
- compiled binaries
- machine artifacts
- benchmark outputs
- rewrite templates

### 2. Capability Registry

This is the index layer. Each capability entry should record:

- `capability_id`
- `kind`
- `slice_signature`
- `input_contract`
- `output_contract`
- `constraints_satisfied`
- `backend_targets`
- `artifact_paths`
- `provenance_runs`
- `fitness_history`
- `selection_history`
- `retirement_state`

### 3. Selection And Learning

This is the optimizer layer:

- retrieve candidate capabilities for a current slice
- compare estimated fit and cost
- select or reject a capability
- execute and measure outcome
- update the capability's confidence and fitness record

## Guardrails To Prevent Directional Conflict

This direction must not conflict with other Symkern goals.

### Guardrail A: Registry, Not Snippet Dump

Generated artifacts must never be treated as anonymous files. If something is worth keeping, it must have machine-readable metadata and a capability identity.

### Guardrail B: Planner Stays In Charge

Capabilities do not replace planning. They are candidate realizations of plan slices selected by the planner.

### Guardrail C: Explanation Stays Downstream

Periscope can explain capabilities and reuse decisions, but it must not become the source of truth for retrieval metadata.

### Guardrail D: Benchmarking Must Feed Learning

Benchmark results should update capability fitness history. Otherwise the system accumulates artifacts without learning when they are actually better.

### Guardrail E: Promotion Must Be Earned

New generated capabilities should begin in an experimental state. Promotion to trusted reuse should require repeated success.

## Compatibility With Other Directions

This direction should compose with:

- backend optimization:
  the registry stores candidate compiled realizations and their measured costs

- richer planning:
  the planner can consider capability reuse as one of several plan transformations

- mixed execution:
  different slices of one plan can reuse different stored capabilities

- evaluation:
  multi-step benchmarks become training signals for capability promotion and retirement

## Near-Term Implementation Path

1. Add a registry file or store for generated backends and invented abstractions.
2. Persist a machine-readable entry whenever Symkern emits a backend artifact worth reusing.
3. Record benchmark and run outcomes against that entry.
4. Make backend selection consult the registry instead of only hardcoded rules.
5. Add promotion, demotion, and retirement states for capabilities.

## Success Criteria

This direction is working when Symkern can:

- recognize that a new slice matches a previously generated capability
- justify why that capability is a good fit
- choose it because measured history supports the decision
- preserve the provenance of that decision in the run artifact
- retire or replace weak capabilities instead of accumulating noise

## Failure Mode To Avoid

The main failure mode is uncontrolled growth: too many generated artifacts, weak retrieval, conflicting variants, and no reliable notion of which reuse decisions actually help.

If that happens, the library becomes baggage rather than self-improvement.
