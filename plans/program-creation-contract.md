# Program Creation Contract Direction

## Why This Direction Exists

Symkern prompts are not supposed to be vague requests for approximate behavior. They are supposed to create machine programs.

That means the core contract must be stronger than "produce something close enough to a known scenario." If a submitted prompt describes a specific computation, Symkern should either:

- create a machine program that faithfully represents that computation
- or fail explicitly because it cannot yet synthesize that program

This direction exists to formalize that standard.

## Core Idea

Prompt submission should be treated as a strict program creation request.

The current anti-pattern to eliminate is nearest-match substitution, where a prompt that is not truly supported is mapped into the closest existing scenario family and then reported as success.

The intended contract is:

- faithful synthesis when the system understands the requested computation
- explicit synthesis failure when it does not

This makes the created Symkern program itself the product of prompt submission.

## What Must Become True

### 1. Translation Must Preserve Unsupported Intent

If the translator sees operations or constraints that do not map cleanly onto a supported goal family, it should not collapse them into a nearby known goal just to obtain a valid payload.

Instead, it should preserve the unmet structure in the intent and surface that the program request is only partially understood.

### 2. Planning Must Not Substitute A Different Program

If the planner does not know how to synthesize the requested computation, it should not quietly route to another plan family.

Instead, it should return an explicit machine-level synthesis gap.

### 3. Success Must Mean Program Fidelity

A run should not be considered successful merely because some plan executed.

For prompt submission, success should mean that the created program matches the requested computation closely enough to justify that it is the same program request realized in machine form.

## Examples Of The Difference

Desired behavior:

- prompt requests decimal sequence generation, square-root mapping, and sum reduction
- Symkern creates that exact program family
- or explicitly says it cannot yet synthesize that program

Undesired behavior:

- prompt requests decimal sequence generation, square-root mapping, and sum reduction
- translator maps it to gaussian statistics because that is the nearest known numeric scenario
- runtime executes successfully but produces the wrong program

The second case is not a successful prompt submission. It is a fidelity failure.

## Layers Affected

This direction primarily affects:

- translator contract and validation
- intent compiler behavior
- planner failure semantics
- evaluation and success criteria
- Periscope explanation of synthesis gaps

## Compatibility With Existing Directions

This direction composes with:

- [skill-trust-model.md](/home/joe/10h/symkern/plans/skill-trust-model.md):
  trusted skills should only be reused when they preserve program fidelity

- [capability-library.md](/home/joe/10h/symkern/plans/capability-library.md):
  retrieval should provide exact or defensible matches, not opportunistic substitution

- [deployment-artifacts.md](/home/joe/10h/symkern/plans/deployment-artifacts.md):
  only faithfully synthesized programs should become deployment candidates

- richer planning:
  more expressive planners make faithful synthesis possible for a broader class of requests

## Guardrails

### Guardrail A: Fidelity Over Coverage

It is better for Symkern to reject or defer an unsupported prompt than to claim success on the wrong program.

### Guardrail B: Explicit Failure Is A Valid Outcome

Unsupported synthesis should not be treated as a broken user experience. It is a correct machine response when fidelity cannot be preserved.

### Guardrail C: Translator And Planner Must Stay Distinct

The translator should not fake planner support by forcing requests into the nearest allowed goal family. It should preserve intent as honestly as possible.

### Guardrail D: Explanations Must Admit Gaps

Periscope should be able to state when a requested program could not yet be synthesized faithfully.

## Near-Term Implementation Path

1. Define failure states for unsupported or partially supported program requests.
2. Tighten translator validation so unsupported operations are not silently normalized away.
3. Update planner logic so generic fallback does not claim equivalent success.
4. Add tests that assert unsupported prompts fail explicitly rather than producing nearest-match plans.
5. Extend Periscope to explain synthesis gaps when they occur.

## Success Criteria

This direction is working when Symkern can:

- create the same program a careful interactive design process would have created
- reject unsupported prompts without silently substituting another computation
- distinguish between execution success and synthesis fidelity
- surface unsupported program structure clearly in artifacts and explanations

## Failure Mode To Avoid

The main failure mode is false success: a prompt appears to work because some program ran, but the created program is not actually the one the prompt requested.

If that happens, prompt submission stops being trustworthy as a program creation interface.