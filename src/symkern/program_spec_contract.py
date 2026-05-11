from __future__ import annotations

import json
from importlib import resources

from symkern.machine_language import MachineLanguage
from symkern.prompt_layer import PROGRAM_SPEC_VERSION


def load_program_spec_schema() -> dict[str, object]:
    text = resources.files("symkern.resources").joinpath("program_spec_schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def build_translator_context_bundle(language: MachineLanguage | None = None) -> dict[str, object]:
    runtime = language or MachineLanguage()
    return {
        "kind": "symkern.translator-context",
        "schema_version": "symkern.translator-context/v1alpha1",
        "program_spec_schema": load_program_spec_schema(),
        "operator_registry": runtime.capability_catalog(),
        "creation_rules": [
            "Return only a ProgramSpec JSON object that matches the provided schema.",
            "Do not substitute one task for another.",
            "If the request cannot be expressed faithfully with the available operators, emit blocking synthesis_gaps.",
            "Do not generate executable code.",
            "Use transformation kinds and outputs that are grounded in the operator registry.",
        ],
    }


def build_program_spec_translation_instructions(language: MachineLanguage | None = None) -> str:
    context_bundle = build_translator_context_bundle(language)
    operator_catalog = context_bundle["operator_registry"]
    operator_lines = [
        f"- {item['capability_id']}: inputs={item['signature']['inputs']} outputs={item['signature']['outputs']} category={item['metadata'].get('category', 'unknown')} description={item['description']}"
        for item in operator_catalog["capabilities"]
    ]
    schema = context_bundle["program_spec_schema"]
    required_keys = ", ".join(list(schema.get("required", [])))
    return (
        "Translate the user request into valid Symkern ProgramSpec JSON only. "
        f"Use spec_version '{PROGRAM_SPEC_VERSION}'. "
        f"Return a JSON object with required keys: {required_keys}. "
        "Do not substitute a different task. "
        "If the request cannot be expressed faithfully using the available operator registry, keep the requested outputs and transformations visible and add blocking synthesis_gaps. "
        "Use strict JSON with double quotes only. "
        "Available operator catalog:\n"
        + "\n".join(operator_lines)
    )