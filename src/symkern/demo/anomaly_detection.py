from __future__ import annotations

from symkern.cli import submit_prompt


def main() -> None:
    result = submit_prompt(
        "Detect anomalies in a streaming signal with low false positives and low latency",
        artifact_root="artifacts",
    )
    print(f"Demo run: {result['run_id']}")
    print(f"Machine artifact: {result['artifact_path']}")
    print(f"Periscope: {result['periscope_path']}")
    print(result["plan_view"])
    print(result["outputs"])


if __name__ == "__main__":
    main()
