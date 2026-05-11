"""
Contract and prompt builder for dynamic operator synthesis.

Symkern sends a synthesis request to the LLM for each missing operator_id.
The LLM returns either:
  - OperatorCompositionSpec: chain of existing operator_ids (no code generated)
  - OperatorHandlerSpec: structured algorithm_steps JSON (Symkern generates code)

The LLM never writes executable Python directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Specs returned by the LLM
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OperatorCompositionSpec:
    operator_id: str
    inputs: list[str]
    outputs: list[str]
    description: str
    steps: list[dict[str, object]]       # each: {operator_id, inputs, outputs, metadata}
    implementation_kind: str = "composition"

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "OperatorCompositionSpec":
        return cls(
            operator_id=str(payload.get("operator_id", "")).strip(),
            inputs=[str(i) for i in list(payload.get("inputs", []))],
            outputs=[str(o) for o in list(payload.get("outputs", []))],
            description=str(payload.get("description", "")),
            steps=[dict(s) for s in list(payload.get("composition_steps", []))],
            implementation_kind=str(payload.get("implementation_kind", "composition")),
        )


@dataclass(slots=True)
class OperatorHandlerSpec:
    operator_id: str
    inputs: list[str]
    outputs: list[str]
    description: str
    algorithm_steps: list[dict[str, object]]
    implementation_kind: str = "handler_spec"

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "OperatorHandlerSpec":
        return cls(
            operator_id=str(payload.get("operator_id", "")).strip(),
            inputs=[str(i) for i in list(payload.get("inputs", []))],
            outputs=[str(o) for o in list(payload.get("outputs", []))],
            description=str(payload.get("description", "")),
            algorithm_steps=[dict(s) for s in list(payload.get("algorithm_steps", []))],
            implementation_kind=str(payload.get("implementation_kind", "handler_spec")),
        )


def parse_synthesis_response(payload: dict[str, object]) -> OperatorCompositionSpec | OperatorHandlerSpec:
    kind = str(payload.get("implementation_kind", "")).strip()
    if kind == "composition":
        return OperatorCompositionSpec.from_dict(payload)
    if kind == "handler_spec":
        return OperatorHandlerSpec.from_dict(payload)
    # Infer from presence of keys
    if "composition_steps" in payload:
        return OperatorCompositionSpec.from_dict(payload)
    if "algorithm_steps" in payload:
        return OperatorHandlerSpec.from_dict(payload)
    raise ValueError(
        f"Cannot parse synthesis response: missing 'implementation_kind' and neither "
        f"'composition_steps' nor 'algorithm_steps' present. Payload keys: {list(payload)}"
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_operator_synthesis_instructions(
    operator_id: str,
    existing_operator_ids: list[str],
    program_spec_context: dict[str, object] | None = None,
) -> str:
    existing_json = json.dumps(sorted(existing_operator_ids), indent=2)
    context_block = ""
    if program_spec_context:
        context_block = f"\n\nThe operator is needed by this program:\n{json.dumps(program_spec_context, indent=2)}"

    return f"""You are the operator synthesis engine for Symkern, a machine-first symbolic constraint kernel.

You must produce an implementation specification for the missing operator: "{operator_id}".

== Available existing operators ==
{existing_json}

== Your task ==
Return a JSON object describing how to implement "{operator_id}". Choose ONE of two implementation kinds:

--- Kind 1: composition ---
Use this when the operator can be expressed as a pipeline of EXISTING operators listed above.
Return:
{{
  "operator_id": "{operator_id}",
  "inputs": ["<input_name>", ...],
  "outputs": ["<output_name>", ...],
  "description": "<one sentence>",
  "implementation_kind": "composition",
  "composition_steps": [
    {{ "operator_id": "<existing_op>", "inputs": ["<name>"], "outputs": ["<name>"], "metadata": {{}} }},
    ...
  ]
}}

--- Kind 2: handler_spec ---
Use this when the operator performs an atomic computation that cannot be expressed through existing operators.
Return:
{{
  "operator_id": "{operator_id}",
  "inputs": ["<input_name>", ...],
  "outputs": ["<output_name>", ...],
  "description": "<one sentence>",
  "implementation_kind": "handler_spec",
  "algorithm_steps": [
    {{ "assign": "<var>", "from_metadata": "<key>", "default": <value> }},
    {{ "assign": "<var>", "from_context": "<key>" }},
    {{ "assign": "<var>", "expr": "<python expression using approved symbols only>" }},
    {{ "assign": "<output_name>", "list_comprehension": {{ "outer": "<range_expr>", "value_expr": "<element_expr>" }} }},
    {{ "assign": "<output_name>", "nested_list_comprehension": {{ "outer": "<range_expr>", "inner": "<range_expr>", "value_expr": "<element_expr>" }} }}
  ]
}}

Approved symbols for expressions: random, math, int, float, str, bool, list, dict, set, tuple,
range, len, sum, min, max, abs, round, sorted, reversed, enumerate, zip, any, all, statistics.

== Rules ==
- Return ONLY valid JSON. No prose, no markdown.
- All referenced operator_ids in composition_steps MUST be from the available list above.
- algorithm_steps expressions must use only approved symbols. No import, no open, no exec, no eval.
- Output variable names in algorithm_steps must match the "outputs" field.
- CRITICAL: Every input variable used in an "expr" step MUST be declared FIRST with a "from_context" or "from_metadata" step. You cannot reference a variable in an expr unless a prior step assigns it.
- The last step must assign the primary output.{context_block}
"""
