"""CLI notification tests; no course data is fetched and no messages are sent."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import monitor
from tds_watch.config import Config


class TestNotificationCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(google_chat_webhook_url="webhook")
        for name, target, options in (
            ("config", "monitor.Config.from_env", {"return_value": self.cfg}),
            ("send", "monitor.notify.send_notifications", {}),
            ("run", "monitor.run", {}),
            ("status", "monitor.status_report", {}),
        ):
            mocked = patch(target, **options)
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)

    def test_test_notification_sends_without_polling(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = monitor.main(["--test-notification"])
        self.assertEqual(result, 0)
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[0], self.cfg)
        self.assertIn("TDS monitor test", self.send.call_args.args[1])
        self.assertEqual(self.send.call_args.kwargs["card"]["header"]["title"], "TDS · Shared alerts connected")
        self.assertIn("sent to all configured destinations", output.getvalue())
        self.run.assert_not_called()
        self.status.assert_not_called()

    def test_dry_test_previews_without_sending_or_polling(self) -> None:
        self.config.return_value = Config()
        output = io.StringIO()
        with redirect_stdout(output):
            result = monitor.main(["--test-notification", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("TDS monitor test", output.getvalue())
        self.assertIn("no notifications sent", output.getvalue())
        self.send.assert_not_called()
        self.run.assert_not_called()
        self.status.assert_not_called()

    def test_delivery_failure_returns_nonzero(self) -> None:
        self.send.side_effect = RuntimeError("Google Chat unavailable")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = monitor.main(["--test-notification"])
        self.assertEqual(result, 1)
        self.assertIn("error: Google Chat unavailable", errors.getvalue())
        self.assertNotIn("sent to all", output.getvalue())
        self.run.assert_not_called()

    def test_test_notification_cannot_be_combined_with_seed(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            monitor.main(["--test-notification", "--seed"])
        self.assertEqual(caught.exception.code, 2)
        self.config.assert_not_called()
        self.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
