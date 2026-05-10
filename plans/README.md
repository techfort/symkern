# Symkern Plans

This folder captures development directions before they harden into code.

The purpose is not to freeze Symkern into one future. The purpose is to let multiple futures be explored without colliding.

## Planning Rules

- Every new direction should preserve the machine-first boundary: human prompts in, machine-native execution and optimization inside, Periscope explanations out.
- Every new direction should declare which layer it changes: compiler, planner, runtime, backend, persistence, evaluation, or capability memory.
- Every new direction should state what existing invariants it must not break.
- Every new direction should define how it composes with other directions rather than assuming it replaces them.
- When two directions conflict, the conflict should be resolved here before expanding implementation scope.

## Current Directions

- Capability library and self-improvement:
  See [capability-library.md](/home/joe/10h/symkern/plans/capability-library.md).

- Skill trust and reuse policy:
  See [skill-trust-model.md](/home/joe/10h/symkern/plans/skill-trust-model.md).

- Backend optimization and mixed execution:
  Symkern can already choose compiled backends for some slices. Future work should make backend choice cost-based and capability-driven rather than scenario-specific.

- Richer plan optimization:
  The planner should evolve from pattern selection toward competing candidate plans, rewrite passes, and measured cost tradeoffs.

- Evaluation on adaptive multi-step tasks:
  Benchmarks should increasingly target orchestration quality, convergence, reuse, and backend selection quality, not just narrow numeric kernels.

## Shared Invariants

- The machine language remains the canonical internal representation.
- Human-readable artifacts remain downstream explanations, not the executable substrate.
- Compiled backends are realizations of plan slices, not replacements for the planner.
- Capability growth must be indexed and measured; Symkern should not become an unstructured archive of generated code.
- New storage of generated artifacts must preserve provenance, fitness history, and retrieval metadata.

## Decision Template For New Directions

When adding a new plan to this folder, answer these questions:

1. What layer does this direction primarily change?
2. What invariants must remain true?
3. What other directions does it depend on?
4. What other directions could it conflict with?
5. How will Symkern know when this direction improved the system?
