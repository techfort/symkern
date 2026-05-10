from pathlib import Path

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