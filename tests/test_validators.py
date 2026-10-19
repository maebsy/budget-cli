"""입력 검증 함수 테스트: 대화형·옵션·CSV 가 모두 같은 규칙을 쓰는지 확인한다."""

import unittest
from datetime import date

from budget_app.errors import ValidationError
from budget_app.models import TxType
from budget_app.validators import (month_range, normalize_category, parse_amount, parse_date, parse_day,
                                   parse_month, parse_tags, parse_tx_id, parse_type, previous_month)


class DateTest(unittest.TestCase):
    def test_valid_date(self):
        self.assertEqual(parse_date(" 2024-01-15 "), date(2024, 1, 15))

    def test_leap_day(self):
        self.assertEqual(parse_date("2024-02-29"), date(2024, 2, 29))

    def test_rejects_bad_format_and_impossible_dates(self):
        for bad in ("2024/01/15", "20240115", "2024-1-5", "2024-13-40", "2023-02-29", "", "오늘"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError) as cm:
                parse_date(bad)
            self.assertTrue(cm.exception.hint)  # 모든 오류에는 해결 힌트가 있다

    def test_month(self):
        self.assertEqual(parse_month("2024-01"), "2024-01")
        for bad in ("2024-13", "2024-00", "2024-1", "24-01"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_month(bad)

    def test_month_range_handles_month_length(self):
        self.assertEqual(month_range("2024-02"), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(month_range("2023-02")[1], date(2023, 2, 28))
        self.assertEqual(month_range("2024-12")[1], date(2024, 12, 31))


class AmountTest(unittest.TestCase):
    def test_accepts_commas_and_won_suffix(self):
        self.assertEqual(parse_amount("15000"), 15000)
        self.assertEqual(parse_amount("3,000,000"), 3000000)
        self.assertEqual(parse_amount("15000원"), 15000)

    def test_rejects_zero_negative_decimal_text(self):
        for bad in ("0", "-100", "12.5", "abc", "", "1e3"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_amount(bad)

    def test_rejects_absurd_amount(self):
        with self.assertRaises(ValidationError):
            parse_amount("1" + "0" * 13)


class TypeCategoryTagTest(unittest.TestCase):
    def test_type_aliases(self):
        self.assertIs(parse_type("income"), TxType.INCOME)
        self.assertIs(parse_type(" EXPENSE "), TxType.EXPENSE)
        self.assertIs(parse_type("지출"), TxType.EXPENSE)
        with self.assertRaises(ValidationError):
            parse_type("refund")

    def test_category_normalization(self):
        self.assertEqual(normalize_category("  Food  "), "food")
        self.assertEqual(normalize_category("eating   out"), "eating out")
        for bad in ("", "   ", "a,b", "x" * 31):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                normalize_category(bad)

    def test_tags_are_normalized_and_deduplicated(self):
        self.assertEqual(parse_tags("Meal, #team ,meal,,"), ("meal", "team"))
        self.assertEqual(parse_tags(""), ())
        self.assertEqual(parse_tags(None), ())

    def test_tx_id_and_day(self):
        self.assertEqual(parse_tx_id("tx-000012"), "TX-000012")
        with self.assertRaises(ValidationError):
            parse_tx_id("12")
        self.assertEqual(parse_day("31"), 31)
        for bad in ("0", "32", "x"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_day(bad)


class PreviousMonthTest(unittest.TestCase):
    def test_previous_month(self):
        self.assertEqual(previous_month("2024-03"), "2024-02")
        self.assertEqual(previous_month("2024-01"), "2023-12")
        self.assertEqual(previous_month("2024-10"), "2024-09")


if __name__ == "__main__":
    unittest.main()
