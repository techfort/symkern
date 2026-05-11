from __future__ import annotations

import json
from pathlib import Path


class ProgramRegistry:
    SCHEMA_VERSION = "symkern.program-registry/v1alpha1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.registry_path = self.root / ".symkern" / "programs" / "registry.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "programs": {}}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def save(self, document: dict[str, object]) -> None:
        self.registry_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def register(
        self,
        program_id: str,
        machine_code_path: str,
        machine_symbols_path: str | None,
        artifact_path: str,
        program_spec: dict[str, object],
        input_contract: list[dict[str, object]],
    ) -> dict[str, object]:
        document = self.load()
        programs = dict(document.get("programs", {}))
        entry = {
            "program_id": program_id,
            "machine_code_path": machine_code_path,
            "machine_symbols_path": machine_symbols_path,
            "artifact_path": artifact_path,
            "program_spec": dict(program_spec),
            "input_contract": [dict(item) for item in input_contract],
        }
        programs[program_id] = entry
        document["programs"] = programs
        self.save(document)
        return entry

    def resolve(self, program_id: str) -> dict[str, object]:
        document = self.load()
        programs = dict(document.get("programs", {}))
        if program_id not in programs:
            raise KeyError(f"Unknown program id: {program_id}")
        return dict(programs[program_id])