from pathlib import Path
import json

from symkern.cli import submit_prompt
from symkern.machine_code import CODE_MAGIC, SYMBOLS_MAGIC


def test_array_prompt_creates_artifact_with_source_and_mapped_arrays(tmp_path: Path) -> None:
    result = submit_prompt(
        "Create a 5-element array of random numbers whose value is between 1 and 10, then create an array that is a map of the first array with random maths operation applied to the members of the first array.",
        artifact_root=tmp_path,
    )

    artifact_path = Path(result["artifact_path"])
    machine_code_path = Path(result["machine_code_path"])
    dictionary_path = Path(result["machine_symbols_path"])
    artifact_text = artifact_path.read_text(encoding="utf-8")

    assert result["status"] == "success"
    assert machine_code_path.exists()
    assert dictionary_path.exists()
    assert machine_code_path.read_bytes().startswith(CODE_MAGIC)
    assert dictionary_path.read_bytes().startswith(SYMBOLS_MAGIC)
    assert "source_array" in artifact_text
    assert "mapped_array" in artifact_text


def test_gaussian_statistics_prompt_creates_artifact_with_statistics(tmp_path: Path) -> None:
    result = submit_prompt(
        "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median.",
        artifact_root=tmp_path,
    )

    artifact_path = Path(result["artifact_path"])
    machine_code_path = Path(result["machine_code_path"])
    dictionary_path = Path(result["machine_symbols_path"])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    outputs = artifact["outputs"]

    assert result["status"] == "success"
    assert machine_code_path.exists()
    assert dictionary_path.exists()
    assert machine_code_path.read_bytes().startswith(CODE_MAGIC)
    assert dictionary_path.read_bytes().startswith(SYMBOLS_MAGIC)
    assert len(outputs["source_array"]) == 20
    assert all(0 <= value <= 20 for value in outputs["source_array"])
    assert set(outputs["statistics"].keys()) == {"standard_deviation", "mean", "median"}
    assert result["timings"]["compiled_backend_target"] == "c.gaussian_array_statistics"


def test_gaussian_statistics_prompt_executes_compiled_backend(tmp_path: Path) -> None:
    result = submit_prompt(
        "Make up an array of 8 numbers with random numbers between 2-12 following a gaussian distribution. Produce the standard deviation, mean and median.",
        artifact_root=tmp_path,
    )

    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert result["status"] == "success"
    assert result["timings"]["compiled_backend_target"] == "c.gaussian_array_statistics"
    assert len(artifact["outputs"]["source_array"]) == 8
    assert all(2 <= value <= 12 for value in artifact["outputs"]["source_array"])
    assert set(result["timings"]["node_execute_ns"].keys()) == {"n1", "n2", "n3"}