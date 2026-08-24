#!/usr/bin/env python3
"""Check Codex or Claude Code usage before starting another checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DEFAULT_CLAUDE_CACHE = Path.home() / ".claude" / "checkpoint-work-usage.json"
DEFAULT_COST_STATE_DIR = Path.home() / ".checkpoint-work" / "cost-runs"
COST_QUALITIES = ("reported", "calculated", "estimated")
COST_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


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
    if sys.platform == "darwin":
        mac_app_binary = "/Applications/Codex.app/Contents/Resources/codex"
        if os.path.isfile(mac_app_binary):
            return mac_app_binary
    raise RuntimeError(
        "Codex CLI executable not found on PATH; set CHECKPOINT_WORK_CODEX_BIN "
        "to its full path"
    )


def send_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("Codex app-server stdin is unavailable")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


class JsonLineReader:
    """Read app-server messages without relying on platform-specific pipe selectors."""

    def __init__(self, stream: Any) -> None:
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream: Any) -> None:
        try:
            for line in stream:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self.messages.put(message)
        finally:
            self.messages.put(None)

    def wait_for_response(
        self, request_id: int, timeout_seconds: float
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                break
            if message is None:
                break
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"app-server error: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("app-server returned no result object")
            return result
        raise RuntimeError(f"timed out waiting for app-server response {request_id}")


def read_codex_data(
    timeout_seconds: float, thread_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    process = subprocess.Popen(
        [find_codex(), "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("Codex app-server stdout is unavailable")
        reader = JsonLineReader(process.stdout)
        send_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "checkpoint-work", "version": "2.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        reader.wait_for_response(1, timeout_seconds)
        send_message(process, {"method": "initialized"})
        send_message(process, {"id": 2, "method": "account/rateLimits/read"})
        rate_limits = reader.wait_for_response(2, timeout_seconds)
        if not thread_id:
            return rate_limits, None
        send_message(
            process,
            {
                "id": 3,
                "method": "account/usage/read",
                "params": {"threadId": thread_id},
            },
        )
        return rate_limits, reader.wait_for_response(3, timeout_seconds)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def read_codex_rate_limits(timeout_seconds: float) -> dict[str, Any]:
    rate_limits, _ = read_codex_data(timeout_seconds)
    return rate_limits


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


def window_identity(provider: str, name: str, resets_at: Any) -> str | None:
    """Identify a concrete rate-limit window without guessing when it resets."""
    if resets_at is None:
        return None
    return f"{provider}:{name}:{resets_at}"


def codex_cost_snapshot(response: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    thread_usage = response.get("threadUsage")
    if not isinstance(thread_usage, dict):
        return None
    usd_micros = thread_usage.get("estimatedUsageUsdMicros")
    thread_id = thread_usage.get("threadId")
    if not isinstance(usd_micros, int) or usd_micros < 0:
        return None
    return {
        "total_cost_usd": float(Decimal(usd_micros) / Decimal(1_000_000)),
        "quality": "estimated",
        "source": "codex_app_server",
        "scope": "thread",
        "source_id": thread_id,
    }


def decimal_usd(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"{field} is not a valid USD amount") from exc
    if not parsed.is_finite() or parsed < 0:
        raise RuntimeError(f"{field} must be a finite non-negative USD amount")
    return parsed


def cost_state_path(directory: Path, run_id: str) -> Path:
    if not COST_RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError(
            "cost run id must contain only letters, digits, dots, underscores, or hyphens"
        )
    return directory / f"{run_id}.json"


def write_json_atomic(destination: Path, payload: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
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


def read_cost_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read cost run state: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("cost run state has an unsupported schema")
    return payload


def unavailable_cost_result(
    result: dict[str, Any], maximum: Decimal, reason: str, run_id: str
) -> dict[str, Any]:
    result.update(
        {
            "max_cost_usd": float(maximum),
            "run_cost_usd": None,
            "cost_quality": "unavailable",
            "cost_source": None,
            "cost_scope": None,
            "cost_run_id": run_id,
            "cost_limit_allows_start": False,
            "cost_error": reason,
            "may_start_next_checkpoint": False,
        }
    )
    return result


def apply_cost_guard(
    result: dict[str, Any],
    maximum: float | None,
    run_id: str | None,
    cost_snapshot: dict[str, Any] | None,
    state_directory: Path,
) -> dict[str, Any]:
    if maximum is None:
        return result
    max_cost = decimal_usd(maximum, "maximum cost")
    if not run_id:
        raise RuntimeError("--cost-run-id is required with --max-cost-usd")
    state_path = cost_state_path(state_directory, run_id)
    if not isinstance(cost_snapshot, dict):
        return unavailable_cost_result(
            result, max_cost, "provider supplied no measurable cost", run_id
        )

    quality = cost_snapshot.get("quality")
    if quality not in COST_QUALITIES:
        return unavailable_cost_result(
            result, max_cost, "cost quality is missing or unsupported", run_id
        )
    source = cost_snapshot.get("source")
    scope = cost_snapshot.get("scope")
    source_id = cost_snapshot.get("source_id")
    if not isinstance(source, str) or not source:
        return unavailable_cost_result(
            result, max_cost, "cost source is missing", run_id
        )
    current_total = decimal_usd(cost_snapshot.get("total_cost_usd"), "current cost")
    state = read_cost_state(state_path)
    if state is None:
        baseline = current_total
        state = {
            "schema_version": 1,
            "run_id": run_id,
            "baseline_total_usd": str(baseline),
            "quality": quality,
            "source": source,
            "scope": scope,
            "source_id": source_id,
            "started_at": time.time(),
        }
        write_json_atomic(state_path, state)
    else:
        for field, current in (
            ("quality", quality),
            ("source", source),
            ("scope", scope),
            ("source_id", source_id),
        ):
            if state.get(field) != current:
                return unavailable_cost_result(
                    result,
                    max_cost,
                    f"cost {field} changed during the run",
                    run_id,
                )
        baseline = decimal_usd(state.get("baseline_total_usd"), "cost baseline")

    if current_total < baseline:
        return unavailable_cost_result(
            result,
            max_cost,
            "current cost is below the saved baseline; the provider session may have reset",
            run_id,
        )
    run_cost = current_total - baseline
    cost_allows_start = run_cost < max_cost
    usage_allows_start = result.get("may_start_next_checkpoint") is not False
    result.update(
        {
            "max_cost_usd": float(max_cost),
            "run_cost_usd": float(run_cost),
            "cost_quality": quality,
            "cost_source": source,
            "cost_scope": scope,
            "cost_run_id": run_id,
            "cost_baseline_usd": float(baseline),
            "current_cost_total_usd": float(current_total),
            "cost_limit_allows_start": cost_allows_start,
            "may_start_next_checkpoint": usage_allows_start and cost_allows_start,
        }
    )
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

    limiting_details = next(
        (window for window in windows if window["name"] == limiting_window), None
    )
    limiting_resets_at = (
        limiting_details.get("resets_at") if limiting_details is not None else None
    )
    result = {
        "ok": True,
        "provider": "codex",
        "limit_id": snapshot.get("limitId", "codex"),
        "plan_type": snapshot.get("planType"),
        "remaining_percent": remaining,
        "limiting_window": limiting_window,
        "limiting_resets_at": limiting_resets_at,
        "limiting_window_id": window_identity(
            "codex", limiting_window, limiting_resets_at
        ),
        "windows": windows,
    }
    return add_reserve_decision(result, reserve)


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
    return {
        "captured_at": captured_at,
        "cache_age_seconds": age,
        "cost_snapshot": payload.get("cost"),
        **rate_limits,
    }


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
    limiting_resets_at = limiting.get("resets_at")
    return add_reserve_decision(
        {
            "ok": True,
            "provider": "claude",
            "remaining_percent": limiting["remaining_percent"],
            "limiting_window": limiting["name"],
            "limiting_resets_at": limiting_resets_at,
            "limiting_window_id": window_identity(
                "claude", str(limiting["name"]), limiting_resets_at
            ),
            "captured_at": snapshot.get("captured_at"),
            "cache_age_seconds": round(float(snapshot.get("cache_age_seconds", 0)), 1),
            "windows": windows,
        },
        reserve,
    )


def external_cost_snapshot(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.current_cost_usd is None:
        return None
    if args.cost_quality is None:
        raise RuntimeError("--cost-quality is required with --current-cost-usd")
    return {
        "total_cost_usd": args.current_cost_usd,
        "quality": args.cost_quality,
        "source": args.cost_source or "external",
        "scope": args.cost_scope or "run",
        "source_id": args.cost_source_id,
    }


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
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        help="Do not start another checkpoint once this run has reached this USD cost.",
    )
    parser.add_argument(
        "--cost-run-id",
        help="Stable identifier used to preserve the cost baseline across checks.",
    )
    parser.add_argument(
        "--cost-state-dir",
        help="Override the directory for cost baseline state.",
    )
    parser.add_argument(
        "--current-cost-usd",
        type=float,
        help="Provider-reported cumulative cost for hosts without a built-in adapter.",
    )
    parser.add_argument("--cost-quality", choices=COST_QUALITIES)
    parser.add_argument("--cost-source")
    parser.add_argument("--cost-scope", choices=("session", "thread", "run", "account"))
    parser.add_argument("--cost-source-id")
    parser.add_argument(
        "--codex-thread-id",
        help="Override the current Codex thread used for estimated cost lookup.",
    )
    args = parser.parse_args()
    if args.reserve is not None and not 0 <= args.reserve <= 100:
        parser.error("--reserve must be between 0 and 100")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.max_cache_age <= 0:
        parser.error("--max-cache-age must be greater than zero")
    if args.max_cost_usd is not None and args.max_cost_usd < 0:
        parser.error("--max-cost-usd must be zero or greater")
    if args.current_cost_usd is not None and args.current_cost_usd < 0:
        parser.error("--current-cost-usd must be zero or greater")
    if args.current_cost_usd is None and any(
        value is not None
        for value in (
            args.cost_quality,
            args.cost_source,
            args.cost_scope,
            args.cost_source_id,
        )
    ):
        parser.error("cost source options require --current-cost-usd")
    return args


def main() -> None:
    args = parse_args()
    try:
        state_directory = (
            Path(args.cost_state_dir).expanduser()
            if args.cost_state_dir
            else DEFAULT_COST_STATE_DIR
        )
        supplied_cost = external_cost_snapshot(args)
        if args.provider == "claude":
            snapshot = read_claude_snapshot(
                claude_cache_path(args.claude_cache), args.max_cache_age
            )
            result = summarize_claude(snapshot, args.reserve)
            emit(
                apply_cost_guard(
                    result,
                    args.max_cost_usd,
                    args.cost_run_id,
                    supplied_cost or snapshot.get("cost_snapshot"),
                    state_directory,
                )
            )
        thread_id = (
            args.codex_thread_id
            or os.environ.get("CHECKPOINT_WORK_CODEX_THREAD_ID")
            or os.environ.get("CODEX_THREAD_ID")
        )
        response, usage_response = read_codex_data(args.timeout, thread_id)
        result = summarize_codex(select_codex_snapshot(response), args.reserve)
        emit(
            apply_cost_guard(
                result,
                args.max_cost_usd,
                args.cost_run_id,
                supplied_cost or codex_cost_snapshot(usage_response),
                state_directory,
            )
        )
    except Exception as exc:
        emit({"ok": False, "provider": args.provider, "error": str(exc)}, exit_code=2)


if __name__ == "__main__":
    main()
