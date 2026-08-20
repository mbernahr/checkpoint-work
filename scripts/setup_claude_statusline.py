#!/usr/bin/env python3
"""Configure Claude Code to capture its official rate-limit status fields."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CAPTURE_SCRIPT = Path(__file__).resolve().with_name("capture_claude_usage.py")


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return settings


def configure(settings: dict[str, Any]) -> dict[str, Any]:
    if "statusLine" in settings:
        raise RuntimeError(
            "Claude Code already has a statusLine configuration. It was not changed. "
            "See README.md > Existing Claude status line for safe manual integration."
        )
    updated = dict(settings)
    if os.name == "nt":
        command = subprocess.list2cmdline([sys.executable, str(CAPTURE_SCRIPT)])
    else:
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(CAPTURE_SCRIPT))}"
    updated["statusLine"] = {
        "type": "command",
        "command": command,
        "padding": 1,
        "refreshInterval": 60,
    }
    return updated


def main() -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings = load_settings(SETTINGS_PATH)
        updated = configure(settings)
        if SETTINGS_PATH.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = SETTINGS_PATH.with_name(f"settings.json.checkpoint-work-{stamp}.bak")
            shutil.copy2(SETTINGS_PATH, backup)
            print(f"Backup: {backup}")
        SETTINGS_PATH.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Configured: {SETTINGS_PATH}")
        print("Restart Claude Code, then send one message to populate the usage cache.")
    except Exception as exc:
        print(f"Setup stopped: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
