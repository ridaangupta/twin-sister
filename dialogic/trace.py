"""Append-only JSONL trace writers for a run directory.

All writes happen on the event-loop thread and are flushed immediately, so
rows from concurrent coroutines never interleave and a crashed run keeps
everything written so far.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Tracer:
    def __init__(self, run_dir: str | Path, run_id: str):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._files: dict[str, IO[str]] = {}
        self._seen_prompts: set[str] = set()

    def write(self, stream: str, row: dict[str, Any]) -> None:
        f = self._files.get(stream)
        if f is None:
            f = self._files[stream] = open(self.run_dir / f"{stream}.jsonl", "a", encoding="utf-8")
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        f.flush()

    def call(self, row: dict[str, Any]) -> None:
        self.write("calls", {"run_id": self.run_id, **row, "ts": utc_now()})

    def prompt(self, prompt_hash: str, messages: list[dict[str, Any]]) -> None:
        if prompt_hash in self._seen_prompts:
            return
        self._seen_prompts.add(prompt_hash)
        self.write("prompts", {"prompt_hash": prompt_hash, "messages": messages})

    def close(self) -> None:
        for f in self._files.values():
            f.close()
        self._files.clear()

    def __enter__(self) -> Tracer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
