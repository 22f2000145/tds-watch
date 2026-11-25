"""Rich Google Chat card layout tests."""

from __future__ import annotations

import json
import unittest
from datetime import datetime

from tds_watch import cards, notify
from tds_watch.sources import Commit


class TestCards(unittest.TestCase):
    def setUp(self) -> None:
        self.args = {
            "term": "2026-09",
            "schedule_changes": [],
            "exam_changes": [],
            "commits": [],
            "labels": {"ga4": "GA4", "ga5": "GA5"},
            "repo": "example/course",
            "now": datetime(2026, 11, 25, 12, 30, tzinfo=notify.IST),
        }

    def test_header_and_source_buttons(self) -> None:
        card = cards.build_card(**self.args)
        self.assertEqual(card["header"]["title"], "TDS · Deadline Watch")
        self.assertEqual(card["header"]["subtitle"], "Term 2026-09 · 25 Nov 2026 · 12:30 IST")
        buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
        self.assertEqual(buttons[0]["onClick"]["openLink"]["url"], "https://github.com/example/course/blob/main/2026-09/README.md")

    def test_baseline_has_monitoring_counts(self) -> None:
        card = cards.build_card(**self.args, seeded=True, seeded_counts=(14, 6))
        section = card["sections"][0]
        self.assertIn("Baseline saved", section["header"])
        self.assertEqual(section["widgets"][0]["decoratedText"]["text"], "<b>14</b>")
        self.assertEqual(section["widgets"][1]["decoratedText"]["text"], "<b>6</b>")

    def test_schedule_keeps_previous_and_highlights_new_date(self) -> None:
        self.args["schedule_changes"] = [
            {"type": "changed", "key": "GA4", "field": "due", "old": "Sun 08 Nov", "new": "Sun 15 Nov"}
        ]
        card = cards.build_card(**self.args)
        section = next(s for s in card["sections"] if s.get("header") == "📅 Schedule updates")
        detail = section["widgets"][0]["decoratedText"]
        self.assertEqual(detail["topLabel"], "GA4 · Submission deadline")
        self.assertIn("<b>Sun 15 Nov</b>", detail["text"])
        self.assertEqual(detail["bottomLabel"], "Previously: Sun 08 Nov")
        self.assertTrue(detail["wrapText"])
        self.assertEqual(detail["button"]["onClick"]["openLink"]["url"], notify.exam_url("2026-09", "ga4"))

    def test_schedule_buttons_target_the_assessment_that_changed(self) -> None:
        for key, exam_id in (
            ("GA5", "ga5"), ("GA6", "ga6"), ("GA7", "ga7"), ("P2", "p2"), ("ROE", "roe"), ("F", "et")
        ):
            with self.subTest(key=key):
                self.args["schedule_changes"] = [
                    {"type": "changed", "key": key, "field": "due", "old": "Old date", "new": "New date"}
                ]
                card = cards.build_card(**self.args)
                buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
                self.assertEqual(
                    buttons[0]["onClick"]["openLink"]["url"],
                    f"https://exam.sanand.workers.dev/tds-2026-09-{exam_id}",
                )
                self.assertNotIn("View course", [button["text"] for button in buttons])

    def test_exam_buttons_target_the_assessment_that_changed(self) -> None:
        for exam_id in ("ga5", "ga6", "ga7", "p2", "roe", "et"):
            with self.subTest(exam_id=exam_id):
                self.args["exam_changes"] = [{"type": "changed", "id": exam_id, "field": "instructions"}]
                card = cards.build_card(**self.args)
                buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
                self.assertEqual(buttons[0]["onClick"]["openLink"]["url"], notify.exam_url("2026-09", exam_id))

    def test_each_affected_assessment_has_one_footer_button(self) -> None:
        self.args["schedule_changes"] = [
            {"type": "changed", "key": "GA6", "field": "due", "old": "Old date", "new": "New date"},
            {"type": "changed", "key": "P2", "field": "weight", "old": "10%", "new": "20%"},
        ]
        self.args["exam_changes"] = [
            {"type": "changed", "id": "ga6", "field": "instructions"},
            {"type": "released", "id": "roe", "title": "Remote Online Exam"},
        ]
        card = cards.build_card(**self.args)
        buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
        assessment_buttons = [button for button in buttons if button["text"].startswith("Open ")]
        self.assertEqual(len(assessment_buttons), 3)
        self.assertEqual(
            {button["onClick"]["openLink"]["url"] for button in assessment_buttons},
            {notify.exam_url("2026-09", exam_id) for exam_id in ("ga6", "p2", "roe")},
        )

    def test_assessment_buttons_use_the_current_term(self) -> None:
        self.args["term"] = "2027-01"
        self.args["exam_changes"] = [{"type": "released", "id": "ga6", "title": "GA6"}]
        card = cards.build_card(**self.args)
        button = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"][0]
        self.assertEqual(button["onClick"]["openLink"]["url"], "https://exam.sanand.workers.dev/tds-2027-01-ga6")

    def test_unrecognized_schedule_rows_do_not_get_an_arbitrary_assessment_link(self) -> None:
        self.args["schedule_changes"] = [
            {"type": "changed", "key": "Orientation", "field": "due", "old": "Old date", "new": "New date"}
        ]
        card = cards.build_card(**self.args)
        buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
        self.assertEqual([button["text"] for button in buttons], ["View schedule"])

    def test_withdrawn_assessments_do_not_get_broken_open_buttons(self) -> None:
        self.args["schedule_changes"] = [{"type": "removed", "key": "GA5", "fields": {}}]
        self.args["exam_changes"] = [{"type": "unreleased", "id": "ga5"}]
        card = cards.build_card(**self.args)
        self.assertNotIn(notify.exam_url("2026-09", "ga5"), json.dumps(card))

    def test_schedule_additions_and_removals(self) -> None:
        self.args["schedule_changes"] = [
            {"type": "added", "key": "GA5", "fields": {"due": "Sun 22 Nov"}},
            {"type": "removed", "key": "GA4", "fields": {}},
        ]
        card = cards.build_card(**self.args)
        section = next(s for s in card["sections"] if s.get("header") == "📅 Schedule updates")
        self.assertIn("Due Sun 22 Nov", section["widgets"][0]["decoratedText"]["text"])
        self.assertEqual(section["widgets"][1]["decoratedText"]["text"], "Removed from the schedule")

    def test_exact_deadlines_have_ist_and_assessment_button(self) -> None:
        self.args["exam_changes"] = [
            {
                "type": "changed",
                "id": "ga4",
                "field": "end",
                "old": "2026-11-08T18:29:59+00:00",
                "new": "2026-11-15T18:29:59+00:00",
            }
        ]
        card = cards.build_card(**self.args)
        detail = card["sections"][1]["widgets"][0]["decoratedText"]
        self.assertEqual(card["sections"][1]["header"], "⏰ Exact deadline changes")
        self.assertEqual(detail["topLabel"], "GA4 · Closes")
        self.assertIn("15 Nov 2026 23:59 IST", detail["text"])
        self.assertEqual(detail["bottomLabel"], "Previously: 08 Nov 2026 23:59 IST")
        self.assertEqual(detail["button"]["onClick"]["openLink"]["url"], notify.exam_url("2026-09", "ga4"))

    def test_releases_have_titles_and_direct_links(self) -> None:
        self.args["exam_changes"] = [{"type": "released", "id": "ga5", "title": "TDS GA5"}]
        card = cards.build_card(**self.args)
        section = next(s for s in card["sections"] if s.get("header") == "🎉 New assessments")
        detail = section["widgets"][0]["decoratedText"]
        self.assertEqual(detail["text"], "<b>TDS GA5</b>")
        self.assertEqual(detail["button"]["text"], "Open assessment")
        self.assertEqual(detail["button"]["onClick"]["openLink"]["url"], notify.exam_url("2026-09", "ga5"))

    def test_instruction_edits_titles_and_withdrawals_are_grouped(self) -> None:
        self.args["exam_changes"] = [
            {"type": "changed", "id": "ga4", "field": "instructions"},
            {"type": "changed", "id": "ga4", "field": "title", "old": "Old title", "new": "New title"},
            {"type": "unreleased", "id": "ga5"},
        ]
        card = cards.build_card(**self.args)
        section = next(s for s in card["sections"] if s.get("header") == "📝 Assessment updates")
        details = [widget["decoratedText"] for widget in section["widgets"]]
        self.assertEqual(details[0]["button"]["text"], "Read instructions")
        self.assertEqual(details[1]["bottomLabel"], "Previously: Old title")
        self.assertIn("Assessment page withdrawn", details[2]["text"])
        self.assertNotIn("button", details[2])

    def test_source_context_is_collapsible(self) -> None:
        self.args["commits"] = [Commit("sha", "Update deadline", "Teacher", "", "https://github.com/example/course")]
        card = cards.build_card(**self.args)
        section = next(s for s in card["sections"] if s.get("header") == "🔗 Change context")
        self.assertTrue(section["collapsible"])
        self.assertEqual(section["uncollapsibleWidgetsCount"], 1)
        self.assertEqual(section["widgets"][0]["decoratedText"]["text"], "Update deadline")
        buttons = card["sections"][-1]["widgets"][0]["buttonList"]["buttons"]
        self.assertEqual(buttons[1]["text"], "View commits")

    def test_escapes_source_content_before_inserting_card_html(self) -> None:
        self.args["exam_changes"] = [{"type": "released", "id": "ga5", "title": "<b>Title</b> & details"}]
        card = cards.build_card(**self.args)
        detail = card["sections"][1]["widgets"][0]["decoratedText"]
        self.assertEqual(detail["text"], "<b>&lt;b&gt;Title&lt;/b&gt; &amp; details</b>")

    def test_large_changes_are_bounded_and_have_overflow_notice(self) -> None:
        self.args["schedule_changes"] = [
            {"type": "changed", "key": f"GA{index}", "field": "content", "old": "A" * 500, "new": "B" * 500}
            for index in range(150)
        ]
        card = cards.build_card(**self.args)
        self.assertLessEqual(sum(len(s["widgets"]) for s in card["sections"]), 100)
        self.assertIn("100 more updates", json.dumps(card))
        payload = notify.google_chat_payload("Many public course updates", card=card)
        self.assertLessEqual(len(json.dumps(payload).encode("utf-8")), notify.GOOGLE_CHAT_MAX_BYTES)

    def test_test_card_is_clearly_a_setup_test(self) -> None:
        card = cards.build_test_card(now=self.args["now"])
        self.assertEqual(card["header"]["title"], "TDS · Shared alerts connected")
        self.assertIn("Test notification", card["header"]["subtitle"])
        self.assertIn("not a new course update", card["sections"][0]["widgets"][0]["decoratedText"]["bottomLabel"])
        self.assertIn("does not change your saved baseline", json.dumps(card))
        self.assertNotIn("View course", json.dumps(card))
        self.assertNotIn("github.com", json.dumps(card))


if __name__ == "__main__":
    unittest.main()
