# Benchmarks

This folder compares Symkern against a C implementation for the gaussian-array statistics task:

- Generate 20 gaussian-distributed numbers bounded to `0..20`
- Compute population standard deviation, mean, and median

Included implementations:

- `gaussian_array_stats.c`: standalone C version of the workload
- `symkern_core_entry.py`: subprocess entrypoint for Symkern core without artifact persistence
- `run_benchmarks.py`: benchmark runner for `symkern_core`, `symkern_cli`, and the compiled C binary

Run it from the repository root:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_benchmarks.py --iterations 1000 --warmup 100
```

Outputs are written to:

- `benchmarks/results/latest.json`
- `benchmarks/results/latest.md`

Notes:

- The current benchmark scenario is mixed execution inside Symkern: the gaussian array generation and statistics slice is eligible for the compiled C backend, while the sink-facing orchestration remains interpreted in Symkern.
- `symkern_core_subprocess` measures compiler + kernel orchestration in a fresh subprocess without artifact persistence.
- `symkern_cli` measures full CLI execution including artifact persistence and Periscope generation.
- `c_core` measures the compiled C binary for the same numeric workload.
- `c_artifact` measures the compiled C binary while also writing a JSON artifact, which is a closer end-to-end comparison against `symkern_cli`.
- `latest.json` now includes `phase_samples` so compile, execute, persist, and explain-related costs can be inspected separately.
- The C benchmark measures the same workload, but it is not expected to reproduce Python's exact gaussian sample sequence.