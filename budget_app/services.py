"""서비스 계층: 기능(유스케이스) 로직.

서비스는 "무엇을 할지"를 결정한다. 파일 형식은 저장소(storage)에, 입출력 형식은 CLI 에 맡긴다.
그래서 서비스 함수는 화면 출력 없이 값을 반환하고, 테스트에서 바로 호출해 검증할 수 있다.

스트리밍 원칙
* 목록·검색·요약·내보내기는 저장소의 제너레이터를 한 번 순회하며 처리한다.
* 최신순 상위 N개는 ``heapq.nlargest`` (크기 N 짜리 힙) 로 고른다 → 메모리 O(N), 시간 O(전체 × log N).
"""

import calendar
import csv
import heapq
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import __version__
from .errors import ConflictError, NotFoundError, StorageError, ValidationError
from .models import Budget, Category, RecurringRule, SearchFilter, Transaction, TxType
from .storage import (BudgetStore, CategoryStore, DataPaths, JsonlFile, RecurringStore,
                      TransactionRepository)
from .validators import (month_range, normalize_category, parse_amount, parse_date, parse_memo,
                         parse_tags, parse_type)

CSV_COLUMNS = ("date", "type", "category", "amount", "memo", "tags")
CSV_REQUIRED = ("date", "type", "category", "amount")


def latest_first_key(tx: Transaction) -> Tuple[date, str]:
    """최신순 정렬 기준: 날짜 → 같은 날이면 id(나중에 등록한 것) 순."""
    return (tx.date, tx.id)


# ============================================================================ 앱 컨텍스트
class App:
    """저장소들을 묶어 서비스에 넘겨주는 컨테이너 (의존성 주입)."""

    def __init__(self, data_dir: str) -> None:
        self.paths = DataPaths(data_dir)
        self.created_files = self.paths.ensure()
        self.transactions = TransactionRepository(self.paths)
        self.categories = CategoryStore(self.paths)
        self.budgets = BudgetStore(self.paths)
        self.recurring = RecurringStore(self.paths)
        self.defaults_created = self.categories.ensure_defaults()


# ============================================================================ 거래
class TransactionService:
    """거래 추가·목록·검색·수정·삭제 유스케이스."""
    def __init__(self, app: App) -> None:
        self.app = app
        self.repo = app.transactions

    def require_category(self, name: str) -> str:
        category = normalize_category(name)
        if not self.app.categories.exists(category):
            raise NotFoundError(
                "등록되지 않은 카테고리입니다: {}".format(category),
                "사용 가능: {} (새로 만들려면 category add)".format(", ".join(self.app.categories.names())))
        return category

    def add(self, tx_type: TxType, when: date, amount: int, category: str, memo: str = "",
            tags: Sequence[str] = (), source: Optional[str] = None) -> Transaction:
        category = self.require_category(category)
        tx = Transaction(self.repo.next_id(), tx_type, when, amount, category, memo, tuple(tags), source)
        return self.repo.add(tx)

    def list_latest(self, limit: int) -> List[Transaction]:
        """최신순 상위 limit 건. 파일 전체를 리스트로 만들지 않는다."""
        return heapq.nlargest(limit, self.repo.iter_all(), key=latest_first_key)

    def search(self, flt: SearchFilter, limit: Optional[int] = None) -> List[Transaction]:
        """조건에 맞는 거래를 최신순으로. 조건 검사는 스트리밍, 결과(일치 건)만 메모리에 남는다."""
        matches: Iterator[Transaction] = (tx for tx in self.repo.iter_all() if flt.matches(tx))
        if limit is not None:
            return heapq.nlargest(limit, matches, key=latest_first_key)
        return sorted(matches, key=latest_first_key, reverse=True)

    def update(self, tx_id: str, changes: Dict[str, object]) -> Tuple[Transaction, Transaction]:
        """변경할 필드만 받아 수정한다. (수정 전, 수정 후) 를 반환한다."""
        if not changes:
            raise ValidationError("수정할 항목이 없습니다.",
                                  "--date, --type, --category, --amount, --memo, --tags 중 하나 이상을 지정하세요.")
        if "category" in changes:
            changes["category"] = self.require_category(str(changes["category"]))
        return self.repo.update(tx_id, lambda tx: tx.with_changes(**changes))

    def delete(self, tx_id: str) -> Transaction:
        return self.repo.delete(tx_id)


# ============================================================================ 요약
@dataclass
class MonthlySummary:
    """한 달 집계 결과. 화면 출력과 분리된 순수 데이터라 테스트하기 쉽다."""
    month: str
    income: int = 0
    expense: int = 0
    count: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    budget: Optional[Budget] = None

    @property
    def balance(self) -> int:
        return self.income - self.expense

    @property
    def has_data(self) -> bool:
        return self.count > 0

    @property
    def budget_usage(self) -> Optional[float]:
        """예산 대비 지출 비율(%)."""
        if self.budget is None or self.budget.amount <= 0:
            return None
        return self.expense / self.budget.amount * 100

    @property
    def over_budget(self) -> int:
        return 0 if self.budget is None else max(0, self.expense - self.budget.amount)

    def top_expenses(self, n: int) -> List[Tuple[str, int]]:
        return heapq.nlargest(n, self.by_category.items(), key=lambda kv: (kv[1], kv[0]))


class SummaryService:
    """월별 요약(총수입·총지출·잔액·카테고리별 지출)을 계산한다."""
    def __init__(self, app: App) -> None:
        self.app = app

    def monthly(self, month: str) -> MonthlySummary:
        """한 번의 스트리밍 순회로 총수입/총지출/카테고리별 지출을 집계한다."""
        return self.monthly_many([month])[month]

    def monthly_many(self, months: Sequence[str]) -> Dict[str, MonthlySummary]:
        """여러 달을 **한 번의 순회**로 함께 집계한다 (전월 비교에서 파일을 두 번 읽지 않도록)."""
        summaries = {m: MonthlySummary(m, budget=self.app.budgets.get(m)) for m in months}
        for tx in self.app.transactions.iter_all():
            summary = summaries.get(tx.month)
            if summary is None:
                continue
            summary.count += 1
            if tx.type is TxType.INCOME:
                summary.income += tx.amount
            else:
                summary.expense += tx.amount
                summary.by_category[tx.category] = summary.by_category.get(tx.category, 0) + tx.amount
        return summaries


# ============================================================================ 예산
class BudgetService:
    """월 예산 설정·조회."""
    def __init__(self, app: App) -> None:
        self.app = app

    def set(self, month: str, amount: int) -> Budget:
        return self.app.budgets.set(month, amount)

    def get(self, month: str) -> Budget:
        budget = self.app.budgets.get(month)
        if budget is None:
            raise NotFoundError("{} 예산이 없습니다.".format(month), "budget set --month {} --amount <금액> 으로 설정하세요.".format(month))
        return budget

    def list(self) -> List[Budget]:
        return self.app.budgets.list()


# ============================================================================ 카테고리
class CategoryService:
    """카테고리 추가·목록·삭제. 사용 중인 카테고리는 대체 카테고리 없이 지울 수 없다."""
    def __init__(self, app: App) -> None:
        self.app = app

    def add(self, name: str) -> Category:
        return self.app.categories.add(normalize_category(name))

    def list(self) -> List[Tuple[Category, int]]:
        """(카테고리, 사용 건수). 사용 건수는 거래 파일을 한 번 스트리밍해서 센다."""
        counts: Dict[str, int] = {}
        for tx in self.app.transactions.iter_all():
            counts[tx.category] = counts.get(tx.category, 0) + 1
        return [(c, counts.get(c.name, 0)) for c in self.app.categories.list()]

    def remove(self, name: str, replace_with: Optional[str] = None) -> int:
        """카테고리 삭제. 사용 중이면 대체 카테고리를 요구한다. 옮긴 거래 수를 반환한다."""
        name = normalize_category(name)
        if not self.app.categories.exists(name):
            raise NotFoundError("없는 카테고리입니다: {}".format(name), "category list 로 목록을 확인하세요.")
        in_use = self.app.transactions.count_by_category(name)
        rules_in_use = sum(1 for r in self.app.recurring.list() if r.category == name)
        moved = 0
        if in_use or rules_in_use:
            if replace_with is None:
                raise ConflictError(
                    "카테고리 '{}' 는 거래 {}건{}에서 사용 중이라 삭제할 수 없습니다.".format(
                        name, in_use, ", 반복 규칙 {}건".format(rules_in_use) if rules_in_use else ""),
                    "--replace-with <다른 카테고리> 를 지정하면 거래를 옮긴 뒤 삭제합니다.")
            target = normalize_category(replace_with)
            if target == name:
                raise ValidationError("대체 카테고리가 삭제할 카테고리와 같습니다.", "다른 카테고리를 지정하세요.")
            if not self.app.categories.exists(target):
                raise NotFoundError("대체 카테고리가 없습니다: {}".format(target), "먼저 category add 로 만드세요.")
            moved = self.app.transactions.replace_category(name, target)
            self.app.recurring.replace_category(name, target)
        self.app.categories.remove(name)
        return moved


# ============================================================================ import / export
@dataclass
class ImportReport:
    """import 결과: 성공 건수, 거부된 행(줄 번호·사유), 거부 행 파일 경로."""
    imported: int = 0
    valid: int = 0                                                 # 검증을 통과한 행 수
    skipped: List[Tuple[int, str]] = field(default_factory=list)   # (CSV 줄 번호, 사유)
    rejected_path: Optional[Path] = None
    dry_run: bool = False
    atomic: bool = False

    @property
    def ok(self) -> bool:
        return not self.skipped


class ImportExportService:
    """CSV 스키마: date,type,category,amount[,memo,tags] / UTF-8 / 헤더 포함."""

    def __init__(self, app: App) -> None:
        self.app = app

    # ------------------------------------------------------------------ export
    def export_csv(self, out: Path, flt: SearchFilter, bom: bool = False, force: bool = False) -> int:
        """조건에 맞는 거래를 날짜순으로 CSV 저장. 원자적으로 기록(임시 파일 → 교체)."""
        if out.exists() and not force:
            raise ConflictError("이미 있는 파일입니다: {}".format(out), "--force 로 덮어쓰거나 다른 --out 경로를 지정하세요.")
        rows = sorted((tx for tx in self.app.transactions.iter_all() if flt.matches(tx)), key=lambda t: (t.date, t.id))
        tmp = out.with_name(out.name + ".tmp")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(CSV_COLUMNS)
                for tx in rows:
                    writer.writerow([tx.date.isoformat(), tx.type.value, tx.category, tx.amount, tx.memo,
                                     ",".join(tx.tags)])
            tmp.replace(out)
        except OSError as exc:
            raise StorageError("CSV 를 저장할 수 없습니다: {} ({})".format(out, exc.strerror), "경로와 쓰기 권한을 확인하세요.")
        return len(rows)

    # ------------------------------------------------------------------ import
    def import_csv(self, src: Path, atomic: bool = False, dry_run: bool = False,
                   skip_duplicates: bool = False, create_categories: bool = False) -> ImportReport:
        """CSV 일괄 등록.

        * 기본(부분 성공): 올바른 행만 등록하고, 문제 있는 행은 줄 번호·사유와 함께 보고한다.
          거부된 행은 ``<원본>.rejected.csv`` 에 사유 컬럼을 붙여 저장해 고쳐서 다시 넣을 수 있게 한다.
        * ``--atomic``(롤백): 한 행이라도 문제가 있으면 아무것도 등록하지 않는다.
        * ``--dry-run``: 검증만 하고 저장하지 않는다.
        * ``--skip-duplicates``: 날짜·타입·카테고리·금액·메모가 같은 기존 거래가 있으면 건너뛴다.
        """
        if not src.exists():
            raise NotFoundError("파일이 없습니다: {}".format(src), "경로를 확인하세요.")
        report = ImportReport(dry_run=dry_run, atomic=atomic)
        known = set(self.app.categories.names())
        new_categories: List[str] = []
        existing = set()
        if skip_duplicates:
            existing = {self._signature(tx.date, tx.type, tx.category, tx.amount, tx.memo)
                        for tx in self.app.transactions.iter_all()}

        valid: List[Transaction] = []
        rejected_rows: List[List[str]] = []
        next_number = int(self.app.transactions.next_id()[3:])
        try:
            with src.open("r", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀 BOM 허용
                reader = csv.DictReader(f)
                header = [h.strip().lower() for h in (reader.fieldnames or [])]
                missing = [c for c in CSV_REQUIRED if c not in header]
                if missing:
                    raise ValidationError("CSV 헤더에 필수 컬럼이 없습니다: {}".format(", ".join(missing)),
                                          "첫 줄은 date,type,category,amount,memo,tags 형식이어야 합니다.")
                reader.fieldnames = header
                for lineno, row in enumerate(reader, start=2):
                    try:
                        tx_date = parse_date(row.get("date") or "")
                        tx_type = parse_type(row.get("type") or "")
                        category = normalize_category(row.get("category") or "")
                        amount = parse_amount(row.get("amount") or "")
                        memo = parse_memo(row.get("memo"))
                        tags = parse_tags(row.get("tags"))
                        if category not in known:
                            if not create_categories:
                                raise ValidationError("등록되지 않은 카테고리: {}".format(category))
                            known.add(category)
                            new_categories.append(category)
                        sig = self._signature(tx_date, tx_type, category, amount, memo)
                        if skip_duplicates and sig in existing:
                            raise ValidationError("이미 같은 거래가 있음 (중복)")
                        existing.add(sig)
                    except ValidationError as exc:
                        report.skipped.append((lineno, exc.message))
                        rejected_rows.append([row.get(c) or "" for c in CSV_COLUMNS] + [exc.message])
                        continue
                    valid.append(Transaction("TX-{:06d}".format(next_number), tx_type, tx_date, amount,
                                             category, memo, tags))
                    next_number += 1
        except UnicodeDecodeError:
            raise ValidationError("CSV 를 UTF-8 로 읽을 수 없습니다: {}".format(src), "엑셀에서 'CSV UTF-8' 형식으로 저장하세요.")
        except csv.Error as exc:
            raise ValidationError("CSV 형식 오류: {}".format(exc), "따옴표와 쉼표 짝을 확인하세요.")

        report.valid = len(valid)
        if rejected_rows and not dry_run:
            report.rejected_path = src.with_name(src.stem + ".rejected.csv")
            with report.rejected_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(list(CSV_COLUMNS) + ["error"])
                writer.writerows(rejected_rows)

        if dry_run or (atomic and report.skipped):
            return report

        for name in new_categories:
            self.app.categories.add(name)
        if atomic:
            # 기존 + 신규를 임시 파일에 모두 쓴 뒤 한 번에 교체 → 중간에 실패해도 반쯤 들어간 상태가 없다
            self.app.transactions.replace_all(_chain(self.app.transactions.iter_all(), valid))
            report.imported = len(valid)
        else:
            report.imported = self.app.transactions.add_many(valid)
        return report

    @staticmethod
    def _signature(when: date, tx_type: TxType, category: str, amount: int, memo: str) -> Tuple:
        return (when, tx_type, category, amount, memo.strip())


def _chain(first: Iterable[Transaction], second: Iterable[Transaction]) -> Iterator[Transaction]:
    yield from first
    yield from second


# ============================================================================ 백업 (보너스)
class BackupService:
    """[보너스] 데이터 파일을 타임스탬프가 붙은 zip 으로 백업하고 복원한다."""

    def __init__(self, app: App) -> None:
        self.app = app

    def create(self, label: str = "") -> Path:
        paths = self.app.paths
        paths.backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = "backup-{}{}.zip".format(stamp, "-" + label if label else "")
        target = paths.backups / name
        counter = 1
        while target.exists():  # 같은 초에 두 번 실행해도 덮어쓰지 않도록
            target = paths.backups / name.replace(".zip", "-{}.zip".format(counter))
            counter += 1
        manifest: Dict[str, Any] = {"app": "budget-cli", "version": __version__, "created_at": datetime.now().isoformat(timespec="seconds"),
                    "files": {}}
        tmp = target.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in paths.data_files():
                if path.exists():
                    zf.write(path, arcname=path.name)
                    manifest["files"][path.name] = sum(1 for _ in JsonlFile(path).iter_records())
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        tmp.replace(target)
        return target

    def list(self) -> List[Tuple[Path, int]]:
        if not self.app.paths.backups.exists():
            return []
        files = sorted(self.app.paths.backups.glob("backup-*.zip"), reverse=True)
        return [(p, p.stat().st_size) for p in files]

    def restore(self, src: Path) -> Tuple[Path, Dict[str, int]]:
        """백업 복원. 복원 전에 현재 상태를 자동 백업하고, 파일마다 원자적으로 교체한다."""
        if not src.exists():
            raise NotFoundError("백업 파일이 없습니다: {}".format(src), "backup --list 로 목록을 확인하세요.")
        try:
            with zipfile.ZipFile(src) as zf:
                names = set(zf.namelist())
                if "manifest.json" not in names:
                    raise ValidationError("budget-cli 백업 파일이 아닙니다 (manifest.json 없음).")
                contents = {p.name: zf.read(p.name).decode("utf-8")
                            for p in self.app.paths.data_files() if p.name in names}
        except zipfile.BadZipFile:
            raise ValidationError("zip 파일이 손상되었습니다: {}".format(src))
        for name, text in contents.items():  # 복원 전에 모든 줄이 JSON 인지 검증
            for lineno, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        raise ValidationError("백업 안의 {} {}번째 줄이 손상되었습니다.".format(name, lineno))
        safety = self.create(label="before-restore")
        restored: Dict[str, int] = {}
        for path in self.app.paths.data_files():
            text = contents.get(path.name, "")
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
            JsonlFile(path).rewrite(records)
            restored[path.name] = len(records)
        return safety, restored


# ============================================================================ 반복 내역 (보너스)
@dataclass
class RecurringApplyReport:
    """[보너스] 반복 내역 적용 결과: 새로 만든 거래와 이미 만들어져 건너뛴 규칙."""
    month: str
    created: List[Transaction] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


class RecurringService:
    """[보너스] 반복 규칙을 등록하고, 특정 월에 거래를 자동 생성한다."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.tx_service = TransactionService(app)

    def add(self, tx_type: TxType, category: str, amount: int, day: int, memo: str = "",
            tags: Sequence[str] = ()) -> RecurringRule:
        category = self.tx_service.require_category(category)
        rule = RecurringRule(self.app.recurring.next_id(), tx_type, category, amount, day, memo, tuple(tags))
        return self.app.recurring.add(rule)

    def list(self) -> List[RecurringRule]:
        return self.app.recurring.list()

    def remove(self, rule_id: str) -> RecurringRule:
        return self.app.recurring.remove(rule_id.strip().upper())

    def apply(self, month: str) -> RecurringApplyReport:
        """규칙마다 해당 월 거래를 만든다. 이미 만든 규칙(source 키)은 건너뛴다 → 여러 번 실행해도 안전(멱등)."""
        report = RecurringApplyReport(month)
        rules = self.app.recurring.list()
        if not rules:
            raise NotFoundError("등록된 반복 규칙이 없습니다.", "recurring add 로 먼저 등록하세요.")
        done = {tx.source for tx in self.app.transactions.iter_all() if tx.source and tx.month == month}
        year, mon = int(month[:4]), int(month[5:])
        last_day = calendar.monthrange(year, mon)[1]
        for rule in rules:
            key = "{}@{}".format(rule.id, month)
            if key in done:
                report.skipped.append(rule.id)
                continue
            when = date(year, mon, min(rule.day, last_day))  # 31일 규칙 → 2월엔 28/29일
            tx = self.tx_service.add(rule.type, when, rule.amount, rule.category, rule.memo, rule.tags, source=key)
            report.created.append(tx)
        return report


def month_filter(month: str) -> SearchFilter:
    start, end = month_range(month)
    return SearchFilter(date_from=start, date_to=end)
