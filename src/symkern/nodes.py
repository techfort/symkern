from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Node:
    node_id: str
    op_id: str = ""
    op_code: int | None = None
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    execution_mode: str = "bulk"
    metadata: dict[str, object] = field(default_factory=dict)
    provenance: dict[str, object] = field(default_factory=dict)
    state_refs: list[str] = field(default_factory=list)
    valid: bool = True

    def to_dict(self) -> dict[str, object]:
        payload = {
            "node_id": self.node_id,
            "op_code": self.op_code,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "execution_mode": self.execution_mode,
            "metadata": dict(self.metadata),
            "provenance": dict(self.provenance),
            "state_refs": list(self.state_refs),
            "valid": self.valid,
        }
        if self.op_id:
            payload["op_id"] = self.op_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Node":
        return cls(
            node_id=str(data["node_id"]),
            op_id=str(data.get("op_id", "")),
            op_code=int(data["op_code"]) if data.get("op_code") is not None else None,
            inputs=list(data.get("inputs", [])),
            outputs=list(data.get("outputs", [])),
            execution_mode=str(data.get("execution_mode", "bulk")),
            metadata=dict(data.get("metadata", {})),
            provenance=dict(data.get("provenance", {})),
            state_refs=list(data.get("state_refs", [])),
            valid=bool(data.get("valid", True)),
        )


@dataclass(slots=True)
class PlanGraph:
    plan_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    state_bindings: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        self.nodes.append(node)

    def add_edge(self, source: str, target: str) -> None:
        self.edges.append((source, target))

    def ordered_nodes(self) -> list[Node]:
        node_map = {node.node_id: node for node in self.nodes}
        incoming = {node.node_id: 0 for node in self.nodes}
        outgoing: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        for source, target in self.edges:
            outgoing[source].append(target)
            incoming[target] = incoming.get(target, 0) + 1

        ready = [node_id for node_id, degree in incoming.items() if degree == 0]
        order: list[Node] = []
        while ready:
            node_id = ready.pop(0)
            order.append(node_map[node_id])
            for target in outgoing.get(node_id, []):
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)

        return order if len(order) == len(self.nodes) else list(self.nodes)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [[source, target] for source, target in self.edges],
            "state_bindings": dict(self.state_bindings),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PlanGraph":
        return cls(
            plan_id=str(data["plan_id"]),
            nodes=[Node.from_dict(node) for node in data.get("nodes", [])],
            edges=[(str(source), str(target)) for source, target in data.get("edges", [])],
            state_bindings=dict(data.get("state_bindings", {})),
            metadata=dict(data.get("metadata", {})),
        )
