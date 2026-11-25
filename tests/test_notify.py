"""Notification formatting and delivery tests; no real messages are sent."""

from __future__ import annotations

import json
import traceback
import unittest
from unittest.mock import Mock, patch

import requests

from tds_watch import notify
from tds_watch.config import Config

WEBHOOK = "https://chat.googleapis.com/v1/spaces/test/messages?key=test-key&token=test-token"
MESSAGE = '<b>TDS 2026-09</b>\nA &amp; B\n<a href="https://github.com/example/repo">View commits</a>'


class TestGoogleChat(unittest.TestCase):
    def test_translates_bold_entities_and_links(self) -> None:
        self.assertEqual(
            notify.google_chat_text(MESSAGE),
            "*TDS 2026-09*\nA & B\n<https://github.com/example/repo|View commits>",
        )

    def test_preserves_plain_text_unicode_and_escaped_content(self) -> None:
        self.assertEqual(notify.google_chat_text("🔔 Test\nGA4: old → new"), "🔔 Test\nGA4: old → new")
        self.assertEqual(notify.google_chat_text("&lt;b&gt;A &amp; B&lt;/b&gt;"), "<b>A & B</b>")

    def test_card_fallback_is_plain_text(self) -> None:
        self.assertEqual(
            notify.google_chat_text(MESSAGE, plain=True),
            "TDS 2026-09\nA & B\nView commits (https://github.com/example/repo)",
        )

    @patch("tds_watch.notify.requests.post")
    def test_posts_rich_card_with_notification_fallback(self, post: Mock) -> None:
        post.return_value.status_code = 200
        card = {"header": {"title": "TDS"}, "sections": [{"widgets": [{"textParagraph": {"text": "Test"}}]}]}
        notify.send_google_chat(WEBHOOK, MESSAGE, card=card)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["cardsV2"], [{"cardId": "tds-update", "card": card}])
        self.assertEqual(payload["fallbackText"], notify.google_chat_text(MESSAGE, plain=True))
        self.assertNotIn("text", payload)

    def test_oversized_card_falls_back_to_text(self) -> None:
        card = {"sections": [{"widgets": [{"textParagraph": {"text": "A" * 40000}}]}]}
        payload = notify.google_chat_payload(MESSAGE, card=card)
        self.assertEqual(payload, {"text": notify.google_chat_text(MESSAGE)})
        self.assertLessEqual(len(json.dumps(payload).encode("utf-8")), notify.GOOGLE_CHAT_MAX_BYTES)

    def test_oversized_unicode_text_is_bounded(self) -> None:
        payload = notify.google_chat_payload("🔔" * 10000)
        self.assertTrue(payload["text"].endswith("…"))
        self.assertLessEqual(len(json.dumps(payload).encode("utf-8")), notify.GOOGLE_CHAT_MAX_BYTES)

    @patch("tds_watch.notify.requests.post")
    def test_posts_google_chat_json(self, post: Mock) -> None:
        post.return_value.status_code = 200
        notify.send_google_chat(WEBHOOK, MESSAGE)
        post.assert_called_once_with(
            WEBHOOK,
            json={"text": "*TDS 2026-09*\nA & B\n<https://github.com/example/repo|View commits>"},
            timeout=25,
            allow_redirects=False,
        )

    def test_http_failures_and_redirects_do_not_leak_secrets(self) -> None:
        for code in (302, 400, 403, 429, 500):
            with self.subTest(code=code), patch("tds_watch.notify.requests.post") as post:
                post.return_value.status_code = code
                post.return_value.text = WEBHOOK
                with self.assertRaises(RuntimeError) as caught:
                    notify.send_google_chat(WEBHOOK, MESSAGE)
                self.assertIn(str(code), str(caught.exception))
                self.assertNotIn(WEBHOOK, str(caught.exception))
                self.assertNotIn("test-token", str(caught.exception))

    def test_network_errors_do_not_leak_secrets_in_tracebacks(self) -> None:
        for error in (requests.Timeout(WEBHOOK), requests.ConnectionError(WEBHOOK)):
            with self.subTest(error=type(error).__name__), patch(
                "tds_watch.notify.requests.post", side_effect=error
            ):
                try:
                    notify.send_google_chat(WEBHOOK, MESSAGE)
                except RuntimeError as exc:
                    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                    self.assertIn(type(error).__name__, str(exc))
                    self.assertNotIn(WEBHOOK, detail)
                    self.assertNotIn("test-token", detail)
                else:
                    self.fail("Expected a delivery error")

    @patch("tds_watch.notify.requests.post")
    def test_telegram_payload_is_unchanged(self, post: Mock) -> None:
        post.return_value.ok = True
        notify.send("token", "chat", MESSAGE)
        post.assert_called_once_with(
            "https://api.telegram.org/bottoken/sendMessage",
            json={
                "chat_id": "chat",
                "text": MESSAGE,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=25,
        )


class TestDestinations(unittest.TestCase):
    def setUp(self) -> None:
        telegram = patch("tds_watch.notify.send")
        google_chat = patch("tds_watch.notify.send_google_chat")
        self.telegram = telegram.start()
        self.google_chat = google_chat.start()
        self.addCleanup(telegram.stop)
        self.addCleanup(google_chat.stop)

    def test_telegram_only(self) -> None:
        notify.send_notifications(Config(token="token", chat_id="chat"), MESSAGE)
        self.telegram.assert_called_once_with("token", "chat", MESSAGE)
        self.google_chat.assert_not_called()

    def test_google_chat_only(self) -> None:
        notify.send_notifications(Config(google_chat_webhook_url=WEBHOOK), MESSAGE)
        self.telegram.assert_not_called()
        self.google_chat.assert_called_once_with(WEBHOOK, MESSAGE, card=None)

    def test_both_destinations(self) -> None:
        cfg = Config(token="token", chat_id="chat", google_chat_webhook_url=WEBHOOK)
        notify.send_notifications(cfg, MESSAGE)
        self.telegram.assert_called_once_with("token", "chat", MESSAGE)
        self.google_chat.assert_called_once_with(WEBHOOK, MESSAGE, card=None)

    def test_rich_card_goes_only_to_google_chat(self) -> None:
        cfg = Config(token="token", chat_id="chat", google_chat_webhook_url=WEBHOOK)
        card = {"header": {"title": "TDS"}}
        notify.send_notifications(cfg, MESSAGE, card=card)
        self.telegram.assert_called_once_with("token", "chat", MESSAGE)
        self.google_chat.assert_called_once_with(WEBHOOK, MESSAGE, card=card)

    def test_telegram_failure_still_attempts_google_chat(self) -> None:
        self.telegram.side_effect = RuntimeError("Telegram unavailable")
        cfg = Config(token="token", chat_id="chat", google_chat_webhook_url=WEBHOOK)
        with self.assertRaisesRegex(RuntimeError, "Telegram unavailable"):
            notify.send_notifications(cfg, MESSAGE)
        self.google_chat.assert_called_once_with(WEBHOOK, MESSAGE, card=None)

    def test_google_chat_failure_is_reported_after_telegram_delivery(self) -> None:
        self.google_chat.side_effect = RuntimeError("Google Chat unavailable")
        cfg = Config(token="token", chat_id="chat", google_chat_webhook_url=WEBHOOK)
        with self.assertRaisesRegex(RuntimeError, "Google Chat unavailable"):
            notify.send_notifications(cfg, MESSAGE)
        self.telegram.assert_called_once_with("token", "chat", MESSAGE)

    def test_reports_both_failures(self) -> None:
        self.telegram.side_effect = RuntimeError("Telegram unavailable")
        self.google_chat.side_effect = RuntimeError("Google Chat unavailable")
        cfg = Config(token="token", chat_id="chat", google_chat_webhook_url=WEBHOOK)
        with self.assertRaisesRegex(RuntimeError, "Telegram unavailable; Google Chat unavailable"):
            notify.send_notifications(cfg, MESSAGE)

    def test_invalid_configuration_never_sends(self) -> None:
        for cfg in (Config(), Config(token="token", google_chat_webhook_url=WEBHOOK)):
            with self.subTest(cfg=cfg), self.assertRaises(RuntimeError):
                notify.send_notifications(cfg, MESSAGE)
        self.telegram.assert_not_called()
        self.google_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
