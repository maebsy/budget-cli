"""저장소 계층 테스트: 스트리밍 읽기, 원자적 재작성, 손상 파일 처리."""

import inspect
import json
import shutil
import tempfile
import tracemalloc
import unittest
from datetime import date
from pathlib import Path

from budget_app.errors import NotFoundError, StorageError
from budget_app.models import Transaction, TxType
from budget_app.services import App, TransactionService
from budget_app.storage import DEFAULT_CATEGORIES, JsonlFile, TransactionRepository


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="budget-storage-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class JsonlFileTest(TempDirTestCase):
    def test_iter_records_is_a_generator(self):
        self.assertTrue(inspect.isgeneratorfunction(JsonlFile.iter_records))
        self.assertTrue(inspect.isgeneratorfunction(TransactionRepository.iter_all))

    def test_append_then_stream(self):
        f = JsonlFile(self.tmp / "a.jsonl")
        f.append([{"n": 1}, {"n": 2}])
        f.append([{"n": 3}])
        self.assertEqual([r["n"] for r in f.iter_records()], [1, 2, 3])

    def test_korean_is_stored_as_readable_utf8(self):
        f = JsonlFile(self.tmp / "k.jsonl")
        f.append([{"memo": "점심"}])
        self.assertIn("점심", (self.tmp / "k.jsonl").read_text(encoding="utf-8"))

    def test_rewrite_replaces_content(self):
        f = JsonlFile(self.tmp / "b.jsonl")
        f.append([{"n": i} for i in range(5)])
        f.rewrite(r for r in f.iter_records() if r["n"] % 2 == 0)  # 원본을 읽으면서 다시 써도 안전
        self.assertEqual([r["n"] for r in f.iter_records()], [0, 2, 4])

    def test_failed_rewrite_keeps_original_and_cleans_temp_file(self):
        path = self.tmp / "c.jsonl"
        f = JsonlFile(path)
        f.append([{"n": 1}, {"n": 2}])
        before = path.read_bytes()

        def exploding():
            yield {"n": 100}
            raise RuntimeError("디스크가 가득 찬 상황을 흉내")

        with self.assertRaises(RuntimeError):
            f.rewrite(exploding())
        self.assertEqual(path.read_bytes(), before)               # 원본 그대로
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])        # 임시 파일 정리됨

    def test_corrupted_line_reports_line_number(self):
        path = self.tmp / "d.jsonl"
        path.write_text('{"n": 1}\n{"n": \n', encoding="utf-8")
        with self.assertRaises(StorageError) as cm:
            list(JsonlFile(path).iter_records())
        self.assertIn("2번째 줄", cm.exception.message)
        self.assertIn("restore", cm.exception.hint)

    def test_blank_lines_are_ignored(self):
        path = self.tmp / "e.jsonl"
        path.write_text('\n{"n": 1}\n\n', encoding="utf-8")
        self.assertEqual(list(JsonlFile(path).iter_records()), [{"n": 1}])


class RepositoryTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.app = App(str(self.tmp / "data"))
        self.repo = self.app.transactions

    def _tx(self, n: int, day: int = 1) -> Transaction:
        return Transaction("TX-{:06d}".format(n), TxType.EXPENSE, date(2024, 1, day), 1000 * n, "food")

    def test_creates_three_plus_files_and_default_categories(self):
        names = sorted(p.name for p in (self.tmp / "data").iterdir())
        for required in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl"):
            self.assertIn(required, names)
        self.assertTrue(self.app.defaults_created)
        self.assertEqual(tuple(self.app.categories.names()), DEFAULT_CATEGORIES)

    def test_defaults_are_created_only_once(self):
        self.app.categories.remove("etc")
        again = App(str(self.tmp / "data"))
        self.assertFalse(again.defaults_created)
        self.assertNotIn("etc", again.categories.names())

    def test_next_id_follows_highest_number(self):
        self.assertEqual(self.repo.next_id(), "TX-000001")
        self.repo.add(self._tx(7))
        self.assertEqual(self.repo.next_id(), "TX-000008")

    def test_update_and_delete_unknown_id_do_not_touch_file(self):
        self.repo.add(self._tx(1))
        path = self.app.paths.transactions
        before = path.stat().st_mtime_ns, path.read_bytes()
        with self.assertRaises(NotFoundError):
            self.repo.update("TX-999999", lambda t: t)
        with self.assertRaises(NotFoundError):
            self.repo.delete("TX-999999")
        self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), before)

    def test_update_changes_only_target(self):
        for n in (1, 2, 3):
            self.repo.add(self._tx(n))
        self.repo.update("TX-000002", lambda t: t.with_changes(amount=1))
        amounts = {t.id: t.amount for t in self.repo.iter_all()}
        self.assertEqual(amounts, {"TX-000001": 1000, "TX-000002": 1, "TX-000003": 3000})
        updated = self.repo.get("TX-000002")
        self.assertIsNotNone(updated.updated_at)

    def test_data_survives_reopen(self):
        """프로그램을 다시 실행해도 데이터가 유지된다 (파일 기반 영속성)."""
        self.repo.add(self._tx(1))
        self.app.budgets.set("2024-01", 500000)
        self.app.categories.add("cafe")
        reopened = App(str(self.tmp / "data"))
        self.assertEqual(reopened.transactions.get("TX-000001").amount, 1000)
        self.assertEqual(reopened.budgets.get("2024-01").amount, 500000)
        self.assertIn("cafe", reopened.categories.names())

    def test_budget_set_is_upsert(self):
        self.app.budgets.set("2024-02", 100)
        self.app.budgets.set("2024-01", 200)
        self.app.budgets.set("2024-02", 300)
        self.assertEqual([(b.month, b.amount) for b in self.app.budgets.list()], [("2024-01", 200), ("2024-02", 300)])

    def test_record_round_trip(self):
        tx = Transaction("TX-000001", TxType.INCOME, date(2024, 1, 1), 5, "salary", "메모", ("a", "b"), "RC-0001@2024-01")
        line = json.dumps(tx.to_record(), ensure_ascii=False)
        self.assertEqual(Transaction.from_record(json.loads(line)), tx)


class StreamingMemoryTest(TempDirTestCase):
    """list 가 파일 전체를 메모리에 올리지 않는지 메모리 사용량으로 확인한다."""

    def test_list_latest_uses_far_less_memory_than_loading_everything(self):
        app = App(str(self.tmp / "data"))
        app.transactions.add_many(
            Transaction("TX-{:06d}".format(i), TxType.EXPENSE, date(2024, 1 + i % 12, 1 + i % 28), 1000 + i, "food",
                        "메모 {}".format(i), ("tag",)) for i in range(1, 8001))
        service = TransactionService(app)

        tracemalloc.start()
        latest = service.list_latest(10)
        _, streaming_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        everything = list(app.transactions.iter_all())
        _, full_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertEqual(len(latest), 10)
        self.assertEqual(len(everything), 8000)
        self.assertLess(streaming_peak * 10, full_peak, (streaming_peak, full_peak))


if __name__ == "__main__":
    unittest.main()
