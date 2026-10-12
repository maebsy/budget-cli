"""저장소 계층: JSONL 파일 입출력.

저장 형식은 **JSONL** (한 줄 = JSON 객체 하나) 이다.

* 읽기: 파일을 한 줄씩 읽어 ``yield`` 하는 제너레이터 → 파일 크기와 무관하게 메모리 O(1)
* 추가: 파일 끝에 한 줄 append → 기존 데이터를 다시 쓰지 않음
* 수정/삭제: 원본을 한 줄씩 읽으며 **임시 파일**에 새 내용을 쓰고, 다 쓰면 ``os.replace`` 로
  원본과 한 번에 교체한다(원자적 교체). 쓰는 도중 프로그램이 죽어도 원본은 그대로 남는다.

파일 구성 (``--data-dir``, 기본 ``./data``)

==========================  ===============================
transactions.jsonl          거래 내역
categories.jsonl            카테고리 목록
budgets.jsonl               월 예산
recurring.jsonl             [보너스] 반복 내역 규칙
app.log                     실행 로그 (데코레이터가 기록)
backups/                    [보너스] 백업 zip
==========================  ===============================
"""

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .errors import ConflictError, NotFoundError, StorageError
from .models import Budget, Category, RecurringRule, Transaction, now_iso

Record = Dict[str, Any]

DEFAULT_CATEGORIES = ("food", "transport", "rent", "shopping", "health",
                      "education", "culture", "salary", "allowance", "etc")


class DataPaths:
    """데이터 폴더 안의 파일 경로 모음."""

    def __init__(self, data_dir: str) -> None:
        self.root = Path(data_dir)
        self.transactions = self.root / "transactions.jsonl"
        self.categories = self.root / "categories.jsonl"
        self.budgets = self.root / "budgets.jsonl"
        self.recurring = self.root / "recurring.jsonl"
        self.log = self.root / "app.log"
        self.backups = self.root / "backups"

    def data_files(self) -> Tuple[Path, ...]:
        return (self.transactions, self.categories, self.budgets, self.recurring)

    def ensure(self) -> bool:
        """폴더와 빈 데이터 파일을 만든다. 새로 만든 파일이 있으면 True."""
        created = False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            for path in self.data_files():
                if not path.exists():
                    path.touch()
                    created = True
        except OSError as exc:
            raise StorageError("데이터 폴더를 만들 수 없습니다: {} ({})".format(self.root, exc.strerror),
                               "--data-dir 로 쓰기 권한이 있는 폴더를 지정하세요.")
        return created


class JsonlFile:
    """JSONL 파일 하나를 다루는 저수준 도구."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def iter_records(self) -> Iterator[Record]:
        """레코드를 한 줄씩 읽어 반환하는 제너레이터. 빈 줄은 건너뛴다.

        손상된 줄을 조용히 버리면 데이터가 사라진 줄 모르게 되므로, 줄 번호와 함께 에러를 낸다.
        """
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        raise StorageError(
                            "{} 의 {}번째 줄이 손상되었습니다.".format(self.path.name, lineno),
                            "해당 줄을 직접 고치거나 'restore' 로 백업을 복원하세요.")
                    if not isinstance(record, dict):
                        raise StorageError("{} 의 {}번째 줄이 객체 형식이 아닙니다.".format(self.path.name, lineno))
                    yield record
        except OSError as exc:
            raise StorageError("파일을 읽을 수 없습니다: {} ({})".format(self.path, exc.strerror))

    def append(self, records: Iterable[Record]) -> int:
        """파일 끝에 레코드를 추가한다. 디스크까지 기록(fsync)한 뒤 반환한다."""
        count = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise StorageError("파일에 쓸 수 없습니다: {} ({})".format(self.path, exc.strerror),
                               "디스크 공간과 쓰기 권한을 확인하세요.")
        return count

    def rewrite(self, records: Iterable[Record]) -> int:
        """[보너스: 저장 원자성] 전체 내용을 임시 파일에 쓴 뒤 원본과 원자적으로 교체한다.

        1) 같은 폴더에 임시 파일 생성 (같은 파일 시스템이어야 os.replace 가 원자적)
        2) 레코드를 한 줄씩 기록 → flush → fsync (디스크까지 확실히 기록)
        3) os.replace(임시, 원본) — 운영체제가 보장하는 한 번의 교체
        4) 중간에 예외가 나면 임시 파일만 지우고 원본은 그대로 둔다

        ``records`` 가 원본 파일을 읽는 제너레이터여도 안전하다(원본은 3단계 전까지 그대로).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        count = 0
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        except BaseException as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            if isinstance(exc, OSError):
                raise StorageError("파일을 저장하지 못했습니다: {} ({})".format(self.path, exc.strerror),
                                   "다른 프로그램(예: 엑셀)이 파일을 열고 있지 않은지 확인하세요.")
            raise
        return count


# ============================================================================ 거래
class TransactionRepository:
    """거래 내역 저장소. 전체를 메모리에 올리는 메서드는 제공하지 않는다."""

    ID_PREFIX = "TX-"

    def __init__(self, paths: DataPaths) -> None:
        self.file = JsonlFile(paths.transactions)

    def iter_all(self) -> Iterator[Transaction]:
        """모든 거래를 파일 순서대로 하나씩 반환한다 (스트리밍)."""
        for record in self.file.iter_records():
            yield Transaction.from_record(record)

    def next_id(self) -> str:
        """가장 큰 번호 + 1. 파일을 한 번 훑지만 한 줄씩 읽으므로 메모리는 일정하다."""
        highest = 0
        for record in self.file.iter_records():
            raw = str(record.get("id", ""))
            if raw.startswith(self.ID_PREFIX) and raw[len(self.ID_PREFIX):].isdigit():
                highest = max(highest, int(raw[len(self.ID_PREFIX):]))
        return "{}{:06d}".format(self.ID_PREFIX, highest + 1)

    def get(self, tx_id: str) -> Optional[Transaction]:
        for tx in self.iter_all():
            if tx.id == tx_id:
                return tx
        return None

    def add(self, tx: Transaction) -> Transaction:
        self.file.append([tx.to_record()])
        return tx

    def add_many(self, txs: Iterable[Transaction]) -> int:
        return self.file.append(tx.to_record() for tx in txs)

    def update(self, tx_id: str, change: Callable[[Transaction], Transaction]) -> Tuple[Transaction, Transaction]:
        """id 가 같은 거래 하나를 ``change`` 결과로 바꿔 원자적으로 다시 쓴다. (수정 전, 수정 후) 반환.

        파일을 **한 번만** 읽는다: 읽으면서 임시 파일에 쓰고, 끝까지 읽었는데 대상이 없으면
        제너레이터가 NotFoundError 를 던진다 → rewrite() 가 임시 파일을 지우고 원본은 건드리지 않는다.
        """
        found: List[Tuple[Transaction, Transaction]] = []

        def rewritten() -> Iterator[Record]:
            for tx in self.iter_all():
                if tx.id == tx_id:
                    new = change(tx)
                    found.append((tx, new))
                    tx = new
                yield tx.to_record()
            self._raise_if_missing(found, tx_id)

        self.file.rewrite(rewritten())
        return found[0]

    def delete(self, tx_id: str) -> Transaction:
        """id 가 같은 거래를 빼고 원자적으로 다시 쓴다. 삭제한 거래를 반환한다 (한 번의 순회)."""
        found: List[Transaction] = []

        def rewritten() -> Iterator[Record]:
            for tx in self.iter_all():
                if tx.id == tx_id:
                    found.append(tx)
                    continue
                yield tx.to_record()
            self._raise_if_missing(found, tx_id)

        self.file.rewrite(rewritten())
        return found[0]

    @staticmethod
    def _raise_if_missing(found: List[Any], tx_id: str) -> None:
        if not found:
            raise NotFoundError("id={} 거래를 찾을 수 없습니다.".format(tx_id), "list 또는 search 로 id 를 확인하세요.")

    def count_by_category(self, category: str) -> int:
        return sum(1 for tx in self.iter_all() if tx.category == category)

    def replace_category(self, old: str, new: str) -> int:
        """카테고리 이름을 일괄 변경하고 바뀐 건수를 반환한다 (원자적 재작성)."""
        changed = [0]

        def rewritten() -> Iterator[Record]:
            for tx in self.iter_all():
                if tx.category == old:
                    tx = tx.with_changes(category=new)
                    changed[0] += 1
                yield tx.to_record()

        self.file.rewrite(rewritten())
        return changed[0]

    def replace_all(self, txs: Iterable[Transaction]) -> int:
        """기존 + 새 거래 전체를 원자적으로 기록할 때 사용 (import --atomic)."""
        return self.file.rewrite(tx.to_record() for tx in txs)


# ============================================================================ 카테고리
class CategoryStore:
    """카테고리 목록. 수가 적으므로 목록 전체를 다뤄도 된다."""

    def __init__(self, paths: DataPaths) -> None:
        self.file = JsonlFile(paths.categories)

    def list(self) -> List[Category]:
        return [Category.from_record(r) for r in self.file.iter_records()]

    def names(self) -> List[str]:
        return [c.name for c in self.list()]

    def exists(self, name: str) -> bool:
        return name in self.names()

    def is_empty(self) -> bool:
        return next(self.file.iter_records(), None) is None

    def ensure_defaults(self) -> bool:
        """(안 A) 카테고리 파일이 비어 있으면 기본 카테고리를 만든다. 만들었으면 True."""
        if not self.is_empty():
            return False
        self.file.rewrite(Category(name).to_record() for name in DEFAULT_CATEGORIES)
        return True

    def add(self, name: str) -> Category:
        if self.exists(name):
            raise ConflictError("이미 있는 카테고리입니다: {}".format(name), "category list 로 목록을 확인하세요.")
        category = Category(name)
        self.file.append([category.to_record()])
        return category

    def remove(self, name: str) -> None:
        remaining = [c for c in self.list() if c.name != name]
        self.file.rewrite(c.to_record() for c in remaining)


# ============================================================================ 예산
class BudgetStore:
    """월 예산. 같은 달은 하나만 유지(upsert)."""

    def __init__(self, paths: DataPaths) -> None:
        self.file = JsonlFile(paths.budgets)

    def list(self) -> List[Budget]:
        return [Budget.from_record(r) for r in self.file.iter_records()]

    def get(self, month: str) -> Optional[Budget]:
        for budget in self.list():
            if budget.month == month:
                return budget
        return None

    def set(self, month: str, amount: int) -> Budget:
        budget = Budget(month, amount, now_iso())
        others = [b for b in self.list() if b.month != month]
        rows = others + [budget]
        rows.sort(key=lambda b: b.month)
        self.file.rewrite(b.to_record() for b in rows)
        return budget


# ============================================================================ 반복 규칙 (보너스)
class RecurringStore:
    """[보너스] 반복 규칙 저장소 (recurring.jsonl)."""

    ID_PREFIX = "RC-"

    def __init__(self, paths: DataPaths) -> None:
        self.file = JsonlFile(paths.recurring)

    def list(self) -> List[RecurringRule]:
        return [RecurringRule.from_record(r) for r in self.file.iter_records()]

    def next_id(self) -> str:
        highest = 0
        for rule in self.list():
            if rule.id[len(self.ID_PREFIX):].isdigit():
                highest = max(highest, int(rule.id[len(self.ID_PREFIX):]))
        return "{}{:04d}".format(self.ID_PREFIX, highest + 1)

    def add(self, rule: RecurringRule) -> RecurringRule:
        self.file.append([rule.to_record()])
        return rule

    def remove(self, rule_id: str) -> RecurringRule:
        rules = self.list()
        target = next((r for r in rules if r.id == rule_id), None)
        if target is None:
            raise NotFoundError("반복 규칙 {} 을(를) 찾을 수 없습니다.".format(rule_id), "recurring list 로 id 를 확인하세요.")
        self.file.rewrite(r.to_record() for r in rules if r.id != rule_id)
        return target

    def replace_category(self, old: str, new: str) -> int:
        rules = self.list()
        changed = sum(1 for r in rules if r.category == old)
        if changed:
            self.file.rewrite((replace(r, category=new) if r.category == old else r).to_record() for r in rules)
        return changed
