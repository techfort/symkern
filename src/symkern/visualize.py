from __future__ import annotations

from symkern.nodes import PlanGraph


def render_plan_graph(plan: PlanGraph) -> str:
    lines = [f"Plan {plan.plan_id}"]
    for node in plan.ordered_nodes():
        op_label = f"opcode {node.op_code}" if node.op_code is not None else "unknown_op"
        lines.append(f"- {node.node_id}: {op_label} -> {', '.join(node.outputs) or 'no outputs'}")
    return "\n".join(lines)
