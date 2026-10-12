"""CLI 통합 테스트: 실제 명령을 실행해 출력 형식, 재입력, 종료 코드를 검증한다."""

import json
import unittest

from budget_app.errors import EXIT_CONFLICT, EXIT_INTERRUPTED, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from tests.helpers import CliTestCase

ALL_COMMANDS = [
    ["add"], ["list"], ["search"], ["summary"], ["budget"], ["budget", "set"], ["budget", "show"],
    ["budget", "list"], ["category"], ["category", "add"], ["category", "list"], ["category", "remove"],
    ["update"], ["delete"], ["export"], ["import"], ["backup"], ["restore"], ["recurring"],
    ["recurring", "add"], ["recurring", "list"], ["recurring", "remove"], ["recurring", "apply"],
]


class HelpTest(CliTestCase):
    def test_every_command_supports_help(self):
        for argv in [[]] + ALL_COMMANDS:
            with self.subTest(argv=argv):
                result = self.run_cli(*argv, "--help")
                self.assertEqual(result.code, EXIT_OK)
                self.assertIn("usage:", result.out)

    def test_unknown_command_and_option_exit_with_usage_error(self):
        for argv in (["fly"], ["list", "--limt", "3"], ["budget"], ["delete"]):
            with self.subTest(argv=argv):
                result = self.run_cli(*argv)
                self.assertEqual(result.code, EXIT_USAGE)
                self.assertIn("[오류]", result.err)
                self.assertIn("[힌트]", result.err)
                self.assertNoTraceback(result)


class AddTest(CliTestCase):
    def test_interactive_add_matches_mission_example(self):
        result = self.run_cli("add", stdin="2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n")
        self.assertEqual(result.code, EXIT_OK)
        self.assertIn("날짜(YYYY-MM-DD", result.out)
        self.assertTrue(result.out.rstrip().endswith("[저장 완료] id=TX-000001"))
        self.assertIn("[안내] 카테고리가 비어 있어 기본 카테고리를 만들었습니다", result.err)

    def test_invalid_input_asks_again(self):
        stdin = "2024-13-40\n2024-01-15\nrefund\nexpense\nbus\nfood\n-5\n0\n15000\n\n\n"
        result = self.run_cli("add", stdin=stdin)
        self.assertEqual(result.code, EXIT_OK, result.err)
        self.assertIn("[오류] 존재하지 않는 날짜입니다: 2024-13-40", result.err)
        self.assertIn("[오류] 허용되지 않는 타입입니다: refund", result.err)
        self.assertIn("[오류] 등록되지 않은 카테고리입니다: bus", result.err)
        self.assertIn("[힌트] 사용 가능: food", result.err)
        self.assertIn("[오류] 금액은 0보다 커야 합니다: -5", result.err)
        self.assertNoTraceback(result)

    def test_empty_date_means_today(self):
        tx_id = self.add("", "expense", "food", "1000")
        result = self.run_cli("list", "--plain")
        self.assertIn(tx_id, result.out)

    def test_eof_cancels_with_exit_130(self):
        result = self.run_cli("add", stdin="2024-01-15\nexpense\n")
        self.assertEqual(result.code, EXIT_INTERRUPTED)
        self.assertIn("[취소]", result.err)
        self.assertEqual(self.run_cli("list").out.strip(), "거래 내역이 없습니다. 'add' 로 첫 거래를 등록하세요.")

    def test_repeated_wrong_input_stops(self):
        result = self.run_cli("add", stdin="x\n" * 10)
        self.assertEqual(result.code, EXIT_USAGE)
        self.assertIn("5번 연속", result.err)


class ScenarioTest(CliTestCase):
    """과제 결과 예시 흐름을 그대로 실행한다."""

    def setUp(self):
        super().setUp()
        self.add("2024-01-05", "expense", "rent", "150000", "월세")
        self.add("2024-01-10", "expense", "food", "30000", "장보기")
        self.add("2024-01-12", "expense", "transport", "20000")
        self.add("2024-01-14", "income", "salary", "3000000")
        self.add("2024-01-15", "expense", "food", "15000", "점심", "meal")

    def test_list_plain_format(self):
        result = self.run_cli("list", "--limit", "3", "--plain")
        self.assertEqual(result.lines, [
            "TX-000005 | 2024-01-15 | expense | food | 15000 | 점심",
            "TX-000004 | 2024-01-14 | income  | salary | 3000000 |",
            "TX-000003 | 2024-01-12 | expense | transport | 20000 |",
        ])

    def test_list_table_format(self):
        result = self.run_cli("list", "--limit", "2")
        self.assertIn("ID", result.lines[0])
        self.assertIn("15,000원", result.out)
        self.assertIn("(최신순 2건", result.out)

    def test_budget_and_summary(self):
        self.assertEqual(self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000").out.strip(),
                         "[저장 완료] 2024-01 예산 500,000원")
        out = self.run_cli("summary", "--month", "2024-01", "--top", "3").out
        for expected in ("총 수입: 3,000,000원", "총 지출: 215,000원", "잔액: 2,785,000원",
                         "예산: 500,000원 (사용률 43.0%)", "지출 TOP 3", "1)  rent", "2)  food", "3)  transport"):
            self.assertIn(expected, out)

    def test_over_budget_warning(self):
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "200000")
        self.assertIn("[경고] 예산을 15,000원 초과했습니다!", self.run_cli("summary", "--month", "2024-01").out)

    def test_summary_without_data(self):
        out = self.run_cli("summary", "--month", "2024-02").out
        self.assertIn("데이터 없음", out)

    def test_search_options(self):
        self.assertIn("TX-000005", self.run_cli("search", "--tag", "meal").out)
        result = self.run_cli("search", "--from", "2024-01-10", "--to", "2024-01-12", "--plain")
        self.assertEqual([line.split(" | ")[0] for line in result.lines], ["TX-000003", "TX-000002"])
        self.assertIn("TX-000002", self.run_cli("search", "--q", "장보").out)
        self.assertEqual(self.run_cli("search", "--type", "income", "--plain").lines[0].split(" | ")[0], "TX-000004")
        self.assertEqual(self.run_cli("search").code, EXIT_USAGE)
        self.assertEqual(self.run_cli("search", "--month", "2024-01", "--from", "2024-01-01").code, EXIT_USAGE)

    def test_update_and_delete_messages(self):
        result = self.run_cli("update", "--id", "TX-000005", "--amount", "18000", "--memo", "점심(회식)")
        self.assertEqual(result.code, EXIT_OK)
        self.assertIn("amount: 15000 -> 18000", result.out)
        self.assertEqual(self.run_cli("update", "--id", "TX-000099", "--amount", "1").code, EXIT_NOT_FOUND)
        self.assertEqual(self.run_cli("delete", "--id", "TX-000005").code, EXIT_OK)
        missing = self.run_cli("delete", "--id", "TX-000005")
        self.assertEqual(missing.code, EXIT_NOT_FOUND)
        self.assertIn("찾을 수 없습니다", missing.err)

    def test_category_commands(self):
        self.assertEqual(self.run_cli("category", "add", stdin="cafe\n").out.strip().splitlines()[-1],
                         "[저장 완료] category=cafe")
        self.assertIn("- cafe", self.run_cli("category", "list").out)
        self.assertIn("- food (2건)", self.run_cli("category", "list").out)
        self.assertEqual(self.run_cli("category", "add", "cafe").code, EXIT_CONFLICT)
        self.assertEqual(self.run_cli("category", "remove", "food").code, EXIT_CONFLICT)
        moved = self.run_cli("category", "remove", "food", "--replace-with", "etc")
        self.assertIn("거래 2건을 'etc' 로 옮김", moved.out)

    def test_export_then_import_into_other_folder(self):
        out = self.tmp / "export.csv"
        result = self.run_cli("export", "--out", str(out), "--month", "2024-01")
        self.assertEqual(result.out.strip(), "[완료] {} (5 records)".format(out))
        self.assertEqual(self.run_cli("export", "--out", str(out), "--month", "2024-01").code, EXIT_CONFLICT)
        self.assertEqual(self.run_cli("export", "--out", str(self.tmp / "x.csv")).code, EXIT_USAGE)

        self.data_dir = self.tmp / "other"
        imported = self.run_cli("import", "--from", str(out))
        self.assertEqual(imported.out.strip(), "[완료] imported=5, skipped=0")

    def test_import_partial_and_atomic(self):
        path = self.write_file("in.csv", "date,type,category,amount\n2024-02-01,expense,food,100\n2024-02-30,expense,food,1\n")
        atomic = self.run_cli("import", "--from", str(path), "--atomic")
        self.assertEqual(atomic.code, EXIT_USAGE)
        self.assertIn("[롤백]", atomic.out)
        partial = self.run_cli("import", "--from", str(path))
        self.assertEqual(partial.out.strip(), "[완료] imported=1, skipped=1")
        self.assertIn("[건너뜀] 3번째 줄", partial.err)
        self.assertEqual(self.run_cli("import", "--from", str(self.tmp / "none.csv")).code, EXIT_NOT_FOUND)

    def test_restart_keeps_data(self):
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000")
        self.run_cli("category", "add", "cafe")
        # 새 프로세스처럼 main() 을 다시 호출해도 세 파일의 내용이 그대로 읽힌다
        self.assertIn("TX-000005", self.run_cli("list").out)
        self.assertIn("500,000원", self.run_cli("budget", "list").out)
        self.assertIn("- cafe", self.run_cli("category", "list").out)

    def test_command_log_is_written(self):
        self.run_cli("list")
        self.run_cli("delete", "--id", "TX-000099")
        lines = (self.data_dir / "app.log").read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1])
        self.assertEqual((last["command"], last["exit_code"]), ("delete", EXIT_NOT_FOUND))
        self.assertIn("elapsed_ms", last)

    def test_verbose_prints_elapsed_time(self):
        self.assertRegex(self.run_cli("list", "--verbose").err, r"\[시간\] list \d+\.\dms")

    def test_global_option_before_or_after_command(self):
        from budget_app.cli import main
        import io
        out = io.StringIO()
        code = main(["list", "--data-dir", str(self.data_dir), "--plain"], stdout=out, stderr=io.StringIO())
        self.assertEqual(code, EXIT_OK)
        self.assertIn("TX-000005", out.getvalue())


class BonusCliTest(CliTestCase):
    def test_backup_and_restore(self):
        self.add("2024-01-15", "expense", "food", "15000", "점심")
        backup = self.run_cli("backup", "--label", "demo")
        self.assertIn("[백업 완료]", backup.out)
        path = backup.out.strip().split("] ", 1)[1]
        self.run_cli("delete", "--id", "TX-000001")
        self.assertEqual(self.run_cli("restore", "--from", path, stdin="n\n").code, EXIT_INTERRUPTED)
        restored = self.run_cli("restore", "--from", path, "--yes")
        self.assertIn("[복원 완료] transactions.jsonl 1건", restored.out)
        self.assertIn("TX-000001", self.run_cli("list").out)
        self.assertIn("backup-", self.run_cli("backup", "--list").out)

    def test_recurring_flow(self):
        added = self.run_cli("recurring", "add", "--type", "income", "--category", "salary", "--amount", "3000000",
                             "--day", "25", "--memo", "월급")
        self.assertIn("[저장 완료] id=RC-0001", added.out)
        interactive = self.run_cli("recurring", "add", stdin="expense\nrent\n500000\n31\n월세\n\n")
        self.assertIn("id=RC-0002", interactive.out)
        applied = self.run_cli("recurring", "apply", "--month", "2024-02")
        self.assertIn("2024-02-29 expense rent 500,000원 월세", applied.out)
        self.assertIn("created=2, skipped=0", applied.out)
        self.assertIn("created=0, skipped=2", self.run_cli("recurring", "apply", "--month", "2024-02").out)
        self.assertIn("RC-0001", self.run_cli("recurring", "list").out)
        self.assertEqual(self.run_cli("recurring", "remove", "--id", "RC-0009").code, EXIT_NOT_FOUND)


class ErrorHandlingTest(CliTestCase):
    def test_corrupted_data_file_gives_hint_not_traceback(self):
        self.add("2024-01-15", "expense", "food", "15000")
        with (self.data_dir / "transactions.jsonl").open("a", encoding="utf-8") as f:
            f.write("{broken\n")
        result = self.run_cli("list")
        self.assertEqual(result.code, 5)
        self.assertIn("2번째 줄이 손상되었습니다", result.err)
        self.assertIn("[힌트]", result.err)
        self.assertNoTraceback(result)

    def test_unexpected_error_is_hidden_unless_debug(self):
        from unittest import mock
        with mock.patch("budget_app.services.TransactionService.list_latest", side_effect=ZeroDivisionError("boom")):
            normal = self.run_cli("list")
            debug = self.run_cli("list", "--debug")
        self.assertEqual(normal.code, 1)
        self.assertIn("예기치 못한 문제", normal.err)
        self.assertNoTraceback(normal)
        self.assertIn("Traceback", debug.err)

    def test_all_error_exit_codes_are_non_zero(self):
        cases = [("list", "--limit", "x"), ("summary", "--month", "2024-13"), ("budget", "set", "--month", "2024-01",
                 "--amount", "-1"), ("budget", "show", "--month", "2030-01"), ("update", "--id", "bad")]
        for argv in cases:
            with self.subTest(argv=argv):
                result = self.run_cli(*argv)
                self.assertNotEqual(result.code, EXIT_OK)
                self.assertIn("[오류]", result.err)


if __name__ == "__main__":
    unittest.main()
