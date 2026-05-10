from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter_ns


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from symkern.intent_compiler import IntentCompiler
from symkern.kernel import KernelOrchestrator


DEFAULT_PROMPT = (
    "Make up an array of 20 numbers with random numbers between 0-20 following "
    "a gaussian distribution. Produce the standard deviation, mean and median."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Symkern core compilation and execution without artifact persistence.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to compile and execute")
    parser.add_argument("--json", action="store_true", help="Print timings and outputs as JSON")
    args = parser.parse_args()

    total_start_ns = perf_counter_ns()
    compiler = IntentCompiler()
    compile_start_ns = perf_counter_ns()
    compiled = compiler.compile(args.prompt)
    compile_ns = perf_counter_ns() - compile_start_ns

    converge_start_ns = perf_counter_ns()
    convergence = KernelOrchestrator().converge(compiled.intent)
    converge_ns = perf_counter_ns() - converge_start_ns
    total_ns = perf_counter_ns() - total_start_ns

    result = {
        "status": convergence.status,
        "timings": {
            **dict(convergence.timings),
            "compile_ns": compile_ns,
            "converge_ns": converge_ns,
            "core_total_ns": total_ns,
        },
        "outputs": convergence.outputs,
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(result["status"])


if __name__ == "__main__":
    main()