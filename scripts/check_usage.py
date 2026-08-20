#!/usr/bin/env python3
"""Check Codex or Claude Code usage before starting another checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_CLAUDE_CACHE = Path.home() / ".claude" / "checkpoint-work-usage.json"


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(exit_code)


def find_codex() -> str:
    configured = os.environ.get("CHECKPOINT_WORK_CODEX_BIN")
    if configured:
        return configured
    discovered = shutil.which("codex")
    if discovered:
        return discovered
    mac_app_binary = "/Applications/Codex.app/Contents/Resources/codex"
    if os.path.isfile(mac_app_binary):
        return mac_app_binary
    raise RuntimeError("Codex CLI executable not found")


def send_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("Codex app-server stdin is unavailable")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def wait_for_response(
    process: subprocess.Popen[str], request_id: int, timeout_seconds: float
) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("Codex app-server stdout is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            if not selector.select(remaining):
                break
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"app-server error: {message['error']}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("app-server returned no result object")
                return result
    finally:
        selector.close()
    raise RuntimeError(f"timed out waiting for app-server response {request_id}")


def read_codex_rate_limits(timeout_seconds: float) -> dict[str, Any]:
    process = subprocess.Popen(
        [find_codex(), "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        send_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "checkpoint-work", "version": "2.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        wait_for_response(process, 1, timeout_seconds)
        send_message(process, {"method": "initialized"})
        send_message(process, {"id": 2, "method": "account/rateLimits/read"})
        return wait_for_response(process, 2, timeout_seconds)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def select_codex_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    by_id = response.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        codex_snapshot = by_id.get("codex")
        if isinstance(codex_snapshot, dict):
            return codex_snapshot
    legacy = response.get("rateLimits")
    if isinstance(legacy, dict):
        return legacy
    raise RuntimeError("rate-limit response contains no Codex snapshot")


def add_reserve_decision(
    result: dict[str, Any], reserve: float | None
) -> dict[str, Any]:
    if reserve is not None:
        result["reserve_percent"] = reserve
        result["may_start_next_checkpoint"] = result["remaining_percent"] > reserve
    return result


def summarize_codex(snapshot: dict[str, Any], reserve: float | None) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    for name in ("primary", "secondary"):
        window = snapshot.get(name)
        if not isinstance(window, dict):
            continue
        used = window.get("usedPercent")
        if not isinstance(used, (int, float)):
            continue
        windows.append(
            {
                "name": name,
                "used_percent": used,
                "remaining_percent": max(0, 100 - used),
                "window_duration_minutes": window.get("windowDurationMins"),
                "resets_at": window.get("resetsAt"),
            }
        )

    hard_limit_reached = bool(
        snapshot.get("spendControlReached") or snapshot.get("rateLimitReachedType")
    )
    if hard_limit_reached:
        remaining: float = 0
        limiting_window = "hard_limit"
    elif windows:
        limiting = min(windows, key=lambda item: item["remaining_percent"])
        remaining = limiting["remaining_percent"]
        limiting_window = str(limiting["name"])
    else:
        credits = snapshot.get("credits")
        if isinstance(credits, dict) and credits.get("unlimited") is True:
            remaining = 100
            limiting_window = "unlimited"
        else:
            raise RuntimeError("rate-limit snapshot contains no measurable window")

    return add_reserve_decision(
        {
            "ok": True,
            "provider": "codex",
            "limit_id": snapshot.get("limitId", "codex"),
            "plan_type": snapshot.get("planType"),
            "remaining_percent": remaining,
            "limiting_window": limiting_window,
            "windows": windows,
        },
        reserve,
    )


def claude_cache_path(configured: str | None = None) -> Path:
    value = configured or os.environ.get("CHECKPOINT_WORK_CLAUDE_CACHE")
    return Path(value).expanduser() if value else DEFAULT_CLAUDE_CACHE


def read_claude_snapshot(cache: Path, max_age_seconds: float) -> dict[str, Any]:
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Claude usage cache not found; run scripts/setup_claude_statusline.py "
            "and send one Claude Code message"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read Claude usage cache: {exc}") from exc

    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, (int, float)):
        raise RuntimeError("Claude usage cache has no capture timestamp")
    age = max(0.0, time.time() - captured_at)
    if age > max_age_seconds:
        raise RuntimeError(
            f"Claude usage cache is stale ({int(age)}s old, maximum {int(max_age_seconds)}s)"
        )
    rate_limits = payload.get("rate_limits")
    if not isinstance(rate_limits, dict):
        raise RuntimeError("Claude rate-limit data is unavailable for this session or plan")
    return {"captured_at": captured_at, "cache_age_seconds": age, **rate_limits}


def summarize_claude(snapshot: dict[str, Any], reserve: float | None) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    for name in ("five_hour", "seven_day"):
        window = snapshot.get(name)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percentage")
        if not isinstance(used, (int, float)):
            continue
        windows.append(
            {
                "name": name,
                "used_percent": used,
                "remaining_percent": max(0, 100 - used),
                "resets_at": window.get("resets_at"),
            }
        )
    if not windows:
        raise RuntimeError("Claude usage cache contains no measurable rate-limit window")
    limiting = min(windows, key=lambda item: item["remaining_percent"])
    return add_reserve_decision(
        {
            "ok": True,
            "provider": "claude",
            "remaining_percent": limiting["remaining_percent"],
            "limiting_window": limiting["name"],
            "captured_at": snapshot.get("captured_at"),
            "cache_age_seconds": round(float(snapshot.get("cache_age_seconds", 0)), 1),
            "windows": windows,
        },
        reserve,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether another checkpoint may start without crossing a usage reserve."
    )
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    parser.add_argument(
        "--reserve", type=float, help="Remaining percentage to preserve (0-100)."
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--claude-cache", help="Override the Claude cache path.")
    parser.add_argument(
        "--max-cache-age",
        type=float,
        default=900.0,
        help="Maximum acceptable Claude cache age in seconds (default: 900).",
    )
    args = parser.parse_args()
    if args.reserve is not None and not 0 <= args.reserve <= 100:
        parser.error("--reserve must be between 0 and 100")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.max_cache_age <= 0:
        parser.error("--max-cache-age must be greater than zero")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.provider == "claude":
            snapshot = read_claude_snapshot(
                claude_cache_path(args.claude_cache), args.max_cache_age
            )
            emit(summarize_claude(snapshot, args.reserve))
        response = read_codex_rate_limits(args.timeout)
        emit(summarize_codex(select_codex_snapshot(response), args.reserve))
    except Exception as exc:
        emit({"ok": False, "provider": args.provider, "error": str(exc)}, exit_code=2)


if __name__ == "__main__":
    main()
