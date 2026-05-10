from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter_ns


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

PROMPT = (
    "Make up an array of 20 numbers with random numbers between 0-20 following "
    "a gaussian distribution. Produce the standard deviation, mean and median."
)


def benchmark_callable(iterations: int, warmup: int, func) -> list[int]:
    for _ in range(warmup):
        func()

    durations_ns: list[int] = []
    for _ in range(iterations):
        start_ns = perf_counter_ns()
        func()
        durations_ns.append(perf_counter_ns() - start_ns)
    return durations_ns


def summarize(durations_ns: list[int]) -> dict[str, float | int]:
    return {
        "iterations": len(durations_ns),
        "min_ns": min(durations_ns),
        "max_ns": max(durations_ns),
        "mean_ns": round(statistics.fmean(durations_ns), 2),
        "median_ns": round(statistics.median(durations_ns), 2),
        "stdev_ns": round(statistics.pstdev(durations_ns), 2),
    }


def compile_c_binary(output_path: Path) -> Path:
    compiler = shutil.which("gcc") or shutil.which("cc")
    if compiler is None:
        raise RuntimeError("No C compiler found. Install gcc or cc to run the benchmark.")

    source_path = ROOT / "benchmarks" / "gaussian_array_stats.c"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [compiler, "-O3", "-std=c11", str(source_path), "-lm", "-o", str(output_path)],
        check=True,
        cwd=ROOT,
    )
    return output_path


def symkern_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) if not existing_pythonpath else f"{SRC}:{existing_pythonpath}"
    return env


def build_symkern_core_command() -> list[str]:
    return [sys.executable, str(ROOT / "benchmarks" / "symkern_core_entry.py"), "--prompt", PROMPT]


def run_symkern_core_subprocess() -> None:
    subprocess.run(
        build_symkern_core_command(),
        check=True,
        cwd=ROOT,
        env=symkern_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def capture_symkern_core_sample() -> dict[str, object]:
    completed = subprocess.run(
        [*build_symkern_core_command(), "--json"],
        check=True,
        cwd=ROOT,
        env=symkern_env(),
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def build_cli_command(artifact_root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "symkern.cli",
        "--prompt",
        PROMPT,
        "--artifact-root",
        str(artifact_root),
    ]


def run_symkern_cli(artifact_root: Path) -> None:
    subprocess.run(
        build_cli_command(artifact_root),
        check=True,
        cwd=ROOT,
        env=symkern_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def latest_machine_artifact(artifact_root: Path) -> Path:
    return max(artifact_root.glob("run-*/machine_artifact.json"), key=lambda path: path.stat().st_mtime_ns)


def capture_symkern_cli_phase_sample(artifact_root: Path) -> dict[str, object]:
    run_symkern_cli(artifact_root)
    artifact = json.loads(latest_machine_artifact(artifact_root).read_text(encoding="utf-8"))
    return dict(artifact.get("timings", {}))


def build_c_command(binary_path: Path, artifact_root: Path | None = None) -> list[str]:
    command = [str(binary_path)]
    if artifact_root is not None:
        command.extend(["--artifact-root", str(artifact_root)])
    return command


def run_c_binary(binary_path: Path, artifact_root: Path | None = None) -> None:
    subprocess.run(build_c_command(binary_path, artifact_root), check=True, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture_c_artifact_phase_sample(binary_path: Path, artifact_root: Path) -> dict[str, object]:
    run_c_binary(binary_path, artifact_root=artifact_root)
    artifact = json.loads((artifact_root / "c_artifact.json").read_text(encoding="utf-8"))
    return dict(artifact.get("timings", {}))


def write_results(results: dict[str, object]) -> tuple[Path, Path]:
    results_dir = ROOT / "benchmarks" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "latest.json"
    md_path = results_dir / "latest.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    comparison = results["comparison"]
    phase_samples = results["phase_samples"]
    md_path.write_text(
        "# Benchmark Results\n\n"
        f"Prompt: `{PROMPT}`\n\n"
        "## Scenario\n"
        "- Symkern executes a mixed plan: the gaussian synthesis and statistics slice runs through a compiled backend, while the sink-facing orchestration remains in Symkern.\n"
        "- The C paths remain standalone implementations of the same numeric workload, with and without artifact output.\n\n"
        "## Summary\n"
        f"- Symkern core subprocess mean: {comparison['symkern_core_subprocess_mean_ms']} ms\n"
        f"- Symkern CLI mean: {comparison['symkern_cli_mean_ms']} ms\n"
        f"- C core mean: {comparison['c_core_mean_ms']} ms\n"
        f"- C artifact mean: {comparison['c_artifact_mean_ms']} ms\n"
        f"- C core speedup vs Symkern core subprocess: {comparison['c_core_vs_symkern_core_subprocess_speedup']}x\n"
        f"- C artifact speedup vs Symkern CLI: {comparison['c_artifact_vs_symkern_cli_speedup']}x\n\n"
        "## Phase Samples\n"
        f"- Symkern core sample timings: `{json.dumps(phase_samples['symkern_core_subprocess'])}`\n"
        f"- Symkern CLI sample timings: `{json.dumps(phase_samples['symkern_cli'])}`\n"
        f"- C artifact sample timings: `{json.dumps(phase_samples['c_artifact'])}`\n",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Symkern against a C implementation for gaussian array statistics.")
    parser.add_argument("--iterations", type=int, default=1000, help="Measured iterations per implementation")
    parser.add_argument("--warmup", type=int, default=100, help="Warmup iterations per implementation")
    args = parser.parse_args()

    binary_path = compile_c_binary(ROOT / "benchmarks" / "bin" / "gaussian_array_stats")

    with tempfile.TemporaryDirectory(prefix="symkern-bench-cli-") as symkern_cli_root, tempfile.TemporaryDirectory(prefix="symkern-bench-c-") as c_artifact_root:
        symkern_core_subprocess_durations = benchmark_callable(args.iterations, args.warmup, run_symkern_core_subprocess)
        symkern_cli_durations = benchmark_callable(args.iterations, args.warmup, lambda: run_symkern_cli(Path(symkern_cli_root)))
        c_core_durations = benchmark_callable(args.iterations, args.warmup, lambda: run_c_binary(binary_path))
        c_artifact_durations = benchmark_callable(args.iterations, args.warmup, lambda: run_c_binary(binary_path, artifact_root=Path(c_artifact_root)))

        phase_samples = {
            "symkern_core_subprocess": dict(capture_symkern_core_sample()["timings"]),
            "symkern_cli": capture_symkern_cli_phase_sample(Path(symkern_cli_root)),
            "c_artifact": capture_c_artifact_phase_sample(binary_path, Path(c_artifact_root)),
        }

    results = {
        "prompt": PROMPT,
        "iterations": args.iterations,
        "warmup": args.warmup,
        "symkern_core_subprocess": summarize(symkern_core_subprocess_durations),
        "symkern_cli": summarize(symkern_cli_durations),
        "c_core": summarize(c_core_durations),
        "c_artifact": summarize(c_artifact_durations),
        "phase_samples": phase_samples,
    }
    results["comparison"] = {
        "symkern_core_subprocess_mean_ms": round(results["symkern_core_subprocess"]["mean_ns"] / 1_000_000, 4),
        "symkern_cli_mean_ms": round(results["symkern_cli"]["mean_ns"] / 1_000_000, 4),
        "c_core_mean_ms": round(results["c_core"]["mean_ns"] / 1_000_000, 4),
        "c_artifact_mean_ms": round(results["c_artifact"]["mean_ns"] / 1_000_000, 4),
        "c_core_vs_symkern_core_subprocess_speedup": round(results["symkern_core_subprocess"]["mean_ns"] / results["c_core"]["mean_ns"], 2),
        "c_artifact_vs_symkern_cli_speedup": round(results["symkern_cli"]["mean_ns"] / results["c_artifact"]["mean_ns"], 2),
    }

    json_path, md_path = write_results(results)
    print(f"results-json: {json_path}")
    print(f"results-md: {md_path}")
    print(json.dumps(results["comparison"], indent=2))


if __name__ == "__main__":
    main()