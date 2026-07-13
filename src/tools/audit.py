"""Structured audit log for the SRAG report workflow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class AuditLogger:
    """Append-only JSONL logger used by the LangGraph orchestrator."""

    def __init__(self, output_dir: str = "outputs", run_id: str | None = None) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = Path(output_dir) / f"audit_{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, node: str, payload: dict[str, Any] | None = None) -> str:
        event_id = str(uuid4())
        event = {
            "event_id": event_id,
            "run_id": self.run_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "node": node,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event_id
