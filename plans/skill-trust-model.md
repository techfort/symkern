# Skill Trust Model Direction

## Why This Direction Exists

Symkern now has the first real local skill loop:

- local skill accumulation
- promotion from experimental to trusted
- reference-counted retirement
- reuse of trusted abstraction skills during synthesis

That is enough for the current stage, but the current trust model is still too coarse. A skill becomes `trusted` mainly through repeated successful use. That is a useful starting heuristic, but it merges too many questions into one state.

A skill can be:

- correct but slow
- fast but brittle
- compressive but hard to generalize
- stable for one prompt family but weak outside it

The next step should therefore be a richer trust model for skills.

## Core Idea

Symkern should evolve from a single promotion counter toward a multi-dimensional trust profile per skill.

Instead of asking only:

- is this skill trusted?

Symkern should eventually ask:

- how correct is this skill?
- how performant is this skill?
- how often does this skill improve compression or plan quality?
- how stable is this skill across related slices?
- how specific or general is this skill's domain of fitness?

This does not replace the current registry. It refines the decision policy used by planning, backend selection, reuse, promotion, and retirement.

## What Should Be Measured

Each skill should gradually accumulate separate evidence dimensions.

### 1. Correctness Trust

Signals:

- successful executions
- replay consistency
- equivalence against interpreted execution when available
- absence of fallback or repair after selection

Purpose:

- prevent reuse of skills that are fast but semantically weak

### 2. Performance Trust

Signals:

- execution time distributions
- compile overhead versus runtime savings
- performance relative to interpreted alternatives
- performance stability across repeated runs

Purpose:

- separate semantic success from actual execution benefit

### 3. Compression Trust

Signals:

- opcodes reduced by abstraction
- plan size reduction
- lowered planner complexity for similar prompts
- reduced need to rediscover the same rewrite

Purpose:

- measure whether an abstraction skill is actually helping the machine language stay compact and reusable

### 4. Generalization Trust

Signals:

- number of distinct slice signatures where the skill remains valid
- range of prompt families where reuse succeeds
- number of repairs or exclusions needed to keep the skill safe

Purpose:

- distinguish narrow local tricks from robust reusable skills

## How Planning Should Use It

Planning should not use a single global threshold for all reuse.

Instead, selection policy should consider the intent of the current decision.

Examples:

- backend selection should weight correctness and performance highest
- abstraction reuse should weight correctness and compression highest
- speculative candidate ranking might use generalization as a gating factor

That means one skill can be trusted for one kind of reuse but not another.

## Proposed Registry Shape

The local skill registry should eventually extend each skill entry with a trust profile such as:

- `trust.correctness`
- `trust.performance`
- `trust.compression`
- `trust.generalization`
- `trust.overall`

These do not need to begin as complex probabilistic values. Early versions can be bounded scores or counters with clear update rules.

The important design rule is that trust dimensions should remain machine-facing and measurable, not human-opinion fields.

## Promotion And Demotion Model

The current states remain useful:

- `experimental`
- `trusted`
- `retired`

But promotion should eventually depend on the relevant trust dimensions instead of only raw repeated success.

Examples:

- a backend skill may require correctness and performance thresholds before becoming trusted for selection
- an abstraction skill may require correctness and compression thresholds before becoming trusted for synthesis reuse

Demotion should also become explicit.

Examples:

- repeated fallback after selection
- replay mismatch
- degraded performance compared to interpreted execution
- shrinking active reference set caused by poor reuse outcomes

## Guardrails

### Guardrail A: No Human Tuning Surface

The trust model should not become a human-managed configuration surface. It should remain derived from machine evidence.

### Guardrail B: No Single Magic Score

An overall score may be useful, but it should not erase the dimensions underneath it.

### Guardrail C: Reuse Must Stay Reversible

If a trusted skill begins to fail, Symkern must be able to demote or retire it without corrupting the language or planner.

### Guardrail D: Metrics Must Stay Comparable

Trust updates should use comparable evidence sources. Ad hoc one-off measurements will make reuse policy noisy and unreliable.

## Compatibility With Existing Directions

This direction composes with:

- [capability-library.md](/home/joe/10h/symkern/plans/capability-library.md):
  the trust model becomes the measured decision layer over the local skill registry

- backend optimization:
  backend choice can become evidence-weighted rather than hardcoded plus heuristic

- richer planning:
  trusted rewrites and abstractions can be retrieved as measured planning candidates

- evaluation:
  benchmarks become one source of performance and generalization evidence

## Near-Term Implementation Path

1. Add per-skill trust subfields to the local registry.
2. Update backend and abstraction skill recording to write separate correctness, performance, and compression evidence.
3. Introduce per-kind promotion rules instead of one shared threshold.
4. Surface trust dimensions in run artifacts and Periscope explanations.
5. Add demotion rules when repeated evidence contradicts prior trust.

## Success Criteria

This direction is working when Symkern can:

- explain why a skill is trusted for one use but not another
- prefer the right skill for the right reason instead of using one generic trusted state
- demote weak skills based on measured evidence
- reuse local skills more aggressively without increasing brittleness

## Failure Mode To Avoid

The main failure mode is false confidence: skills promoted too early because repeated use was mistaken for broad trust.

If that happens, the registry will make planning overconfident and brittle instead of adaptive.