"""Monitor delivery and state persistence tests with mocked public sources."""

from __future__ import annotations

import copy
import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import patch

from tds_watch.config import Config
from tds_watch.run import run


class TestRun(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(google_chat_webhook_url="webhook")
        self.schedule = {
            "GA4": {"content": "Week-4", "weight": "—", "release": "Wed 21 Oct", "due": "Sun 15 Nov"}
        }
        self.exams = {"ga4": None}
        self.previous = {
            "term": "2026-09",
            "schedule": copy.deepcopy(self.schedule),
            "exams": copy.deepcopy(self.exams),
        }
        for name, target, options in (
            ("collect", "tds_watch.run.collect", {"return_value": ("2026-09", self.schedule, self.exams, [])}),
            ("load", "tds_watch.run.state.load", {"return_value": self.previous}),
            ("save", "tds_watch.run.state.save", {}),
            ("send", "tds_watch.run.notify.send_notifications", {}),
        ):
            mocked = patch(target, **options)
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)

    def test_first_run_delivers_before_saving_baseline(self) -> None:
        self.load.return_value = None

        def check_delivery(cfg: Config, message: str, **kwargs) -> None:
            self.save.assert_not_called()
            self.assertEqual(cfg, self.cfg)
            self.assertIn("Baseline saved", message)
            self.assertIn("Monitoring is ready", kwargs["card"]["sections"][0]["header"])

        self.send.side_effect = check_delivery
        result = run(self.cfg)
        self.assertTrue(result.seeded)
        self.assertTrue(result.sent)
        self.send.assert_called_once()
        self.save.assert_called_once()

    def test_schedule_change_delivers_before_saving_new_state(self) -> None:
        self.previous["schedule"]["GA4"]["due"] = "Sun 08 Nov"
        self.send.side_effect = lambda cfg, message, **kwargs: self.save.assert_not_called()
        result = run(self.cfg)
        self.assertFalse(result.seeded)
        self.assertTrue(result.sent)
        self.assertEqual(result.changes, 1)
        self.assertIn("Sun 08 Nov", result.message)
        self.assertIn("Sun 15 Nov", result.message)
        card = self.send.call_args.kwargs["card"]
        self.assertIn("📅 Schedule updates", [section.get("header") for section in card["sections"]])
        self.save.assert_called_once()
        self.assertEqual(self.save.call_args.args[1]["schedule"], self.schedule)

    def test_delivery_failure_preserves_baseline_for_retry(self) -> None:
        self.previous["schedule"]["GA4"]["due"] = "Sun 08 Nov"
        self.send.side_effect = RuntimeError("Google Chat unavailable")
        with self.assertRaisesRegex(RuntimeError, "Google Chat unavailable"):
            run(self.cfg)
        self.save.assert_not_called()

        self.send.side_effect = None
        result = run(self.cfg)
        self.assertEqual(result.changes, 1)
        self.assertTrue(result.sent)
        self.assertEqual(self.send.call_count, 2)
        self.save.assert_called_once()

    def test_failed_first_delivery_does_not_save_baseline(self) -> None:
        self.load.return_value = None
        self.send.side_effect = RuntimeError("Google Chat unavailable")
        with self.assertRaises(RuntimeError):
            run(self.cfg)
        self.save.assert_not_called()

    def test_dry_run_does_not_send_or_save(self) -> None:
        self.previous["schedule"]["GA4"]["due"] = "Sun 08 Nov"
        output = io.StringIO()
        with redirect_stdout(output):
            result = run(replace(self.cfg, dry_run=True))
        self.assertEqual(result.changes, 1)
        self.assertFalse(result.sent)
        self.assertIn(result.message, output.getvalue())
        self.send.assert_not_called()
        self.save.assert_not_called()

    def test_unchanged_run_is_quiet_without_credentials(self) -> None:
        result = run(Config())
        self.assertEqual(result.changes, 0)
        self.assertIsNone(result.message)
        self.assertFalse(result.sent)
        self.send.assert_not_called()
        self.save.assert_not_called()

    def test_force_seed_needs_no_credentials_and_sends_nothing(self) -> None:
        result = run(Config(), force_seed=True)
        self.assertTrue(result.seeded)
        self.assertIsNone(result.message)
        self.send.assert_not_called()
        self.save.assert_called_once()

    def test_term_rollover_notifies_and_rebaselines(self) -> None:
        self.previous["term"] = "2026-05"
        result = run(self.cfg)
        self.assertTrue(result.seeded)
        self.send.assert_called_once()
        self.save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
