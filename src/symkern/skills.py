from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "symkern.skill-registry/v1alpha1"


@dataclass(slots=True)
class SkillMatch:
    skill_id: str
    entry: dict[str, object]


class SkillRegistry:
    def __init__(self, deployment_root: str | Path) -> None:
        self.deployment_root = Path(deployment_root)
        self.registry_dir = self.deployment_root / ".symkern" / "skills"
        self.registry_path = self.registry_dir / "registry.json"
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return {"schema_version": SCHEMA_VERSION, "skills": {}}
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported skill registry schema version: {payload.get('schema_version')}")
        payload.setdefault("skills", {})
        return payload

    def save(self, payload: dict[str, object]) -> None:
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def lookup_backend_skill(self, target: str, slice_signature: dict[str, object]) -> SkillMatch | None:
        registry = self.load()
        for skill_id, entry in dict(registry.get("skills", {})).items():
            if str(entry.get("kind", "")) != "backend":
                continue
            if str(entry.get("status", "")) == "retired":
                continue
            if str(entry.get("target", "")) != target:
                continue
            if dict(entry.get("slice_signature", {})) != slice_signature:
                continue
            return SkillMatch(skill_id=skill_id, entry=dict(entry))
        return None

    def record_backend_skill(
        self,
        *,
        target: str,
        slice_signature: dict[str, object],
        ideal_for: list[str],
        selection: dict[str, object],
        timings: dict[str, object],
        backend: dict[str, object],
        run_id: str,
        prompt: str,
        executable_path: str,
        success: bool,
    ) -> dict[str, object]:
        registry = self.load()
        skills = dict(registry.get("skills", {}))
        skill_id = self._find_backend_skill_id(skills, target, slice_signature) or self._skill_id(target, slice_signature)
        existing = dict(skills.get(skill_id, {}))

        selection_count = int(existing.get("selection_count", 0)) + 1
        success_count = int(existing.get("success_count", 0)) + (1 if success else 0)
        execute_ns = int(timings.get("execute_ns", 0))
        total_execute_ns = int(existing.get("total_execute_ns", 0)) + execute_ns
        mean_execute_ns = int(total_execute_ns / max(success_count, 1)) if success_count else 0
        source_runs = list(existing.get("source_runs", []))
        source_runs.append({"run_id": run_id, "prompt": prompt, "success": success})
        source_runs = source_runs[-10:]

        artifacts = dict(backend.get("artifacts", {}))
        artifact_examples = list(existing.get("artifact_examples", []))
        if artifacts:
            artifact_examples.append(dict(artifacts))
            artifact_examples = artifact_examples[-5:]

        executable_references = self._merge_executable_reference(
            list(existing.get("executable_references", [])),
            {
                "run_id": run_id,
                "machine_code_path": executable_path,
                "target": target,
            },
        )
        active_reference_count = self._count_active_references(executable_references)

        status = "retired" if active_reference_count == 0 else ("trusted" if success_count >= 3 else "experimental")
        entry = {
            "skill_id": skill_id,
            "name": target.split(".")[-1],
            "kind": "backend",
            "target": target,
            "slice_signature": dict(slice_signature),
            "ideal_for": list(ideal_for),
            "selection": dict(selection),
            "selection_count": selection_count,
            "success_count": success_count,
            "total_execute_ns": total_execute_ns,
            "mean_execute_ns": mean_execute_ns,
            "last_execute_ns": execute_ns,
            "active_reference_count": active_reference_count,
            "status": status,
            "artifact_examples": artifact_examples,
            "executable_references": executable_references,
            "source_runs": source_runs,
        }
        skills[skill_id] = entry
        registry["skills"] = skills
        self.save(registry)
        return entry

    def record_abstraction_skill(
        self,
        *,
        invention: dict[str, object],
        run_id: str,
        prompt: str,
        executable_path: str,
    ) -> dict[str, object]:
        registry = self.load()
        skills = dict(registry.get("skills", {}))
        skill_id = self._abstraction_skill_id(invention)
        existing = dict(skills.get(skill_id, {}))

        application_count = int(existing.get("application_count", 0)) + 1
        source_runs = list(existing.get("source_runs", []))
        source_runs.append({"run_id": run_id, "prompt": prompt, "success": True})
        source_runs = source_runs[-10:]
        executable_references = self._merge_executable_reference(
            list(existing.get("executable_references", [])),
            {
                "run_id": run_id,
                "machine_code_path": executable_path,
                "op_code": int(invention.get("op_code", -1)),
            },
        )
        active_reference_count = self._count_active_references(executable_references)
        status = "retired" if active_reference_count == 0 else ("trusted" if application_count >= 3 else "experimental")

        entry = {
            "skill_id": skill_id,
            "name": f"opcode_{int(invention.get('op_code', -1))}",
            "kind": "abstraction",
            "op_code": int(invention.get("op_code", -1)),
            "source_op_codes": list(invention.get("source_op_codes", [])),
            "rationale": str(invention.get("rationale", "")),
            "score": float(invention.get("score", 0.0)),
            "application_count": application_count,
            "active_reference_count": active_reference_count,
            "status": status,
            "executable_references": executable_references,
            "source_runs": source_runs,
        }
        skills[skill_id] = entry
        registry["skills"] = skills
        self.save(registry)
        return entry

    def reconcile_executable_references(self) -> dict[str, object]:
        registry = self.load()
        skills = dict(registry.get("skills", {}))
        retired: list[str] = []
        changed = False
        for skill_id, entry in list(skills.items()):
            executable_references = list(entry.get("executable_references", []))
            active_references = [reference for reference in executable_references if Path(str(reference.get("machine_code_path", ""))).exists()]
            active_reference_count = len(active_references)
            next_status = "retired" if active_reference_count == 0 else ("trusted" if int(entry.get("success_count", 0)) >= 3 else "experimental")
            if active_references != executable_references or int(entry.get("active_reference_count", 0)) != active_reference_count or str(entry.get("status", "")) != next_status:
                updated_entry = dict(entry)
                updated_entry["executable_references"] = active_references
                updated_entry["active_reference_count"] = active_reference_count
                updated_entry["status"] = next_status
                skills[skill_id] = updated_entry
                changed = True
            if active_reference_count == 0:
                retired.append(skill_id)
        if changed:
            registry["skills"] = skills
            self.save(registry)
        return {"retired_skill_ids": retired, "skill_count": len(skills)}

    def trusted_abstraction_skills(self) -> list[dict[str, object]]:
        registry = self.load()
        skills = []
        for entry in dict(registry.get("skills", {})).values():
            skill = dict(entry)
            if str(skill.get("kind", "")) != "abstraction":
                continue
            if str(skill.get("status", "")) != "trusted":
                continue
            if int(skill.get("active_reference_count", 0)) <= 0:
                continue
            skills.append(skill)
        return sorted(skills, key=lambda item: (-int(item.get("application_count", 0)), int(item.get("op_code", 0))))

    @staticmethod
    def _count_active_references(executable_references: list[dict[str, object]]) -> int:
        return sum(1 for reference in executable_references if Path(str(reference.get("machine_code_path", ""))).exists())

    @staticmethod
    def _merge_executable_reference(existing: list[dict[str, object]], new_reference: dict[str, object]) -> list[dict[str, object]]:
        machine_code_path = str(new_reference.get("machine_code_path", ""))
        filtered = [reference for reference in existing if str(reference.get("machine_code_path", "")) != machine_code_path]
        filtered.append(dict(new_reference))
        return filtered[-25:]

    @staticmethod
    def _find_backend_skill_id(skills: dict[str, object], target: str, slice_signature: dict[str, object]) -> str | None:
        for skill_id, raw_entry in skills.items():
            entry = dict(raw_entry)
            if str(entry.get("kind", "")) != "backend":
                continue
            if str(entry.get("target", "")) != target:
                continue
            if dict(entry.get("slice_signature", {})) != slice_signature:
                continue
            return skill_id
        return None

    @staticmethod
    def _abstraction_skill_id(invention: dict[str, object]) -> str:
        op_code = int(invention.get("op_code", -1))
        source_op_codes = "-".join(str(item) for item in list(invention.get("source_op_codes", []))) or "opaque"
        return f"skill.abstraction.{op_code}.{source_op_codes}"

    @staticmethod
    def _skill_id(target: str, slice_signature: dict[str, object]) -> str:
        op_codes = "-".join(str(item) for item in list(slice_signature.get("op_codes", []))) or "opaque"
        goals = "-".join(str(item) for item in list(slice_signature.get("goals", []))) or "generic"
        return f"skill.{target.replace('.', '_')}.{goals}.{op_codes}"
