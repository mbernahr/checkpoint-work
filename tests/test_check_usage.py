from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import tempfile
import time
import unittest


SCRIPT_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "check_usage.py"
SPEC = importlib.util.spec_from_file_location("check_usage", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECK_USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_USAGE)


class CodexSummaryTests(unittest.TestCase):
    def snapshot(self, used: int) -> dict:
        return {
            "limitId": "codex",
            "planType": "plus",
            "primary": {"usedPercent": used, "resetsAt": 123456},
            "secondary": None,
            "spendControlReached": False,
            "rateLimitReachedType": None,
        }

    def test_starts_when_remaining_is_above_reserve(self) -> None:
        result = CHECK_USAGE.summarize_codex(self.snapshot(89), 10)
        self.assertEqual(result["remaining_percent"], 11)
        self.assertTrue(result["may_start_next_checkpoint"])

    def test_stops_when_remaining_equals_reserve(self) -> None:
        result = CHECK_USAGE.summarize_codex(self.snapshot(90), 10)
        self.assertEqual(result["remaining_percent"], 10)
        self.assertFalse(result["may_start_next_checkpoint"])

    def test_uses_the_most_constrained_window(self) -> None:
        snapshot = self.snapshot(20)
        snapshot["secondary"] = {"usedPercent": 75, "resetsAt": 789012}
        result = CHECK_USAGE.summarize_codex(snapshot, 20)
        self.assertEqual(result["remaining_percent"], 25)
        self.assertEqual(result["limiting_window"], "secondary")
        self.assertEqual(result["limiting_resets_at"], 789012)
        self.assertEqual(result["limiting_window_id"], "codex:secondary:789012")

    def test_hard_limit_prevents_starting(self) -> None:
        snapshot = self.snapshot(20)
        snapshot["rateLimitReachedType"] = "rate_limit_reached"
        result = CHECK_USAGE.summarize_codex(snapshot, 0)
        self.assertEqual(result["remaining_percent"], 0)
        self.assertFalse(result["may_start_next_checkpoint"])


class JsonLineReaderTests(unittest.TestCase):
    def test_ignores_notifications_and_invalid_lines(self) -> None:
        stream = io.StringIO(
            "not-json\n"
            '{"method":"account/rateLimits/updated"}\n'
            '{"id":2,"result":{"rateLimits":{"primary":{}}}}\n'
        )
        reader = CHECK_USAGE.JsonLineReader(stream)
        result = reader.wait_for_response(2, 1)
        self.assertIn("rateLimits", result)

    def test_reports_app_server_errors(self) -> None:
        reader = CHECK_USAGE.JsonLineReader(
            io.StringIO('{"id":3,"error":{"message":"unsupported"}}\n')
        )
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            reader.wait_for_response(3, 1)


class CostGuardTests(unittest.TestCase):
    def usage_result(self, allowed: bool = True) -> dict:
        return {
            "ok": True,
            "provider": "claude",
            "remaining_percent": 80,
            "may_start_next_checkpoint": allowed,
        }

    def snapshot(self, total: float, quality: str = "estimated") -> dict:
        return {
            "total_cost_usd": total,
            "quality": quality,
            "source": "claude_statusline",
            "scope": "session",
            "source_id": "session-1",
        }

    def test_creates_baseline_and_allows_first_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(),
                5,
                "run-1",
                self.snapshot(1.25),
                pathlib.Path(directory),
            )
            self.assertEqual(result["run_cost_usd"], 0)
            self.assertEqual(result["cost_quality"], "estimated")
            self.assertTrue(result["may_start_next_checkpoint"])

    def test_stops_when_run_cost_reaches_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-2", self.snapshot(1), state_dir
            )
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-2", self.snapshot(6), state_dir
            )
            self.assertEqual(result["run_cost_usd"], 5)
            self.assertFalse(result["cost_limit_allows_start"])
            self.assertFalse(result["may_start_next_checkpoint"])

    def test_usage_and_cost_must_both_allow_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(False),
                5,
                "run-3",
                self.snapshot(1),
                pathlib.Path(directory),
            )
            self.assertTrue(result["cost_limit_allows_start"])
            self.assertFalse(result["may_start_next_checkpoint"])

    def test_missing_cost_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-4", None, pathlib.Path(directory)
            )
            self.assertEqual(result["cost_quality"], "unavailable")
            self.assertFalse(result["may_start_next_checkpoint"])

    def test_does_not_mix_quality_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-5", self.snapshot(1), state_dir
            )
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(),
                5,
                "run-5",
                self.snapshot(2, "reported"),
                state_dir,
            )
            self.assertEqual(result["cost_quality"], "unavailable")
            self.assertIn("quality changed", result["cost_error"])

    def test_rejects_session_reset_below_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = pathlib.Path(directory)
            CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-6", self.snapshot(2), state_dir
            )
            result = CHECK_USAGE.apply_cost_guard(
                self.usage_result(), 5, "run-6", self.snapshot(1), state_dir
            )
            self.assertEqual(result["cost_quality"], "unavailable")
            self.assertIn("below the saved baseline", result["cost_error"])

    def test_reads_estimated_codex_thread_cost(self) -> None:
        snapshot = CHECK_USAGE.codex_cost_snapshot(
            {
                "threadUsage": {
                    "threadId": "thread-1",
                    "estimatedUsageUsdMicros": 1_234_567,
                    "estimatedUsageCreditsMicros": 0,
                    "groups": [],
                }
            }
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["total_cost_usd"], 1.234567)
        self.assertEqual(snapshot["quality"], "estimated")
        self.assertEqual(snapshot["scope"], "thread")

    def test_codex_cost_is_unavailable_without_usd_route(self) -> None:
        self.assertIsNone(
            CHECK_USAGE.codex_cost_snapshot(
                {
                    "threadUsage": {
                        "threadId": "thread-1",
                        "estimatedUsageUsdMicros": None,
                        "estimatedUsageCreditsMicros": 100,
                        "groups": [],
                    }
                }
            )
        )


class ClaudeSummaryTests(unittest.TestCase):
    def test_uses_more_constrained_claude_window(self) -> None:
        snapshot = {
            "captured_at": 123,
            "cache_age_seconds": 3.25,
            "five_hour": {"used_percentage": 30, "resets_at": 1000},
            "seven_day": {"used_percentage": 82, "resets_at": 2000},
        }
        result = CHECK_USAGE.summarize_claude(snapshot, 10)
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["remaining_percent"], 18)
        self.assertEqual(result["limiting_window"], "seven_day")
        self.assertEqual(result["limiting_resets_at"], 2000)
        self.assertEqual(result["limiting_window_id"], "claude:seven_day:2000")
        self.assertTrue(result["may_start_next_checkpoint"])

    def test_does_not_invent_a_window_identity_without_reset_data(self) -> None:
        result = CHECK_USAGE.summarize_claude(
            {"five_hour": {"used_percentage": 10}}, 5
        )
        self.assertIsNone(result["limiting_resets_at"])
        self.assertIsNone(result["limiting_window_id"])

    def test_reads_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = pathlib.Path(directory) / "usage.json"
            cache.write_text(
                json.dumps(
                    {
                        "captured_at": time.time(),
                        "rate_limits": {"five_hour": {"used_percentage": 44}},
                        "cost": {
                            "total_cost_usd": 1.25,
                            "quality": "estimated",
                            "source": "claude_statusline",
                            "scope": "session",
                            "source_id": "session-1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            snapshot = CHECK_USAGE.read_claude_snapshot(cache, 60)
            self.assertEqual(snapshot["five_hour"]["used_percentage"], 44)
            self.assertEqual(snapshot["cost_snapshot"]["total_cost_usd"], 1.25)

    def test_rejects_stale_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = pathlib.Path(directory) / "usage.json"
            cache.write_text(
                json.dumps(
                    {
                        "captured_at": time.time() - 120,
                        "rate_limits": {"five_hour": {"used_percentage": 44}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "stale"):
                CHECK_USAGE.read_claude_snapshot(cache, 60)


if __name__ == "__main__":
    unittest.main()
