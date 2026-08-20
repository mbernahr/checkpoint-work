from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPTS = pathlib.Path(__file__).parents[1] / "scripts"


def load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPTURE = load("capture_claude_usage")
SETUP = load("setup_claude_statusline")


class CaptureTests(unittest.TestCase):
    def test_writes_rate_limit_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / "usage.json"
            data = {"rate_limits": {"five_hour": {"used_percentage": 25}}}
            CAPTURE.write_snapshot(data, destination)
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["rate_limits"]["five_hour"]["used_percentage"], 25
            )

    def test_status_text_shows_remaining(self) -> None:
        data = {
            "rate_limits": {
                "five_hour": {"used_percentage": 25},
                "seven_day": {"used_percentage": 60},
            }
        }
        self.assertEqual(
            CAPTURE.status_text(data), "Checkpoint Work · 5h 75% left · 7d 40% left"
        )


class SetupTests(unittest.TestCase):
    def test_adds_status_line_when_absent(self) -> None:
        configured = SETUP.configure({"theme": "dark"})
        self.assertEqual(configured["theme"], "dark")
        self.assertEqual(configured["statusLine"]["type"], "command")

    def test_refuses_to_replace_existing_status_line(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "already has"):
            SETUP.configure({"statusLine": {"type": "command", "command": "mine"}})


if __name__ == "__main__":
    unittest.main()
