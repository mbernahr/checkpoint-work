#!/usr/bin/env python3
"""Capture Claude Code status-line rate limits for checkpoint-work."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


DEFAULT_CACHE = Path.home() / ".claude" / "checkpoint-work-usage.json"


def cache_path() -> Path:
    configured = os.environ.get("CHECKPOINT_WORK_CLAUDE_CACHE")
    return Path(configured).expanduser() if configured else DEFAULT_CACHE


def write_snapshot(data: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "captured_at": time.time(),
        "rate_limits": data.get("rate_limits"),
    }
    handle, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".", dir=destination.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.write("\n")
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def status_text(data: dict[str, Any]) -> str:
    parts = ["Checkpoint Work"]
    rate_limits = data.get("rate_limits")
    if isinstance(rate_limits, dict):
        for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
            window = rate_limits.get(key)
            used = window.get("used_percentage") if isinstance(window, dict) else None
            if isinstance(used, (int, float)):
                parts.append(f"{label} {max(0, 100 - used):g}% left")
    if len(parts) == 1:
        parts.append("usage unavailable")
    return " · ".join(parts)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("status-line input is not a JSON object")
        write_snapshot(data, cache_path())
        print(status_text(data))
    except Exception as exc:
        print(f"Checkpoint Work · capture error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
