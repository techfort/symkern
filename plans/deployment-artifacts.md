# Deployment Artifact Direction

## Why This Direction Exists

Symkern is becoming capable of local translation, planning, optimization, backend selection, skill reuse, and skill evolution. That is powerful, but it also means the full Symkern runtime is broader and more stateful than many secure production environments should allow.

For high-assurance deployments, the safer model is often:

- run full Symkern in a trusted local or staging environment
- synthesize and optimize there
- emit a reduced deployment artifact
- deploy that reduced artifact into a narrower runtime envelope

This direction exists to formalize that split.

## Core Idea

Symkern should eventually distinguish between two classes of machine output.

### 1. Rich Development Artifacts

These are for synthesis, replay, analysis, learning, and improvement.

They may include:

- machine code
- symbol tables
- trace data
- benchmark evidence
- skill references
- backend candidates
- invention metadata
- Periscope explanations

### 2. Reduced Deployment Artifacts

These are for secure operation.

They should include only what is needed to execute the approved task:

- the selected executable realization
- required adapter bindings
- minimal configuration
- declared resource envelope
- optional signature or promotion metadata

They should omit unnecessary synthesis and learning machinery.

## Security Motivation

The full Symkern runtime is a programmable machine substrate. That is appropriate in trusted environments, but it is a wider attack surface than many production targets should accept.

Reduced deployment artifacts shrink that surface by removing:

- open-ended prompt translation
- broad planning capability
- unrestricted skill evolution
- unnecessary local machine memory
- debugging and analysis metadata that is only useful in development

This does not eliminate the need for sandboxing or policy, but it does reduce what must be defended.

## What A Deployment Artifact Should Declare

Each deployment artifact should eventually carry a machine-readable manifest describing:

- artifact identity
- source run or promotion lineage
- selected runtime target
- required adapters
- required secrets or credentials class
- network egress requirements
- filesystem requirements
- CPU and memory envelope
- timeout envelope
- whether the artifact is mutable or immutable at runtime

This makes secure deployment an explicit machine concern rather than an ad hoc operational guess.

## Runtime Targets

This direction should not assume only one production target.

Possible targets:

- minimal container runtime
- static process bundle
- WASM-like constrained target
- unikernel-friendly target for very narrow, stripped-down execution surfaces

The interesting point is not that every Symkern output must become a unikernel artifact. The point is that the architecture should allow outputs to be reduced far enough that such deployment classes become realistic.

## Trusted Synthesis vs Operational Execution

The strongest model for secure environments is:

- full Symkern in trusted local, build, or staging environments
- reduced deployment artifact in operational environments

That means:

- skills evolve in the trusted zone
- prompts are translated in the trusted zone unless explicitly allowed otherwise
- optimization and benchmarking happen in the trusted zone
- only promoted, reduced artifacts are pushed into narrow production runtimes

This treats Symkern more like a machine-native program foundry than a permanently exposed autonomous runtime.

## Compatibility With Existing Directions

This direction composes with:

- [capability-library.md](/home/joe/10h/symkern/plans/capability-library.md):
  capabilities and skills can influence which executable realization is exported into a deployment artifact

- [skill-trust-model.md](/home/joe/10h/symkern/plans/skill-trust-model.md):
  trust and promotion can determine which generated realizations are eligible for deployment

- backend optimization:
  the selected backend may become the concrete deployed realization

- secure production policy:
  deployment artifacts make it easier to expose only approved resource envelopes in production

## Guardrails

### Guardrail A: Rich And Reduced Artifacts Must Stay Distinct

Development artifacts and deployment artifacts serve different purposes. They should not collapse into one ambiguous format.

### Guardrail B: Deployment Artifacts Must Not Quietly Reinflate

If a reduced artifact can dynamically reacquire planning, broad translation, or unrestricted learning capabilities in production, then the security benefit is mostly lost.

### Guardrail C: Resource Needs Must Be Explicit

A deployment artifact should declare what resources it expects. Secure operation should not depend on ambient runtime discovery.

### Guardrail D: Promotion Must Precede Export

Only approved realizations should become deployment artifacts. Experimental machine products should remain in the trusted synthesis environment.

## Near-Term Implementation Path

1. Define a distinct deployment-artifact manifest format.
2. Decide what metadata is removable versus required for secure execution.
3. Add an export step that reduces a rich run artifact into a deployment artifact.
4. Add adapter and resource-envelope declarations to the exported manifest.
5. Introduce signed or promoted export states for deployment eligibility.

## Success Criteria

This direction is working when Symkern can:

- synthesize and optimize in a trusted environment
- emit a reduced artifact that is smaller and narrower than the development artifact
- declare the runtime envelope required by that artifact
- deploy that artifact into a constrained environment without carrying the full Symkern runtime with it

## Failure Mode To Avoid

The main failure mode is false reduction: an artifact that appears stripped down but still depends on ambient planning, hidden mutable state, or broad runtime privileges.

If that happens, the deployment model looks safer than it actually is.