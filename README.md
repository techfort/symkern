# Symkern

Symkern is a prototype machine-first symbolic kernel. A human provides a prompt, a translator boundary normalizes it into a strict machine intent, the kernel synthesizes and executes a machine-native plan, persists that plan as an opaque executable artifact, and Periscope writes a separate explanation of what the machine did.

The persisted executable artifact is the primary execution product. It is intentionally opaque and not optimized for human readability. Periscope is downstream-only and exists to explain the artifact without affecting execution.

At the current stage, Symkern is no longer just a prompt-to-plan demo. It now includes:

- a versioned translator contract between LLMs and the kernel
- local or remote translator adapters
- opaque executable machine artifacts with replay and explain flows
- compiled backend selection for eligible plan slices
- a local skill registry with promotion, reuse, reference counting, and retirement
- Periscope explanations for inputs, outputs, backend selection, performance, and strategy

## Architecture

- `TranslatorAdapter`: optional LLM-facing adapter that translates prompts into the versioned Symkern intent contract
- `IntentCompiler`: validates translator output and normalizes it into a `PromptIntent`
- `MachineLanguage`: operation registry, plan building, replay reconstruction, and invented opcode support
- `SymKernel`: synthesizes, optimizes, executes, and persists machine-native executable artifacts
- `CompiledBackendRegistry`: selects compiled realizations for eligible slices
- `SkillRegistry`: stores local backend and abstraction skills, tracks executable references, and retires unused skills
- `Periscope`: explains the persisted artifact in a separate markdown file

## Current Capabilities

The current prototype supports these scenario families:

- stream anomaly detection
- random array generation and randomized mapping
- gaussian-distributed array generation with statistics
- historical date generation, Wikipedia death lookup, and illustrious-candidate selection

It also supports:

- compiled backend execution for gaussian statistics slices
- compiled backend execution for historical death ranking slices
- mixed interpreted and compiled execution in a single plan
- replay from persisted `machine_code.bin`
- explanation from persisted machine code without exposing the executable representation directly

## Translator Boundary

Symkern now has an explicit LLM-agnostic ingress boundary.

The model is not asked to generate a Symkern program. It is asked to emit a versioned Symkern intent contract. That contract is then validated and normalized before the kernel sees it.

The translator layer currently includes:

- packaged JSON resources for the intent schema and ontology
- automatic repair when model output validates structurally but fails contract rules
- adapters for `ollama`, `openai-compatible`, and `anthropic` style APIs
- a deterministic heuristic path so the system remains runnable offline

Key resources:

- [src/symkern/resources/intent_schema.json](src/symkern/resources/intent_schema.json)
- [src/symkern/resources/intent_ontology.json](src/symkern/resources/intent_ontology.json)

## Local Skill System

Symkern now maintains a deployment-local skill registry under `.symkern/skills/registry.json`.

That registry currently stores:

- backend skills for compiled execution targets
- abstraction skills for invented opcodes and compressed plan fragments

Each deployment can therefore evolve differently depending on what it runs.

The registry currently supports:

- accumulation of new local skills from successful runs
- promotion from `experimental` to `trusted`
- reuse of trusted abstraction skills during synthesis
- reference counting through persisted machine executables
- retirement of skills with zero active executable references

This means Symkern already behaves like an early machine-native tree shaker: unused local skills are retired instead of being accumulated forever.

## Run

```bash
pip install -e .[dev]
symkern --prompt "Detect anomalies in a streaming signal with low false positives"
symkern-demo
```

## Translator Examples

To test a local model through Ollama while preserving the same validated ingress contract:

```bash
symkern \
	--prompt "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median." \
	--translator ollama \
	--ollama-model llama3.1:8b
```

OpenAI-compatible example:

```bash
symkern \
	--prompt "Detect anomalies in a streaming signal with low false positives" \
	--translator openai-compatible \
	--translator-model gpt-4.1-mini \
	--translator-api-key-env OPENAI_API_KEY
```

Anthropic example:

```bash
symkern \
	--prompt "make up 3 historical dates, lookup on wikipedia.org what deaths occurred on those dates and elect the most illustrious one" \
	--translator anthropic \
	--translator-model claude-3-5-sonnet-latest \
	--translator-api-key-env ANTHROPIC_API_KEY
```

Equivalent runnable scripts are stored in [examples](examples):

- [examples/ollama_gaussian_stats.sh](examples/ollama_gaussian_stats.sh)
- [examples/openai_compatible_anomaly_detection.sh](examples/openai_compatible_anomaly_detection.sh)
- [examples/anthropic_historical_death_lookup.sh](examples/anthropic_historical_death_lookup.sh)

## Artifacts

The CLI writes run outputs under `artifacts/`.

Each run now persists:

- `machine_code.bin`: compact executable machine artifact
- `machine_symbols.bin`: compact per-run symbol snapshot used for replay and runtime reconstruction
- `machine_artifact.json`: run manifest with outputs and trace
- `periscope.md`: human-readable explanation

Compiled runs may also persist backend-specific artifacts under the run directory:

- generated backend source
- compiled backend binary

The runtime also maintains an evolving shared opcode lexicon at `.symkern/machine_lexicon.bin` under the artifact root. That lexicon is binary and is reused across runs so opcode assignments can stabilize and evolve over time.

## Explain And Replay

Symkern supports both replay and explain workflows from persisted machine code.

- replay reconstructs and re-executes the machine artifact
- explain reconstructs the machine artifact and emits Periscope documentation without exposing the executable representation directly

Examples:

```bash
symkern --replay-language artifacts/<run-id>/machine_code.bin
symkern --explain-machine-code artifacts/<run-id>/machine_code.bin
```

## What Periscope Documents

Periscope currently includes:

- goals and high-level artifact behavior
- explicit inputs and outputs
- backend selection decisions
- performance and per-node timing
- reconstructed strategy
- machine intent narrative
- machine abstractions
- execution trace

## Development Status

This is still an early-stage prototype. The key result so far is not just that Symkern can execute prompts, but that it now has the beginnings of a self-evolving local machine substrate:

- prompts can be translated through an explicit contract
- plans can be executed partly through compiled backends
- local skills can be learned, reused, and retired
- executable artifacts remain opaque while explanations remain downstream-only

The next architectural directions are documented in [plans](plans).
