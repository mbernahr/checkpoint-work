from __future__ import annotations

import importlib.util
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
            "primary": {"usedPercent": used},
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
        snapshot["secondary"] = {"usedPercent": 75}
        result = CHECK_USAGE.summarize_codex(snapshot, 20)
        self.assertEqual(result["remaining_percent"], 25)
        self.assertEqual(result["limiting_window"], "secondary")

    def test_hard_limit_prevents_starting(self) -> None:
        snapshot = self.snapshot(20)
        snapshot["rateLimitReachedType"] = "rate_limit_reached"
        result = CHECK_USAGE.summarize_codex(snapshot, 0)
        self.assertEqual(result["remaining_percent"], 0)
        self.assertFalse(result["may_start_next_checkpoint"])


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
        self.assertTrue(result["may_start_next_checkpoint"])

    def test_reads_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = pathlib.Path(directory) / "usage.json"
            cache.write_text(
                json.dumps(
                    {
                        "captured_at": time.time(),
                        "rate_limits": {"five_hour": {"used_percentage": 44}},
                    }
                ),
                encoding="utf-8",
            )
            snapshot = CHECK_USAGE.read_claude_snapshot(cache, 60)
            self.assertEqual(snapshot["five_hour"]["used_percentage"], 44)

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
