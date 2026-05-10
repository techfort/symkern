from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from symkern.logging import ExecutionTrace
from symkern.machine_code import decode_machine_code, encode_machine_code, load_or_create_lexicon, save_lexicon
from symkern.nodes import PlanGraph


@dataclass(slots=True)
class ArtifactBundle:
    run_id: str
    prompt: str
    plan: PlanGraph
    outputs: dict[str, object]
    status: str
    reason_codes: list[str] = field(default_factory=list)
    inventions: list[dict[str, object]] = field(default_factory=list)
    trace: ExecutionTrace = field(default_factory=ExecutionTrace)
    compiler: dict[str, object] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    language_snapshot: dict[str, object] = field(default_factory=dict)
    timings: dict[str, object] = field(default_factory=dict)
    backend: dict[str, object] = field(default_factory=dict)

    def machine_language_dict(self) -> dict[str, object]:
        if self.language_snapshot:
            snapshot = dict(self.language_snapshot)
            snapshot["run_id"] = self.run_id
            return snapshot
        return {
            "kind": "symkern.machine_language",
            "schema_version": "symkern.machine-language/v1alpha1",
            "run_id": self.run_id,
            "plan": self.plan.to_dict(),
            "operation_schemas": {},
            "inventions": list(self.inventions),
            "status": self.status,
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "prompt": self.prompt,
            "outputs": dict(self.outputs),
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "trace": self.trace.to_dict(),
            "compiler": dict(self.compiler),
            "files": dict(self.files),
            "timings": dict(self.timings),
            "backend": dict(self.backend),
        }


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def lexicon_path(self) -> Path:
        return self.root / ".symkern" / "machine_lexicon.bin"

    def save_machine_artifact(self, bundle: ArtifactBundle) -> Path:
        run_dir = self.root / bundle.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = run_dir / "machine_artifact.json"
        artifact_path.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
        return artifact_path

    def save_machine_code(self, bundle: ArtifactBundle) -> tuple[Path, Path]:
        run_dir = self.root / bundle.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        code_path = run_dir / "machine_code.bin"
        dictionary_path = run_dir / "machine_symbols.bin"
        lexicon = load_or_create_lexicon(self.lexicon_path())
        code_bytes, symbol_bytes = encode_machine_code(bundle.machine_language_dict(), lexicon)
        code_path.write_bytes(code_bytes)
        dictionary_path.write_bytes(symbol_bytes)
        save_lexicon(self.lexicon_path(), lexicon)
        return code_path, dictionary_path

    def save_machine_language(self, bundle: ArtifactBundle) -> Path:
        run_dir = self.root / bundle.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        language_path = run_dir / "machine_language.json"
        language_path.write_text(json.dumps(bundle.machine_language_dict(), indent=2), encoding="utf-8")
        return language_path

    def save_periscope(self, run_id: str, content: str) -> Path:
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        periscope_path = run_dir / "periscope.md"
        periscope_path.write_text(content, encoding="utf-8")
        return periscope_path

    def save_backend_artifacts(self, bundle: ArtifactBundle) -> dict[str, str]:
        generated_files = dict(bundle.backend.get("generated_files", {}))
        if not generated_files:
            return {}

        run_dir = self.root / bundle.run_id / "backend"
        run_dir.mkdir(parents=True, exist_ok=True)
        persisted: dict[str, str] = {}
        for name, path_str in generated_files.items():
            source_path = Path(path_str)
            if not source_path.exists():
                continue
            destination = run_dir / source_path.name
            shutil.copy2(source_path, destination)
            persisted[name] = str(destination)
        return persisted

    def load_machine_artifact(self, path: str | Path) -> dict[str, object]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def load_machine_language(self, path: str | Path, dictionary_path: str | Path | None = None) -> dict[str, object]:
        target_path = Path(path)
        if target_path.suffix == ".bin":
            resolved_dictionary = Path(dictionary_path) if dictionary_path is not None else target_path.with_name("machine_symbols.bin")
            lexicon = load_or_create_lexicon(self.lexicon_path())
            return decode_machine_code(target_path.read_bytes(), lexicon, resolved_dictionary.read_bytes())
        return json.loads(target_path.read_text(encoding="utf-8"))
