"""Sanity tests for the two parsers. Run with: python -m unittest discover -s tests"""

from __future__ import annotations

import unittest

from tds_watch.parse import exam_id_for, parse_exam, parse_schedule, strip_md

SCHEDULE = """
These dates are **tentative** and may change.

| Content                                                  | Assessment     | Weight | Release Date        | Submission Date     |
| -------------------------------------------------------- | -------------- | -----: | ------------------- | ------------------- |
| Graded Assignment (GA)                                   | Best 7 of 9    |    20% |                     |                     |
| [Bootcamp][GA0]                                          | [**GA0**][GA0] |      — | Wed 16 Sep          | Sun 11 Oct          |
| Week-4                                                   | **GA4**        |      — | Wed 21 Oct          | Sun 08 Nov          |
| Project 1                                                | [**P1**][P1]   |    20% | Sat 17 Oct          | Mon 17 Nov          |
| Remote Online Exam                                       | **ROE**        |    20% | Sun 29 Nov, 1:00 PM | Sun 29 Nov, 1:45 PM |
| Final end-term (in-person)                               | **F**          |    20% | Sun 10 Jan 2027     | Sun 10 Jan 2027     |

[GA0]: https://exam.sanand.workers.dev/tds-2026-09-ga0
"""

EXAM = """import e from"./exam-tds-2026-09-ga2.info.js";var t={title:"TDS 2026 Sep Project 1",start:"2026-10-17T00:00:00+05:30",end:"2026-11-17T23:59:59+05:30",read:()=>!0,admin:s=>s=="a@b.c",instructions:`
    <h1>Project 1</h1>
    <p>Read carefully.</p>
  `};export{t as default};"""


class TestSchedule(unittest.TestCase):
    def test_strips_markdown_links(self) -> None:
        self.assertEqual(strip_md("[**GA4**][GA4]"), "GA4")
        self.assertEqual(strip_md("[Week-1](https://x.y)"), "Week-1")

    def test_parses_assessment_rows(self) -> None:
        schedule = parse_schedule(SCHEDULE)
        self.assertEqual(schedule["GA4"]["due"], "Sun 08 Nov")
        self.assertEqual(schedule["GA4"]["content"], "Week-4")
        self.assertEqual(schedule["P1"]["weight"], "20%")
        self.assertEqual(schedule["ROE"]["release"], "Sun 29 Nov, 1:00 PM")
        self.assertIn("F", schedule)

    def test_skips_rows_without_dates(self) -> None:
        schedule = parse_schedule(SCHEDULE)
        self.assertNotIn("Best 7 of 9", schedule)
        self.assertEqual(len(schedule), 5)

    def test_rejects_document_without_table(self) -> None:
        with self.assertRaises(ValueError):
            parse_schedule("# Nothing here")


class TestExam(unittest.TestCase):
    def test_extracts_metadata(self) -> None:
        exam = parse_exam(EXAM)
        self.assertEqual(exam["title"], "TDS 2026 Sep Project 1")
        self.assertEqual(exam["start"], "2026-10-17T00:00:00+05:30")
        self.assertEqual(exam["end"], "2026-11-17T23:59:59+05:30")
        self.assertEqual(len(exam["instructions_hash"]), 16)

    def test_hash_ignores_whitespace_but_not_content(self) -> None:
        first = parse_exam(EXAM)
        reformatted = EXAM.replace("<h1>Project 1</h1>", "<h1>Project 1</h1>   ")
        self.assertEqual(first["instructions_hash"], parse_exam(reformatted)["instructions_hash"])

        edited = EXAM.replace("Read carefully.", "Read very carefully.")
        self.assertNotEqual(first["instructions_hash"], parse_exam(edited)["instructions_hash"])


class TestExamIds(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual(exam_id_for("GA4"), "ga4")
        self.assertEqual(exam_id_for("ga0"), "ga0")
        self.assertEqual(exam_id_for("P1"), "p1")
        self.assertEqual(exam_id_for("ROE"), "roe")
        self.assertEqual(exam_id_for("F"), "et")
        self.assertIsNone(exam_id_for("Best 7 of 9"))


if __name__ == "__main__":
    unittest.main()
