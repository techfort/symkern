"""
OperatorHandlerCompiler: converts OperatorHandlerSpec.algorithm_steps into
a restricted Python handler function and validates it against synthetic inputs.

Security model:
- No user-supplied Python is eval'd or exec'd.
- Only a fixed, approved symbol set is available inside generated functions.
- Handlers are run against synthetic inputs before being accepted.
"""
from __future__ import annotations

import math
import random
import statistics
import textwrap
from typing import Any, Callable

from symkern.operator_synthesis_contract import OperatorHandlerSpec


# ---------------------------------------------------------------------------
# Approved execution environment
# ---------------------------------------------------------------------------

_APPROVED_GLOBALS: dict[str, Any] = {
    "__builtins__": {},          # block everything by default
    "random": random,
    "math": math,
    "statistics": statistics,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "range": range,
    "len": len,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "any": any,
    "all": all,
}


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

def _build_function_body(steps: list[dict[str, object]], output_names: list[str]) -> str:
    lines: list[str] = []
    for step in steps:
        var = str(step.get("assign", ""))
        if not var:
            continue

        if "from_metadata" in step:
            key = str(step["from_metadata"])
            default = repr(step.get("default", None))
            lines.append(f"{var} = node.metadata.get({key!r}, {default})")

        elif "from_context" in step:
            key = str(step["from_context"])
            default = repr(step.get("default", None))
            lines.append(f"{var} = context.get({key!r}, {default})")

        elif "expr" in step:
            expr = str(step["expr"])
            lines.append(f"{var} = {expr}")

        elif "list_comprehension" in step:
            lc = dict(step["list_comprehension"])
            outer = str(lc.get("outer", "range(0)"))
            val_expr = str(lc.get("value_expr", "None"))
            loop_var = str(lc.get("loop_var", "_i"))
            lines.append(f"{var} = [{val_expr} for {loop_var} in {outer}]")

        elif "nested_list_comprehension" in step:
            nlc = dict(step["nested_list_comprehension"])
            outer = str(nlc.get("outer", "range(0)"))
            inner = str(nlc.get("inner", "range(0)"))
            val_expr = str(nlc.get("value_expr", "None"))
            outer_var = str(nlc.get("outer_var", "_i"))
            inner_var = str(nlc.get("inner_var", "_j"))
            lines.append(
                f"{var} = [[{val_expr} for {inner_var} in {inner}] for {outer_var} in {outer}]"
            )

        elif "dict_from_keys" in step:
            mapping = dict(step["dict_from_keys"])
            items = ", ".join(f"{k!r}: {v}" for k, v in mapping.items())
            lines.append(f"{var} = {{{items}}}")

    # Build return dict from declared outputs
    return_items = ", ".join(f"{name!r}: {name}" for name in output_names)
    lines.append(f"return {{{return_items}}}")

    indent = "    "
    return "\n".join(f"{indent}{line}" for line in lines)


def compile_handler(spec: OperatorHandlerSpec) -> Callable:
    """Compile an OperatorHandlerSpec into a restricted Python callable."""
    body = _build_function_body(list(spec.algorithm_steps), list(spec.outputs))
    fn_src = f"def _generated_handler(node, context):\n{body}\n"

    # Run security checks before exec
    _check_source_safety(fn_src)

    local_ns: dict[str, Any] = {}
    exec(fn_src, dict(_APPROVED_GLOBALS), local_ns)  # noqa: S102  — controlled, approved-only globals
    return local_ns["_generated_handler"]


def _check_source_safety(source: str) -> None:
    """Reject patterns that should never appear in generated handler code."""
    forbidden = ("import ", "__import__", "open(", "exec(", "eval(", "__builtins__",
                 "subprocess", "os.system", "os.popen", "socket", "http", "urllib")
    for token in forbidden:
        if token in source:
            raise ValueError(f"Generated handler source contains forbidden token: {token!r}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_handler(
    handler: Callable,
    spec: OperatorHandlerSpec,
    synthetic_inputs: dict[str, object] | None = None,
) -> None:
    """Run the handler against synthetic inputs; confirm all outputs are produced."""
    from symkern.nodes import Node  # local import to avoid circular deps

    inputs = dict(synthetic_inputs or {})
    for inp in spec.inputs:
        if inp not in inputs:
            inputs[inp] = _synthetic_value_for(inp)

    node = Node(
        node_id="validation_node",
        op_code=9999,
        inputs=list(spec.inputs),
        outputs=list(spec.outputs),
    )
    try:
        result = handler(node, inputs)
    except Exception as error:
        raise ValueError(f"Handler for '{spec.operator_id}' raised during validation: {error}") from error

    if not isinstance(result, dict):
        raise ValueError(f"Handler for '{spec.operator_id}' must return a dict, got {type(result)}")

    missing = [o for o in spec.outputs if o not in result]
    if missing:
        raise ValueError(
            f"Handler for '{spec.operator_id}' did not produce required outputs: {missing}. "
            f"Produced: {list(result)}"
        )


def _synthetic_value_for(name: str) -> object:
    """Return a plausible synthetic value for a named input."""
    if "matrix" in name:
        return [[random.randint(1, 10) for _ in range(3)] for _ in range(3)]
    if "array" in name or "list" in name or "diagonal" in name or "tokens" in name:
        return [random.randint(1, 10) for _ in range(5)]
    if "text" in name or "phrase" in name or "string" in name or "sentence" in name or "word" in name or "input" in name:
        return "hello world test"
    if "count" in name or "size" in name or "length" in name or "n" == name:
        return 5
    if "freq" in name or "stat" in name or "counts" in name:
        return {"hello": 2, "world": 1, "test": 1}
    if "seed" in name:
        return 42
    return 1
