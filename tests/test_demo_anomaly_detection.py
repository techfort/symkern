from pathlib import Path

from symkern.cli import submit_prompt
from symkern.machine_code import CODE_MAGIC, SYMBOLS_MAGIC


def test_prompt_produces_machine_artifact_and_periscope(tmp_path: Path) -> None:
    result = submit_prompt(
        "Detect anomalies in a streaming signal with low false positives and low latency",
        artifact_root=tmp_path,
    )

    artifact_path = Path(result["artifact_path"])
    machine_code_path = Path(result["machine_code_path"])
    dictionary_path = Path(result["machine_symbols_path"])
    periscope_path = Path(result["periscope_path"])

    assert result["status"] == "success"
    assert artifact_path.exists()
    assert machine_code_path.exists()
    assert dictionary_path.exists()
    assert periscope_path.exists()
    assert machine_code_path.read_bytes().startswith(CODE_MAGIC)
    assert dictionary_path.read_bytes().startswith(SYMBOLS_MAGIC)
    assert "Periscope" in periscope_path.read_text(encoding="utf-8")