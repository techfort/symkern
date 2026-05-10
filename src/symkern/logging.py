from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TraceEvent:
    stage: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"stage": self.stage, "message": self.message, "payload": dict(self.payload)}


@dataclass(slots=True)
class ExecutionTrace:
    events: list[TraceEvent] = field(default_factory=list)

    def record(self, stage: str, message: str, **payload: object) -> None:
        self.events.append(TraceEvent(stage=stage, message=message, payload=dict(payload)))

    def to_dict(self) -> dict[str, object]:
        return {"events": [event.to_dict() for event in self.events]}
