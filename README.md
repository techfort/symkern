# Symkern

Symkern is a prototype prompt-to-artifact system. A human provides a prompt, an intent compiler normalizes it into a strict machine intent, the kernel synthesizes a machine-native plan, persists that plan as an opaque executable artifact, and Periscope writes a separate explanation of what the machine did.

The persisted executable artifact is the primary execution product. It is intentionally opaque and not optimized for human readability. Periscope is downstream-only and exists to explain the artifact without affecting execution.

## Architecture

- `IntentCompiler`: compiles natural-language or symbolic prompts into a validated `PromptIntent`
- `MachineLanguage`: operation registry and plan-building primitives
- `SymKernel`: synthesizes, executes, and persists a machine-native executable artifact
- `Periscope`: explains the persisted artifact in a separate markdown file

## Run

```bash
pip install -e .[dev]
symkern --prompt "Detect anomalies in a streaming signal with low false positives"
symkern-demo
```

The CLI writes run outputs under `artifacts/`.

Each run now persists:

- `machine_code.bin`: compact executable machine artifact
- `machine_symbols.bin`: compact per-run symbol snapshot used for replay and runtime reconstruction
- `machine_artifact.json`: run manifest with outputs and trace
- `periscope.md`: human-readable explanation

The runtime also maintains an evolving shared opcode lexicon at `.symkern/machine_lexicon.bin` under the artifact root. That lexicon is binary and is reused across runs so opcode assignments can stabilize and evolve over time.
