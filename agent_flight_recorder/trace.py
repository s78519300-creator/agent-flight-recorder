"""Load and validate agent traces stored as JSON Lines."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVENT_TYPES = {"user", "llm", "tool_call", "tool_result", "final"}


class TraceError(ValueError):
    """Raised when a trace file cannot be trusted enough to audit."""


@dataclass(frozen=True)
class Event:
    run_id: str
    step: int
    type: str
    name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    output: Any = None
    error: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class Run:
    run_id: str
    events: tuple[Event, ...]

    def of_type(self, *types: str) -> list[Event]:
        return [event for event in self.events if event.type in types]


def _parse_line(raw: str, source: str, line_no: int) -> Event:
    where = f"{source}:{line_no}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TraceError(f"{where}: invalid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise TraceError(f"{where}: each line must be a JSON object")
    for key in ("run_id", "step", "type"):
        if key not in data:
            raise TraceError(f"{where}: missing required field '{key}'")
    if data["type"] not in EVENT_TYPES:
        raise TraceError(f"{where}: unknown event type '{data['type']}'")
    if not isinstance(data["step"], int) or isinstance(data["step"], bool):
        raise TraceError(f"{where}: 'step' must be an integer")
    if data["type"] in {"tool_call", "tool_result"} and not data.get("name"):
        raise TraceError(f"{where}: {data['type']} events need a tool 'name'")
    args = data.get("args") or {}
    if not isinstance(args, dict):
        raise TraceError(f"{where}: 'args' must be an object")
    return Event(
        run_id=str(data["run_id"]),
        step=data["step"],
        type=data["type"],
        name=data.get("name"),
        args=args,
        text=str(data.get("text") or ""),
        output=data.get("output"),
        error=data.get("error"),
        tokens=int(data.get("tokens") or 0),
        cost_usd=float(data.get("cost_usd") or 0.0),
    )


def load_runs(path: str | Path) -> list[Run]:
    """Read a JSONL trace file and return one ``Run`` per ``run_id``.

    Malformed input raises ``TraceError`` instead of being skipped: an audit
    that silently ignores part of a trace would report false confidence.
    """
    source = Path(path)
    grouped: dict[str, list[Event]] = defaultdict(list)
    with source.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if raw.strip():
                event = _parse_line(raw, source.name, line_no)
                grouped[event.run_id].append(event)
    runs = []
    for run_id, events in grouped.items():
        steps = [event.step for event in events]
        if len(steps) != len(set(steps)):
            raise TraceError(f"{source.name}: run '{run_id}' has duplicate step numbers")
        runs.append(Run(run_id, tuple(sorted(events, key=lambda event: event.step))))
    return runs
