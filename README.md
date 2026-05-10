# Symkern

Symkern is a prototype prompt-to-artifact system. A human provides a prompt, an intent compiler normalizes it into a strict machine intent, the kernel synthesizes a machine-native plan, persists that plan as an opaque executable artifact, and Periscope writes a separate explanation of what the machine did.

The persisted executable artifact is the primary execution product. It is intentionally opaque and not optimized for human readability. Periscope is downstream-only and exists to explain the artifact without affecting execution.

## Architecture

- `IntentCompiler`: compiles natural-language or symbolic prompts into a validated `PromptIntent`
- `TranslatorAdapter`: optional LLM-facing adapter that translates prompts into the versioned Symkern intent contract
- `MachineLanguage`: operation registry and plan-building primitives
- `SymKernel`: synthesizes, executes, and persists a machine-native executable artifact
- `Periscope`: explains the persisted artifact in a separate markdown file

## Run

```bash
pip install -e .[dev]
symkern --prompt "Detect anomalies in a streaming signal with low false positives"
symkern-demo
```

To test a local model through Ollama while preserving the same validated ingress contract:

```bash
symkern \
	--prompt "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median." \
	--translator ollama \
	--ollama-model llama3.2:3b
```

The translator boundary is provider-neutral. The package now includes:

- packaged JSON resources for the intent schema and ontology
- automatic repair for invalid model translations
- adapters for `ollama`, `openai-compatible`, and `anthropic` style APIs

The CLI writes run outputs under `artifacts/`.

Each run now persists:

- `machine_code.bin`: compact executable machine artifact
- `machine_symbols.bin`: compact per-run symbol snapshot used for replay and runtime reconstruction
- `machine_artifact.json`: run manifest with outputs and trace
- `periscope.md`: human-readable explanation

The runtime also maintains an evolving shared opcode lexicon at `.symkern/machine_lexicon.bin` under the artifact root. That lexicon is binary and is reused across runs so opcode assignments can stabilize and evolve over time.
