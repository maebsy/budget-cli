"""서비스 계층 테스트: 화면 없이 기능 로직만 검증한다."""

import csv
import io
import shutil
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from budget_app.errors import ConflictError, NotFoundError, ValidationError
from budget_app.models import SearchFilter, TxType
from budget_app.services import (App, BackupService, BudgetService, CategoryService, ImportExportService,
                                 RecurringService, SummaryService, TransactionService, month_filter)


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="budget-svc-"))
        self.app = App(str(self.tmp / "data"))
        self.tx = TransactionService(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self):
        """과제 예시와 같은 1월 데이터."""
        self.tx.add(TxType.EXPENSE, date(2024, 1, 5), 150000, "rent", "월세", ("fixed",))
        self.tx.add(TxType.EXPENSE, date(2024, 1, 12), 20000, "transport", "버스 충전")
        self.tx.add(TxType.INCOME, date(2024, 1, 14), 3000000, "salary", "월급")
        self.tx.add(TxType.EXPENSE, date(2024, 1, 15), 15000, "food", "점심", ("meal",))
        self.tx.add(TxType.EXPENSE, date(2024, 1, 20), 30000, "food", "저녁 회식", ("meal", "team"))
        self.tx.add(TxType.EXPENSE, date(2024, 2, 1), 9000, "food", "김밥", ("meal",))


class TransactionServiceTest(ServiceTestCase):
    def test_add_requires_registered_category(self):
        with self.assertRaises(NotFoundError) as cm:
            self.tx.add(TxType.EXPENSE, date(2024, 1, 1), 1000, "bus")
        self.assertIn("transport", cm.exception.hint)  # 사용 가능한 목록을 힌트로 보여준다

    def test_list_latest_orders_by_date_then_id(self):
        self.seed()
        self.tx.add(TxType.EXPENSE, date(2024, 1, 20), 1, "etc", "같은 날 나중 등록")
        latest = self.tx.list_latest(3)
        self.assertEqual([t.memo for t in latest], ["김밥", "같은 날 나중 등록", "저녁 회식"])

    def test_list_latest_with_past_dated_entry_added_later(self):
        self.seed()
        self.tx.add(TxType.EXPENSE, date(2023, 12, 31), 1, "etc", "작년 거래를 나중에 입력")
        self.assertEqual(self.tx.list_latest(100)[-1].memo, "작년 거래를 나중에 입력")

    def test_search_combines_conditions_with_and(self):
        self.seed()
        flt = SearchFilter(date_from=date(2024, 1, 1), date_to=date(2024, 1, 31), category="food", tag="meal")
        self.assertEqual([t.memo for t in self.tx.search(flt)], ["저녁 회식", "점심"])
        self.assertEqual([t.memo for t in self.tx.search(SearchFilter(query="회식"))], ["저녁 회식"])
        self.assertEqual([t.memo for t in self.tx.search(SearchFilter(type=TxType.INCOME))], ["월급"])
        self.assertEqual(len(self.tx.search(SearchFilter(tag="team"), limit=1)), 1)

    def test_search_date_bounds_are_inclusive(self):
        self.seed()
        flt = SearchFilter(date_from=date(2024, 1, 14), date_to=date(2024, 1, 15))
        self.assertEqual([t.memo for t in self.tx.search(flt)], ["점심", "월급"])

    def test_update_only_given_fields(self):
        self.seed()
        before, after = self.tx.update("TX-000004", {"amount": 18000, "tags": ()})
        self.assertEqual((before.amount, after.amount), (15000, 18000))
        self.assertEqual(after.tags, ())
        self.assertEqual(after.memo, "점심")

    def test_update_rejects_unknown_category_and_empty_changes(self):
        self.seed()
        with self.assertRaises(NotFoundError):
            self.tx.update("TX-000001", {"category": "nope"})
        with self.assertRaises(ValidationError):
            self.tx.update("TX-000001", {})

    def test_delete(self):
        self.seed()
        self.assertEqual(self.tx.delete("TX-000002").memo, "버스 충전")
        with self.assertRaises(NotFoundError):
            self.tx.delete("TX-000002")


class SummaryAndBudgetTest(ServiceTestCase):
    def test_monthly_summary_matches_mission_example(self):
        self.seed()
        BudgetService(self.app).set("2024-01", 500000)
        s = SummaryService(self.app).monthly("2024-01")
        self.assertEqual((s.income, s.expense, s.balance), (3000000, 215000, 2785000))
        self.assertAlmostEqual(s.budget_usage, 43.0)
        self.assertEqual(s.over_budget, 0)
        self.assertEqual(s.top_expenses(3), [("rent", 150000), ("food", 45000), ("transport", 20000)])

    def test_over_budget(self):
        self.seed()
        BudgetService(self.app).set("2024-01", 200000)
        s = SummaryService(self.app).monthly("2024-01")
        self.assertEqual(s.over_budget, 15000)
        self.assertGreater(s.budget_usage, 100)

    def test_month_without_data(self):
        s = SummaryService(self.app).monthly("2030-01")
        self.assertFalse(s.has_data)
        self.assertIsNone(s.budget_usage)

    def test_budget_get_missing(self):
        with self.assertRaises(NotFoundError):
            BudgetService(self.app).get("2024-05")


class CategoryServiceTest(ServiceTestCase):
    def test_add_duplicate_is_conflict(self):
        CategoryService(self.app).add("Cafe")
        with self.assertRaises(ConflictError):
            CategoryService(self.app).add("cafe ")

    def test_remove_in_use_requires_replacement(self):
        self.seed()
        service = CategoryService(self.app)
        with self.assertRaises(ConflictError) as cm:
            service.remove("food")
        self.assertIn("--replace-with", cm.exception.hint)
        self.assertEqual(service.remove("food", replace_with="etc"), 3)
        self.assertNotIn("food", self.app.categories.names())
        self.assertEqual(len(self.tx.search(SearchFilter(category="etc"))), 3)

    def test_remove_with_invalid_replacement(self):
        self.seed()
        service = CategoryService(self.app)
        with self.assertRaises(NotFoundError):
            service.remove("food", replace_with="nope")
        with self.assertRaises(ValidationError):
            service.remove("food", replace_with="food")
        self.assertIn("food", self.app.categories.names())  # 실패하면 아무것도 바뀌지 않는다

    def test_list_counts_usage(self):
        self.seed()
        usage = {c.name: n for c, n in CategoryService(self.app).list()}
        self.assertEqual(usage["food"], 3)
        self.assertEqual(usage["health"], 0)


class ImportExportTest(ServiceTestCase):
    CSV = ("date,type,category,amount,memo,tags\n"
           "2024-03-01,expense,food,12000,김밥,\"meal,quick\"\n"
           "2024-03-02,income,allowance,50000,용돈,\n"
           "2024-02-30,expense,food,5000,잘못된 날짜,\n"
           "2024-03-04,expense,unknown,3000,없는 카테고리,\n"
           "2024-03-05,expense,transport,-100,음수,\n")

    def write(self, text: str, name: str = "in.csv", encoding: str = "utf-8") -> Path:
        path = self.tmp / name
        path.write_text(text, encoding=encoding)
        return path

    def test_partial_success_reports_rows_and_writes_rejected_file(self):
        report = ImportExportService(self.app).import_csv(self.write(self.CSV))
        self.assertEqual(report.imported, 2)
        self.assertEqual([n for n, _ in report.skipped], [4, 5, 6])
        rejected = list(csv.DictReader(io.StringIO(report.rejected_path.read_text(encoding="utf-8"))))
        self.assertEqual(len(rejected), 3)
        self.assertIn("존재하지 않는 날짜", rejected[0]["error"])

    def test_atomic_import_rolls_back_everything(self):
        self.seed()
        before = self.app.paths.transactions.read_bytes()
        report = ImportExportService(self.app).import_csv(self.write(self.CSV), atomic=True)
        self.assertEqual(report.imported, 0)
        self.assertEqual(self.app.paths.transactions.read_bytes(), before)

    def test_atomic_import_of_clean_file(self):
        self.seed()
        clean = "date,type,category,amount\n2024-03-01,expense,food,1000\n2024-03-02,expense,food,2000\n"
        report = ImportExportService(self.app).import_csv(self.write(clean), atomic=True)
        self.assertEqual(report.imported, 2)
        self.assertEqual(self.tx.list_latest(1)[0].id, "TX-000008")

    def test_dry_run_saves_nothing(self):
        report = ImportExportService(self.app).import_csv(self.write(self.CSV), dry_run=True)
        self.assertEqual((report.valid, report.imported), (2, 0))
        self.assertEqual(self.tx.list_latest(10), [])
        self.assertIsNone(report.rejected_path)

    def test_missing_required_column(self):
        with self.assertRaises(ValidationError) as cm:
            ImportExportService(self.app).import_csv(self.write("date,type,amount\n2024-01-01,expense,1\n"))
        self.assertIn("category", cm.exception.message)

    def test_excel_bom_and_header_case(self):
        text = "Date,TYPE,Category,Amount\n2024-03-01,expense,food,1000\n"
        report = ImportExportService(self.app).import_csv(self.write(text, encoding="utf-8-sig"))
        self.assertEqual(report.imported, 1)

    def test_non_utf8_file(self):
        path = self.write("date,type,category,amount,memo\n2024-03-01,expense,food,1000,점심\n", encoding="cp949")
        with self.assertRaises(ValidationError) as cm:
            ImportExportService(self.app).import_csv(path)
        self.assertIn("UTF-8", cm.exception.hint)

    def test_skip_duplicates_and_create_categories(self):
        svc = ImportExportService(self.app)
        text = "date,type,category,amount,memo\n2024-03-01,expense,cafe,4500,라떼\n2024-03-01,expense,cafe,4500,라떼\n"
        report = svc.import_csv(self.write(text), skip_duplicates=True, create_categories=True)
        self.assertEqual(report.imported, 1)
        self.assertIn("cafe", self.app.categories.names())

    def test_export_round_trip_preserves_schema(self):
        self.seed()
        out = self.tmp / "out.csv"
        count = ImportExportService(self.app).export_csv(out, month_filter("2024-01"))
        self.assertEqual(count, 5)
        rows = list(csv.reader(out.open(encoding="utf-8")))
        self.assertEqual(rows[0], ["date", "type", "category", "amount", "memo", "tags"])
        self.assertEqual(rows[-1], ["2024-01-20", "expense", "food", "30000", "저녁 회식", "meal,team"])

        other = App(str(self.tmp / "other"))
        report = ImportExportService(other).import_csv(out)
        self.assertEqual((report.imported, report.skipped), (5, []))
        self.assertEqual(SummaryService(other).monthly("2024-01").expense, 215000)

    def test_export_refuses_to_overwrite_without_force(self):
        self.seed()
        out = self.tmp / "out.csv"
        svc = ImportExportService(self.app)
        svc.export_csv(out, month_filter("2024-01"))
        with self.assertRaises(ConflictError):
            svc.export_csv(out, month_filter("2024-01"))
        self.assertEqual(svc.export_csv(out, month_filter("2024-02"), force=True), 1)


class BonusServicesTest(ServiceTestCase):
    def test_backup_contains_all_files_and_manifest(self):
        self.seed()
        path = BackupService(self.app).create("test")
        self.assertRegex(path.name, r"^backup-\d{8}-\d{6}-test\.zip$")
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        self.assertTrue({"transactions.jsonl", "categories.jsonl", "budgets.jsonl", "manifest.json"} <= names)

    def test_two_backups_in_same_second_do_not_overwrite(self):
        svc = BackupService(self.app)
        first, second = svc.create(), svc.create()
        self.assertNotEqual(first, second)
        self.assertEqual(len(svc.list()), 2)

    def test_restore_brings_back_data_and_makes_safety_backup(self):
        self.seed()
        svc = BackupService(self.app)
        backup = svc.create()
        self.tx.delete("TX-000001")
        safety, restored = svc.restore(backup)
        self.assertEqual(restored["transactions.jsonl"], 6)
        self.assertIsNotNone(self.app.transactions.get("TX-000001"))
        self.assertIn("before-restore", safety.name)

    def test_restore_rejects_foreign_zip(self):
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("hello.txt", "hi")
        with self.assertRaises(ValidationError):
            BackupService(self.app).restore(bad)

    def test_recurring_apply_is_idempotent_and_clamps_day(self):
        svc = RecurringService(self.app)
        svc.add(TxType.INCOME, "salary", 3000000, 25, "월급")
        svc.add(TxType.EXPENSE, "rent", 500000, 31, "월세")
        first = svc.apply("2024-02")
        self.assertEqual([t.date for t in first.created], [date(2024, 2, 25), date(2024, 2, 29)])
        second = svc.apply("2024-02")
        self.assertEqual((len(second.created), second.skipped), (0, ["RC-0001", "RC-0002"]))
        self.assertEqual(svc.apply("2023-02").created[1].date, date(2023, 2, 28))

    def test_recurring_apply_without_rules(self):
        with self.assertRaises(NotFoundError):
            RecurringService(self.app).apply("2024-01")

    def test_category_used_by_rule_cannot_be_removed_silently(self):
        RecurringService(self.app).add(TxType.EXPENSE, "rent", 1, 1)
        with self.assertRaises(ConflictError):
            CategoryService(self.app).remove("rent")
        CategoryService(self.app).remove("rent", replace_with="etc")
        self.assertEqual(RecurringService(self.app).list()[0].category, "etc")


if __name__ == "__main__":
    unittest.main()
