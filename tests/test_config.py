"""Notification destination configuration tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tds_watch.config import Config


class TestConfig(unittest.TestCase):
    def test_reads_and_trims_webhook_from_env(self) -> None:
        with patch("tds_watch.config._load_dotenv"), patch.dict(
            os.environ, {"GOOGLE_CHAT_WEBHOOK_URL": "  https://chat.googleapis.com/test  "}, clear=True
        ):
            cfg = Config.from_env()
        self.assertEqual(cfg.google_chat_webhook_url, "https://chat.googleapis.com/test")
        self.assertIsNone(cfg.token)
        self.assertIsNone(cfg.chat_id)

    def test_blank_webhook_is_unconfigured(self) -> None:
        with patch("tds_watch.config._load_dotenv"), patch.dict(
            os.environ, {"GOOGLE_CHAT_WEBHOOK_URL": "  ", "DRY_RUN": "true"}, clear=True
        ):
            cfg = Config.from_env()
        self.assertIsNone(cfg.google_chat_webhook_url)
        self.assertTrue(cfg.dry_run)

    def test_accepts_either_destination_or_both(self) -> None:
        for cfg in (
            Config(token="token", chat_id="chat"),
            Config(google_chat_webhook_url="webhook"),
            Config(token="token", chat_id="chat", google_chat_webhook_url="webhook"),
        ):
            with self.subTest(cfg=cfg):
                cfg.require_notifications()

    def test_requires_a_destination(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_CHAT_WEBHOOK_URL.*TELEGRAM_BOT_TOKEN"):
            Config().require_notifications()

    def test_rejects_incomplete_telegram_even_with_webhook(self) -> None:
        for credentials in ({"token": "token"}, {"chat_id": "chat"}):
            with self.subTest(credentials=credentials):
                cfg = Config(**credentials, google_chat_webhook_url="webhook")
                with self.assertRaisesRegex(RuntimeError, "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"):
                    cfg.require_notifications()


if __name__ == "__main__":
    unittest.main()
