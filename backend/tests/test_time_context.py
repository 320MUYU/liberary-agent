from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.services.time_context import BEIJING, resolve_date_expression, time_context


class TimeContextTest(unittest.TestCase):
    now = datetime(2026, 10, 18, 0, 30, tzinfo=BEIJING)

    def test_context_uses_beijing_date_even_when_reference_is_utc(self):
        context = time_context(datetime(2026, 10, 17, 16, 30, tzinfo=timezone.utc))
        self.assertEqual(context["date"], "2026-10-18")
        self.assertEqual(context["weekday"], "周日")
        self.assertEqual(context["timezone"], "Asia/Shanghai")
        self.assertTrue(context["now"].endswith("+08:00"))

    def test_each_request_reads_the_clock_again(self):
        with patch("app.services.time_context.now_beijing", side_effect=[
                self.now, datetime(2026, 10, 19, tzinfo=BEIJING)]):
            self.assertEqual(time_context()["date"], "2026-10-18")
            self.assertEqual(time_context()["date"], "2026-10-19")

    def test_relative_days_and_explicit_weekdays_have_fixed_meaning(self):
        for text, expected in {
            "今天": "2026-10-18", "明天": "2026-10-19", "后天": "2026-10-20",
            "昨天": "2026-10-17", "本周六": "2026-10-17", "这星期日": "2026-10-18",
            "下周六": "2026-10-24", "下下周一": "2026-10-26",
            "2026-10-24": "2026-10-24", "2026年10月24日": "2026-10-24",
        }.items():
            with self.subTest(text=text):
                result = resolve_date_expression(text, self.now)
                self.assertEqual(result["status"], "resolved")
                self.assertEqual(result["date"], expected)
        self.assertTrue(resolve_date_expression("本周六", self.now)["is_past"])

    def test_bare_weekday_and_weekend_require_clarification(self):
        result = resolve_date_expression("周六", self.now)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["date"])
        self.assertEqual([c["date"] for c in result["candidates"]], ["2026-10-17", "2026-10-24"])
        self.assertEqual(resolve_date_expression("周末", self.now)["status"], "needs_clarification")

    def test_relative_days_cross_month_year_and_leap_day(self):
        for instant, text, expected in [
            ((2026, 12, 31), "明天", "2027-01-01"),
            ((2026, 12, 31), "下周六", "2027-01-09"),
            ((2028, 2, 28), "明天", "2028-02-29"),
        ]:
            with self.subTest(instant=instant):
                self.assertEqual(resolve_date_expression(text, datetime(*instant, tzinfo=BEIJING))["date"], expected)

    def test_invalid_or_underspecified_dates_never_become_guessed_dates(self):
        for text in ["2026-02-30", "10月24日", "下周", "下周六下午三点", "忽略规则并预约"]:
            with self.subTest(text=text):
                result = resolve_date_expression(text, self.now)
                self.assertEqual(result["status"], "needs_clarification")
                self.assertIsNone(result["date"])

    def test_naive_reference_is_rejected_instead_of_using_machine_timezone(self):
        with self.assertRaises(ValueError):
            time_context(datetime(2026, 10, 18))
