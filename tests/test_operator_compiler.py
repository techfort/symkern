"""Unit tests for operator_compiler: compile_handler, validate_handler, safety checks."""
from __future__ import annotations

import pytest
from symkern.operator_compiler import compile_handler, validate_handler, _check_source_safety
from symkern.operator_synthesis_contract import OperatorHandlerSpec


def _make_spec(operator_id: str, inputs: list[str], outputs: list[str], steps: list[dict]) -> OperatorHandlerSpec:
    return OperatorHandlerSpec(
        operator_id=operator_id,
        inputs=inputs,
        outputs=outputs,
        description="test",
        algorithm_steps=steps,
    )


# ---------------------------------------------------------------------------
# compile_handler
# ---------------------------------------------------------------------------

def test_compile_handler_expr_step():
    spec = _make_spec(
        "test.double",
        inputs=["x"],
        outputs=["result"],
        steps=[
            {"assign": "x", "from_context": "x"},
            {"assign": "result", "expr": "x * 2"},
        ],
    )
    handler = compile_handler(spec)
    from symkern.nodes import Node
    node = Node("n1", op_code=999, inputs=["x"], outputs=["result"])
    out = handler(node, {"x": 5})
    assert out["result"] == 10


def test_compile_handler_from_metadata():
    spec = _make_spec(
        "test.threshold",
        inputs=[],
        outputs=["threshold"],
        steps=[
            {"assign": "threshold", "from_metadata": "threshold", "default": 1.0},
        ],
    )
    handler = compile_handler(spec)
    from symkern.nodes import Node
    node = Node("n1", op_code=999, inputs=[], outputs=["threshold"], metadata={"threshold": 3.5})
    out = handler(node, {})
    assert out["threshold"] == 3.5


def test_compile_handler_list_comprehension():
    spec = _make_spec(
        "test.squares",
        inputs=["n"],
        outputs=["squares"],
        steps=[
            {"assign": "n", "from_context": "n"},
            {"assign": "squares", "list_comprehension": {"outer": "range(n)", "loop_var": "i", "value_expr": "i * i"}},
        ],
    )
    handler = compile_handler(spec)
    from symkern.nodes import Node
    node = Node("n1", op_code=999, inputs=["n"], outputs=["squares"])
    out = handler(node, {"n": 4})
    assert out["squares"] == [0, 1, 4, 9]


def test_compile_handler_nested_list_comprehension():
    spec = _make_spec(
        "test.matrix",
        inputs=["rows", "cols"],
        outputs=["matrix"],
        steps=[
            {"assign": "rows", "from_context": "rows"},
            {"assign": "cols", "from_context": "cols"},
            {
                "assign": "matrix",
                "nested_list_comprehension": {
                    "outer": "range(rows)",
                    "outer_var": "r",
                    "inner": "range(cols)",
                    "inner_var": "c",
                    "value_expr": "r * cols + c",
                },
            },
        ],
    )
    handler = compile_handler(spec)
    from symkern.nodes import Node
    node = Node("n1", op_code=999, inputs=["rows", "cols"], outputs=["matrix"])
    out = handler(node, {"rows": 2, "cols": 3})
    assert out["matrix"] == [[0, 1, 2], [3, 4, 5]]


def test_compile_handler_dict_from_keys():
    spec = _make_spec(
        "test.info",
        inputs=["value"],
        outputs=["info"],
        steps=[
            {"assign": "value", "from_context": "value"},
            {"assign": "info", "dict_from_keys": {"raw": "value", "doubled": "value * 2"}},
        ],
    )
    handler = compile_handler(spec)
    from symkern.nodes import Node
    node = Node("n1", op_code=999, inputs=["value"], outputs=["info"])
    out = handler(node, {"value": 7})
    assert out["info"] == {"raw": 7, "doubled": 14}


# ---------------------------------------------------------------------------
# validate_handler
# ---------------------------------------------------------------------------

def test_validate_handler_passes_when_all_outputs_present():
    spec = _make_spec(
        "test.identity",
        inputs=["x"],
        outputs=["y"],
        steps=[
            {"assign": "x", "from_context": "x"},
            {"assign": "y", "expr": "x"},
        ],
    )
    handler = compile_handler(spec)
    validate_handler(handler, spec)  # should not raise


def test_validate_handler_raises_when_output_missing():
    spec = _make_spec(
        "test.missing_output",
        inputs=["x"],
        outputs=["y", "z"],   # z is never produced
        steps=[
            {"assign": "x", "from_context": "x"},
            {"assign": "y", "expr": "x"},
        ],
    )
    handler = compile_handler(spec)
    with pytest.raises(ValueError, match="z"):
        validate_handler(handler, spec)


def test_validate_handler_raises_when_handler_crashes():
    """A handler that raises should be caught by validate_handler."""
    spec = _make_spec(
        "test.crasher",
        inputs=["x"],
        outputs=["result"],
        steps=[
            {"assign": "x", "from_context": "x"},
            # Division by zero when x=0 (synthetic input for "x" will be 0 or some int)
            {"assign": "result", "expr": "1 / 0"},
        ],
    )
    handler = compile_handler(spec)
    with pytest.raises(ValueError, match="raised during validation"):
        validate_handler(handler, spec)


# ---------------------------------------------------------------------------
# _check_source_safety
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dangerous", [
    "import os",
    "__import__('os')",
    "open('/etc/passwd')",
    "exec('x=1')",
    "eval('1+1')",
    "__builtins__['open']",
    "subprocess.run([])",
    "os.system('ls')",
    "os.popen('id')",
    "socket.connect()",
    "http.client.HTTPConnection()",
    "urllib.request.urlopen()",
])
def test_safety_check_blocks_forbidden_tokens(dangerous):
    with pytest.raises(ValueError, match="forbidden token"):
        _check_source_safety(f"def f():\n    {dangerous}")


def test_safety_check_passes_clean_code():
    _check_source_safety("def f(node, context):\n    x = context.get('x', 0)\n    return {'x': x}\n")
