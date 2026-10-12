"""거래 수(1천 ~ 10만 건)에 따른 명령별 소요 시간과 메모리를 측정한다.

    python scripts/benchmark.py              # 1,000 / 10,000 / 100,000 건
    python scripts/benchmark.py 1000 5000    # 원하는 크기만

결과는 docs/performance.md 의 표를 만드는 데 사용했다. 측정값은 실행 환경에 따라 달라진다.
"""

import random
import shutil
import sys
import tempfile
import time
import tracemalloc
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budget_app.models import SearchFilter, Transaction, TxType  # noqa: E402
from budget_app.services import App, SummaryService, TransactionService  # noqa: E402

CATEGORIES = ("food", "transport", "rent", "shopping", "health", "culture", "etc")


def populate(app: App, n: int) -> None:
    rng = random.Random(42)
    start = date(2020, 1, 1)

    def rows():
        for i in range(1, n + 1):
            yield Transaction("TX-{:06d}".format(i), TxType.EXPENSE if rng.random() < 0.9 else TxType.INCOME,
                              start + timedelta(days=rng.randrange(365 * 5)), rng.randrange(1000, 100000),
                              rng.choice(CATEGORIES), "메모 {}".format(i), ("tag{}".format(i % 5),))

    app.transactions.add_many(rows())


def measure(func, repeat_safe: bool = True):
    """시간은 tracemalloc 없이(추적 비용 제외), 메모리는 tracemalloc 으로 따로 잰다."""
    t0 = time.perf_counter()
    result = func()
    elapsed = (time.perf_counter() - t0) * 1000
    peak_kb = None
    if repeat_safe:
        tracemalloc.start()
        func()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_kb = peak / 1024
    return elapsed, peak_kb, result


def run(n: int) -> None:
    tmp = Path(tempfile.mkdtemp())
    try:
        app = App(str(tmp / "data"))
        populate(app, n)
        size_mb = app.paths.transactions.stat().st_size / 1024 / 1024
        tx = TransactionService(app)
        cases = [
            ("list --limit 20 (스트리밍 + 힙)", lambda: tx.list_latest(20), True),
            ("[비교] 전체를 list 로 로드", lambda: list(app.transactions.iter_all()), True),
            ("search --category food --tag tag1", lambda: tx.search(SearchFilter(category="food", tag="tag1")), True),
            ("summary --month 2022-06", lambda: SummaryService(app).monthly("2022-06"), True),
            ("add (next_id 계산 포함)", lambda: tx.add(TxType.EXPENSE, date(2024, 1, 1), 1000, "food"), True),
            ("update (원자적 재작성)", lambda: tx.update("TX-{:06d}".format(n // 2), {"amount": 1}), True),
            ("delete (원자적 재작성)", lambda: tx.delete("TX-{:06d}".format(n // 3)), False),
        ]
        print("\n### {:,}건 (transactions.jsonl {:.1f} MB)\n".format(n, size_mb))
        print("| 작업 | 시간(ms) | 최대 메모리(KB) |")
        print("| --- | ---: | ---: |")
        for name, func, repeat_safe in cases:
            elapsed, peak_kb, _ = measure(func, repeat_safe)
            print("| {} | {:,.1f} | {} |".format(name, elapsed, "-" if peak_kb is None else "{:,.0f}".format(peak_kb)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sizes = [int(a) for a in sys.argv[1:]] or [1000, 10000, 100000]
    print("Python {} / {}".format(sys.version.split()[0], sys.platform))
    for size in sizes:
        run(size)
