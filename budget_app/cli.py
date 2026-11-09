"""CLI 계층: 명령어 파싱 → 입력 검증 → 서비스 호출 → 결과 출력.

규칙
* 옵션은 리눅스 표준인 ``--`` 로 통일한다 (``--limit``, ``--month``, ``--data-dir`` …).
* 모든 명령은 ``--help`` 로 사용법과 예시를 보여준다.
* ``add`` 는 대화형 입력이 기본이다. ``update`` 는 **옵션 방식(안 A)** 으로 고정했다.
* 정상 출력은 stdout, 오류·안내는 stderr 로 보낸다(파이프/리다이렉션 시 섞이지 않도록).
* 핸들러는 ``@command`` 로 감싸서 에러 처리·로그·시간 측정을 공통으로 적용한다.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO

from . import __version__
from .decorators import CommandContext, command
from .errors import EXIT_OK, EXIT_USAGE, Cancelled, ValidationError
from .formatting import format_change, money, progress_bar, render_table, transaction_plain, transaction_table
from .models import SearchFilter, Transaction, TxType
from .prompts import Prompter
from .services import (App, BackupService, BudgetService, CategoryService, ImportExportService,
                       RecurringService, SummaryService, TransactionService, month_filter)
from .validators import (month_range, normalize_category, parse_amount, parse_date, parse_day,
                         parse_memo, parse_month, parse_positive_int, parse_tags, parse_tx_id,
                         parse_type, previous_month)

DEFAULT_DATA_DIR = os.environ.get("BUDGET_DATA_DIR", "./data")
DEFAULT_LIST_LIMIT = 20
BUDGET_WARN_RATIO = 80.0  # 사용률 80% 이상이면 주의 문구


# ============================================================================ 공용 헬퍼
def open_app(ctx: CommandContext) -> App:
    """데이터 폴더를 열고(없으면 생성) 초기 실행 안내를 출력한다."""
    app = App(ctx.args.data_dir)
    ctx.app = app
    if app.created_files:
        ctx.err("[안내] 데이터 파일을 만들었습니다: {}".format(app.paths.root))
    if app.defaults_created:
        ctx.err("[안내] 카테고리가 비어 있어 기본 카테고리를 만들었습니다: {}".format(
            ", ".join(app.categories.names())))
    return app


def prompter(ctx: CommandContext) -> Prompter:
    return Prompter(ctx.stdin, ctx.stdout, ctx.stderr)


def optional(value: Optional[str], parse: Callable[[str], Any]) -> Any:
    return None if value is None else parse(value)


def build_filter(args: argparse.Namespace) -> SearchFilter:
    """search/export 공통 조건 파싱. --month 는 --from/--to 와 함께 쓸 수 없다."""
    month = getattr(args, "month", None)
    date_from = optional(getattr(args, "date_from", None), parse_date)
    date_to = optional(getattr(args, "date_to", None), parse_date)
    if month is not None:
        if date_from or date_to:
            raise ValidationError("--month 와 --from/--to 는 함께 쓸 수 없습니다.", "둘 중 하나만 지정하세요.")
        date_from, date_to = month_range(parse_month(month))
    if date_from and date_to and date_from > date_to:
        raise ValidationError("--from 이 --to 보다 늦습니다: {} > {}".format(date_from, date_to),
                              "기간의 시작일이 종료일보다 앞서야 합니다.")
    return SearchFilter(
        date_from=date_from,
        date_to=date_to,
        category=optional(getattr(args, "category", None), normalize_category),
        type=optional(getattr(args, "type", None), parse_type),
        query=(args.q.strip() or None) if getattr(args, "q", None) is not None else None,
        tag=(parse_tags(args.tag) or (None,))[0] if getattr(args, "tag", None) else None,
    )


def is_empty_filter(flt: SearchFilter) -> bool:
    return flt == SearchFilter()


def print_transactions(ctx: CommandContext, txs: Sequence[Transaction], plain: bool) -> None:
    if plain:
        for tx in txs:
            ctx.out(transaction_plain(tx))
        return
    for line in transaction_table(txs):
        ctx.out(line)


def describe(tx: Transaction) -> str:
    memo = " " + tx.memo if tx.memo else ""
    return "{} {} {} {} {}{}".format(tx.id, tx.date.isoformat(), tx.type.value, tx.category, money(tx.amount), memo)


# ============================================================================ add
@command
def cmd_add(ctx: CommandContext) -> int:
    """대화형으로 거래를 입력받아 저장한다."""
    app = open_app(ctx)
    service = TransactionService(app)
    ask = prompter(ctx)

    when = ask.ask("날짜(YYYY-MM-DD, 엔터=오늘): ", parse_date, optional=True, default=date.today())
    tx_type = ask.ask("타입(income/expense): ", parse_type)
    category = ask.ask("카테고리: ", service.require_category)  # 없는 카테고리면 목록을 힌트로 보여주고 재입력
    amount = ask.ask("금액(양수): ", parse_amount)
    memo = ask.ask("메모(선택): ", parse_memo, optional=True, default="")
    tags = ask.ask("태그(쉼표로 구분, 없으면 엔터): ", parse_tags, optional=True, default=())
    tx = service.add(tx_type, when, amount, category, memo, tags)
    ctx.out("[저장 완료] id={}".format(tx.id))
    return EXIT_OK


# ============================================================================ list / search
@command
def cmd_list(ctx: CommandContext) -> int:
    app = open_app(ctx)
    limit = parse_positive_int(ctx.args.limit, "--limit", maximum=100000)
    txs = TransactionService(app).list_latest(limit)
    if not txs:
        ctx.out("거래 내역이 없습니다. 'add' 로 첫 거래를 등록하세요.")
        return EXIT_OK
    print_transactions(ctx, txs, ctx.args.plain)
    if not ctx.args.plain:
        ctx.out("(최신순 {}건{})".format(len(txs), ", --limit 으로 개수 조절" if len(txs) == limit else ""))
    return EXIT_OK


@command
def cmd_search(ctx: CommandContext) -> int:
    app = open_app(ctx)
    flt = build_filter(ctx.args)
    if is_empty_filter(flt):
        raise ValidationError("검색 조건이 없습니다.",
                              "--from/--to, --month, --category, --type, --q, --tag 중 하나 이상을 지정하세요. "
                              "전체 목록은 list 를 사용하세요.")
    limit = optional(ctx.args.limit, lambda v: parse_positive_int(v, "--limit"))
    txs = TransactionService(app).search(flt, limit)
    if not txs:
        ctx.out("조건에 맞는 거래가 없습니다.")
        return EXIT_OK
    print_transactions(ctx, txs, ctx.args.plain)
    if not ctx.args.plain:
        total_in = sum(t.amount for t in txs if t.type is TxType.INCOME)
        total_out = sum(t.amount for t in txs if t.type is TxType.EXPENSE)
        ctx.out("(검색 결과 {}건 · 수입 {} · 지출 {})".format(len(txs), money(total_in), money(total_out)))
    return EXIT_OK


# ============================================================================ summary
@command
def cmd_summary(ctx: CommandContext) -> int:
    app = open_app(ctx)
    month = parse_month(ctx.args.month) if ctx.args.month else date.today().strftime("%Y-%m")
    top = parse_positive_int(ctx.args.top, "--top", maximum=100)
    prev_month = previous_month(month)
    months = SummaryService(app).monthly_many([month, prev_month] if ctx.args.compare else [month])
    s = months[month]

    ctx.out("[{} 월별 요약]".format(month))
    if not s.has_data:
        ctx.out("데이터 없음: {} 에 등록된 거래가 없습니다.".format(month))
        if s.budget:
            ctx.out("예산: {} (사용률 0.0%)".format(money(s.budget.amount)))
        return EXIT_OK

    ctx.out("총 수입: {}".format(money(s.income)))
    ctx.out("총 지출: {}".format(money(s.expense)))
    ctx.out("잔액: {}".format(money(s.balance)))
    if s.budget is not None and s.budget_usage is not None:
        usage = s.budget_usage
        ctx.out("예산: {} (사용률 {:.1f}%) {}".format(money(s.budget.amount), usage, progress_bar(usage / 100)))
        if s.over_budget > 0:
            ctx.out("[경고] 예산을 {} 초과했습니다!".format(money(s.over_budget)))
        elif round(usage, 1) >= BUDGET_WARN_RATIO:  # 화면에 보이는 값(소수 첫째 자리)으로 판정: 79.99% 는 80.0% 로 보이므로 주의
            ctx.out("[주의] 예산의 {:.1f}% 를 사용했습니다. 남은 예산: {}".format(
                usage, money(s.budget.amount - s.expense)))
        else:
            ctx.out("남은 예산: {}".format(money(s.budget.amount - s.expense)))
    else:
        ctx.out("예산: 미설정 (budget set --month {} --amount <금액>)".format(month))

    if ctx.args.compare:
        prev = months[prev_month]
        ctx.out("")
        ctx.out("[전월 대비] {} → {}".format(prev_month, month))
        if not prev.has_data:
            ctx.out("전월({}) 거래가 없어 비교할 수 없습니다.".format(prev_month))
        else:
            ctx.out("수입: {} → {} ({})".format(money(prev.income), money(s.income),
                                               format_change(prev.income, s.income)))
            ctx.out("지출: {} → {} ({})".format(money(prev.expense), money(s.expense),
                                               format_change(prev.expense, s.expense)))

    ctx.out("")
    ranking = s.top_expenses(top)
    ctx.out("지출 TOP {}".format(top))
    if not ranking:
        ctx.out("(지출 내역 없음)")
    rows = []
    for rank, (category, amount) in enumerate(ranking, start=1):
        share = amount / s.expense * 100 if s.expense else 0
        rows.append(("{})".format(rank), category, money(amount), "{:.1f}%".format(share)))
    if rows:
        for line in render_table(("", "", "", ""), rows, ("left", "left", "right", "right"))[2:]:
            ctx.out(line)
    return EXIT_OK


# ============================================================================ budget
@command
def cmd_budget(ctx: CommandContext) -> int:
    app = open_app(ctx)
    service = BudgetService(app)
    action = ctx.args.action
    if action == "set":
        month = parse_month(ctx.args.month)
        amount = parse_amount(ctx.args.amount)
        budget = service.set(month, amount)
        ctx.out("[저장 완료] {} 예산 {}".format(budget.month, money(budget.amount)))
    elif action == "show":
        month = parse_month(ctx.args.month) if ctx.args.month else date.today().strftime("%Y-%m")
        budget = service.get(month)
        expense = SummaryService(app).monthly(month).expense
        ctx.out("{} 예산: {} / 지출: {} (사용률 {:.1f}%)".format(
            month, money(budget.amount), money(expense), expense / budget.amount * 100))
    else:  # list
        budgets = service.list()
        if not budgets:
            ctx.out("설정된 예산이 없습니다. budget set --month YYYY-MM --amount <금액>")
            return EXIT_OK
        for line in render_table(("월", "예산"), [(b.month, money(b.amount)) for b in budgets], ("left", "right")):
            ctx.out(line)
    return EXIT_OK


# ============================================================================ category
@command
def cmd_category(ctx: CommandContext) -> int:
    app = open_app(ctx)
    service = CategoryService(app)
    action = ctx.args.action
    if action == "add":
        name = ctx.args.name if ctx.args.name else prompter(ctx).ask("카테고리명: ", normalize_category)
        category = service.add(name)
        ctx.out("[저장 완료] category={}".format(category.name))
    elif action == "list":
        for category, used in service.list():
            ctx.out("- {}{}".format(category.name, " ({}건)".format(used) if used else ""))
    else:  # remove
        name = ctx.args.name if ctx.args.name else prompter(ctx).ask("삭제할 카테고리명: ", normalize_category)
        moved = service.remove(name, ctx.args.replace_with)
        if moved:
            ctx.out("[삭제 완료] category={} (거래 {}건을 '{}' 로 옮김)".format(
                normalize_category(name), moved, normalize_category(ctx.args.replace_with)))
        else:
            ctx.out("[삭제 완료] category={}".format(normalize_category(name)))
    return EXIT_OK


# ============================================================================ update / delete
UPDATE_FIELDS = ("date", "type", "category", "amount", "memo", "tags")


@command
def cmd_update(ctx: CommandContext) -> int:
    """옵션 방식(안 A): 지정한 필드만 바꾼다. --memo "" / --tags "" 는 비우기."""
    app = open_app(ctx)
    tx_id = parse_tx_id(ctx.args.id)
    parsers: Dict[str, Callable[[str], Any]] = {
        "date": parse_date, "type": parse_type, "category": normalize_category,
        "amount": parse_amount, "memo": parse_memo, "tags": parse_tags,
    }
    changes: Dict[str, Any] = {}
    for name in UPDATE_FIELDS:
        raw = getattr(ctx.args, name)
        if raw is not None:
            changes[name] = parsers[name](raw)
    before, after = TransactionService(app).update(tx_id, changes)
    ctx.out("[수정 완료] {}".format(after.id))
    for name in UPDATE_FIELDS:
        old, new = getattr(before, name), getattr(after, name)
        if old != new:
            fmt = (lambda v: ",".join(v) or "(없음)") if name == "tags" else (lambda v: str(getattr(v, "value", v)) or "(없음)")
            ctx.out("  {}: {} -> {}".format(name, fmt(old), fmt(new)))
    return EXIT_OK


@command
def cmd_delete(ctx: CommandContext) -> int:
    app = open_app(ctx)
    tx = TransactionService(app).delete(parse_tx_id(ctx.args.id))
    ctx.out("[삭제 완료] {}".format(describe(tx)))
    return EXIT_OK


# ============================================================================ import / export
@command
def cmd_export(ctx: CommandContext) -> int:
    app = open_app(ctx)
    if not (ctx.args.month or ctx.args.date_from or ctx.args.date_to):
        raise ValidationError("내보낼 기간을 지정하세요.",
                              "--month YYYY-MM 또는 --from YYYY-MM-DD --to YYYY-MM-DD 가 필요합니다.")
    flt = build_filter(ctx.args)
    out = Path(ctx.args.out)
    count = ImportExportService(app).export_csv(out, flt, bom=ctx.args.bom, force=ctx.args.force)
    ctx.out("[완료] {} ({} records)".format(out, count))
    return EXIT_OK


@command
def cmd_import(ctx: CommandContext) -> int:
    app = open_app(ctx)
    report = ImportExportService(app).import_csv(
        Path(ctx.args.src), atomic=ctx.args.atomic, dry_run=ctx.args.dry_run,
        skip_duplicates=ctx.args.skip_duplicates, create_categories=ctx.args.create_categories)

    for lineno, reason in report.skipped[:20]:
        ctx.err("[건너뜀] {}번째 줄: {}".format(lineno, reason))
    if len(report.skipped) > 20:
        ctx.err("[건너뜀] … 외 {}건".format(len(report.skipped) - 20))

    if report.dry_run:
        ctx.out("[검증] 가져올 수 있는 행 {}건, 오류 {}건 — 저장하지 않았습니다 (--dry-run)".format(
            report.valid, len(report.skipped)))
        return EXIT_OK if report.ok else EXIT_USAGE
    if report.atomic and report.skipped:
        ctx.out("[롤백] 오류가 있어 아무것도 가져오지 않았습니다: imported=0, skipped={}".format(len(report.skipped)))
        if report.rejected_path:
            ctx.err("[힌트] 거부된 행과 사유: {}".format(report.rejected_path))
        return EXIT_USAGE

    ctx.out("[완료] imported={}, skipped={}".format(report.imported, len(report.skipped)))
    if report.rejected_path:
        ctx.err("[힌트] 거부된 행은 '{}' 에 사유와 함께 저장했습니다. 고쳐서 다시 import 하세요.".format(report.rejected_path))
    return EXIT_OK


# ============================================================================ backup / restore (보너스)
@command
def cmd_backup(ctx: CommandContext) -> int:
    app = open_app(ctx)
    service = BackupService(app)
    if ctx.args.list:
        backups = service.list()
        if not backups:
            ctx.out("백업이 없습니다. 'backup' 으로 만드세요.")
            return EXIT_OK
        rows = [(p.name, "{:,} B".format(size)) for p, size in backups]
        for line in render_table(("백업 파일", "크기"), rows, ("left", "right")):
            ctx.out(line)
        return EXIT_OK
    path = service.create(ctx.args.label or "")
    ctx.out("[백업 완료] {}".format(path))
    return EXIT_OK


@command
def cmd_restore(ctx: CommandContext) -> int:
    app = open_app(ctx)
    src = Path(ctx.args.src)
    if not ctx.args.yes:
        answer = prompter(ctx).ask("현재 데이터를 '{}' 내용으로 덮어씁니다. 계속할까요? (y/N): ".format(src.name),
                                   lambda v: v.strip().lower(), optional=True, default="n")
        if answer not in ("y", "yes"):
            raise Cancelled("복원을 취소했습니다.")
    safety, restored = BackupService(app).restore(src)
    ctx.out("[복원 완료] {}".format(", ".join("{} {}건".format(k, v) for k, v in restored.items())))
    ctx.out("[안내] 복원 직전 상태는 {} 에 백업했습니다.".format(safety))
    return EXIT_OK


# ============================================================================ recurring (보너스)
@command
def cmd_recurring(ctx: CommandContext) -> int:
    app = open_app(ctx)
    service = RecurringService(app)
    action = ctx.args.action
    args = ctx.args
    if action == "add":
        ask = prompter(ctx)

        def value(raw: Optional[str], label: str, parse: Callable[[str], Any], is_optional: bool = False,
                  default: Any = None) -> Any:
            if raw is not None:
                return parse(raw)
            return ask.ask(label, parse, optional=is_optional, default=default)

        # 필수 옵션을 모두 줬다면 스크립트 실행으로 보고 선택 항목(메모·태그)은 묻지 않는다.
        interactive = any(v is None for v in (args.type, args.category, args.amount, args.day))
        if not interactive:
            args.memo = "" if args.memo is None else args.memo
            args.tags = "" if args.tags is None else args.tags
        tx_type = value(args.type, "타입(income/expense): ", parse_type)
        category = value(args.category, "카테고리: ", TransactionService(app).require_category)
        amount = value(args.amount, "금액(양수): ", parse_amount)
        day = value(args.day, "매달 며칠(1~31): ", parse_day)
        memo = value(args.memo, "메모(선택): ", parse_memo, True, "")
        tags = value(args.tags, "태그(쉼표로 구분, 없으면 엔터): ", parse_tags, True, ())
        rule = service.add(tx_type, category, amount, day, memo, tags)
        ctx.out("[저장 완료] id={} (매달 {}일 {} {} {})".format(rule.id, rule.day, rule.type.value, rule.category,
                                                             money(rule.amount)))
    elif action == "list":
        rules = service.list()
        if not rules:
            ctx.out("등록된 반복 규칙이 없습니다. 'recurring add' 로 등록하세요.")
            return EXIT_OK
        rows = [(r.id, "매달 {}일".format(r.day), r.type.value, r.category, money(r.amount), r.memo) for r in rules]
        for line in render_table(("ID", "주기", "타입", "카테고리", "금액", "메모"), rows,
                                 ("left", "left", "left", "left", "right", "left")):
            ctx.out(line)
    elif action == "remove":
        rule = service.remove(args.id)
        ctx.out("[삭제 완료] {} (이미 생성된 거래는 그대로 남습니다)".format(rule.id))
    else:  # apply
        month = parse_month(args.month)
        report = service.apply(month)
        for tx in report.created:
            ctx.out("[생성] {}".format(describe(tx)))
        ctx.out("[완료] {} 반복 내역 created={}, skipped={}{}".format(
            month, len(report.created), len(report.skipped),
            " (이미 생성됨: {})".format(", ".join(report.skipped)) if report.skipped else ""))
    return EXIT_OK


# ============================================================================ 파서
class KoreanArgumentParser(argparse.ArgumentParser):
    """argparse 오류를 '[오류] / [힌트]' 형식으로 바꾼다 (스택트레이스 없음, 종료 코드 2)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        replacements = {
            "the following arguments are required": "다음 옵션이 필요합니다",
            "unrecognized arguments": "알 수 없는 인자",
            "invalid choice": "허용되지 않는 값",
            "expected one argument": "값이 필요합니다",
            "argument": "인자",
            "choose from": "선택 가능",
        }
        for en, ko in replacements.items():
            message = message.replace(en, ko)
        self.print_usage(sys.stderr)
        print("[오류] {}".format(message), file=sys.stderr)
        print("[힌트] '{} --help' 로 사용법을 확인하세요.".format(self.prog), file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _formatter(prog: str) -> argparse.HelpFormatter:
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=32)


def _common_options() -> argparse.ArgumentParser:
    """모든 하위 명령에서 쓸 수 있는 공통 옵션 (명령 앞/뒤 어디에 써도 된다)."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS, metavar="DIR",
                        help="데이터 폴더 (기본: ./data, 환경변수 BUDGET_DATA_DIR)")
    common.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="실행 시간 등 상세 정보 출력")
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="예기치 못한 오류의 상세 정보 출력")
    return common


def _add_filter_options(p: argparse.ArgumentParser, with_type: bool = True) -> None:
    p.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="시작일 (포함)")
    p.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="종료일 (포함)")
    p.add_argument("--month", metavar="YYYY-MM", help="해당 월 전체 (--from/--to 대신)")
    p.add_argument("--category", metavar="NAME", help="카테고리 일치")
    if with_type:
        p.add_argument("--type", metavar="income|expense", help="거래 타입")
    p.add_argument("--q", metavar="KEYWORD", help="메모에 포함된 키워드 (대소문자 무시)")
    p.add_argument("--tag", metavar="TAG", help="태그 일치")


def build_parser() -> argparse.ArgumentParser:
    common = _common_options()
    parser = KoreanArgumentParser(
        prog="python -m budget_app",
        description="표준 라이브러리만으로 만든 콘솔 가계부 (JSONL 파일 저장)",
        epilog="예시:\n  python -m budget_app add\n  python -m budget_app list --limit 5\n"
               "  python -m budget_app summary --month 2024-01 --top 3\n\n"
               "명령별 도움말: python -m budget_app <command> --help",
        formatter_class=_formatter, parents=[common])
    parser.add_argument("--version", action="version", version="budget-cli " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=KoreanArgumentParser)
    sub.required = True

    def add_cmd(name: str, handler: Callable, help_text: str, epilog: str = "") -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text, epilog=epilog,
                           formatter_class=_formatter, parents=[common])
        p.set_defaults(func=handler)
        return p

    add_cmd("add", cmd_add, "거래 추가 (대화형 입력)",
            "날짜 → 타입 → 카테고리 → 금액 → 메모 → 태그 순서로 묻습니다.\n"
            "잘못 입력하면 이유와 예시를 보여주고 다시 묻습니다. Ctrl+C 로 취소.")

    p = add_cmd("list", cmd_list, "거래 목록 (최신순)", "예: python -m budget_app list --limit 10")
    p.add_argument("--limit", default=str(DEFAULT_LIST_LIMIT), metavar="N",
                   help="출력 개수 (기본 {})".format(DEFAULT_LIST_LIMIT))
    p.add_argument("--plain", action="store_true", help="'|' 로 구분한 한 줄 형식")

    p = add_cmd("search", cmd_search, "조건 검색 (최신순, 모든 조건은 AND)",
                "예:\n  python -m budget_app search --from 2024-01-01 --to 2024-01-31 --type expense\n"
                "  python -m budget_app search --category food --q 점심\n  python -m budget_app search --tag meal")
    _add_filter_options(p)
    p.add_argument("--limit", metavar="N", help="최대 출력 개수 (기본: 전체)")
    p.add_argument("--plain", action="store_true", help="'|' 로 구분한 한 줄 형식")

    p = add_cmd("summary", cmd_summary, "월별 요약 (총수입·총지출·잔액·예산 사용률·지출 TOP N)",
                "예:\n  python -m budget_app summary --month 2024-01 --top 3\n"
                "  python -m budget_app summary --month 2024-02 --compare")
    p.add_argument("--month", metavar="YYYY-MM", help="대상 월 (기본: 이번 달)")
    p.add_argument("--top", default="3", metavar="N", help="지출 상위 카테고리 개수 (기본 3)")
    p.add_argument("--compare", action="store_true", help="전월 대비 수입·지출 증감 함께 표시")

    p = add_cmd("budget", cmd_budget, "월 예산 설정/조회",
                "예:\n  python -m budget_app budget set --month 2024-01 --amount 500000\n"
                "  python -m budget_app budget show --month 2024-01\n  python -m budget_app budget list")
    bsub = p.add_subparsers(dest="action", metavar="<set|show|list>", parser_class=KoreanArgumentParser)
    bsub.required = True
    bp = bsub.add_parser("set", help="월 예산 저장 (같은 달은 덮어씀)", parents=[common])
    bp.add_argument("--month", required=True, metavar="YYYY-MM")
    bp.add_argument("--amount", required=True, metavar="AMOUNT")
    bp = bsub.add_parser("show", help="월 예산과 사용률", parents=[common])
    bp.add_argument("--month", metavar="YYYY-MM", help="기본: 이번 달")
    bsub.add_parser("list", help="설정된 모든 예산", parents=[common])

    p = add_cmd("category", cmd_category, "카테고리 관리",
                "예:\n  python -m budget_app category add          (이름을 대화형으로 입력)\n"
                "  python -m budget_app category add cafe\n  python -m budget_app category list\n"
                "  python -m budget_app category remove cafe --replace-with food")
    csub = p.add_subparsers(dest="action", metavar="<add|list|remove>", parser_class=KoreanArgumentParser)
    csub.required = True
    cp = csub.add_parser("add", help="카테고리 추가", parents=[common])
    cp.add_argument("name", nargs="?", help="카테고리명 (생략하면 대화형 입력)")
    csub.add_parser("list", help="카테고리 목록과 사용 건수", parents=[common])
    cp = csub.add_parser("remove", help="카테고리 삭제 (사용 중이면 --replace-with 필요)", parents=[common])
    cp.add_argument("name", nargs="?", help="카테고리명 (생략하면 대화형 입력)")
    cp.add_argument("--replace-with", metavar="NAME", help="사용 중인 거래를 옮길 카테고리")

    p = add_cmd("update", cmd_update, "거래 수정 (옵션 방식: 지정한 항목만 변경)",
                "예:\n  python -m budget_app update --id TX-000012 --amount 18000 --memo \"점심(회식)\"\n"
                "  python -m budget_app update --id TX-000012 --tags \"\"     (태그 비우기)")
    p.add_argument("--id", required=True, metavar="TX-000000")
    p.add_argument("--date", metavar="YYYY-MM-DD")
    p.add_argument("--type", metavar="income|expense")
    p.add_argument("--category", metavar="NAME")
    p.add_argument("--amount", metavar="AMOUNT")
    p.add_argument("--memo", metavar="TEXT", help='빈 문자열("")이면 메모 삭제')
    p.add_argument("--tags", metavar="a,b", help='쉼표 구분, 빈 문자열("")이면 태그 삭제')

    p = add_cmd("delete", cmd_delete, "거래 삭제", "예: python -m budget_app delete --id TX-000012")
    p.add_argument("--id", required=True, metavar="TX-000000")

    p = add_cmd("export", cmd_export, "CSV 내보내기 (UTF-8, 헤더 포함)",
                "기간 조건(--month 또는 --from/--to)이 필수입니다.\n"
                "예:\n  python -m budget_app export --out export.csv --month 2024-01\n"
                "  python -m budget_app export --out q1.csv --from 2024-01-01 --to 2024-03-31 --type expense")
    p.add_argument("--out", required=True, metavar="FILE.csv")
    _add_filter_options(p)
    p.add_argument("--bom", action="store_true", help="엑셀에서 한글이 깨지지 않도록 UTF-8 BOM 추가")
    p.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")

    p = add_cmd("import", cmd_import, "CSV 가져오기 (date,type,category,amount[,memo,tags])",
                "기본은 부분 성공: 올바른 행만 저장하고, 거부된 행은 <파일>.rejected.csv 에 사유와 함께 남깁니다.\n"
                "예:\n  python -m budget_app import --from import.csv\n"
                "  python -m budget_app import --from import.csv --atomic      (하나라도 틀리면 전체 취소)\n"
                "  python -m budget_app import --from import.csv --dry-run     (검증만)")
    p.add_argument("--from", dest="src", required=True, metavar="FILE.csv")
    p.add_argument("--atomic", action="store_true", help="한 행이라도 오류면 아무것도 저장하지 않음 (롤백)")
    p.add_argument("--dry-run", action="store_true", help="검증만 하고 저장하지 않음")
    p.add_argument("--skip-duplicates", action="store_true", help="같은 날짜·타입·카테고리·금액·메모 거래는 건너뜀")
    p.add_argument("--create-categories", action="store_true", help="없는 카테고리는 자동 등록")

    p = add_cmd("backup", cmd_backup, "[보너스] 데이터 백업 (타임스탬프 zip)",
                "예:\n  python -m budget_app backup\n  python -m budget_app backup --label before-import\n"
                "  python -m budget_app backup --list")
    p.add_argument("--label", metavar="TEXT", help="파일 이름에 붙일 설명")
    p.add_argument("--list", action="store_true", help="백업 목록")

    p = add_cmd("restore", cmd_restore, "[보너스] 백업 복원 (복원 직전 상태는 자동 백업)",
                "예: python -m budget_app restore --from data/backups/backup-20240115-093000.zip")
    p.add_argument("--from", dest="src", required=True, metavar="BACKUP.zip")
    p.add_argument("--yes", action="store_true", help="확인 질문 없이 복원")

    p = add_cmd("recurring", cmd_recurring, "[보너스] 반복 내역 (월급·월세 등) 등록과 월별 자동 생성",
                "예:\n  python -m budget_app recurring add --type income --category salary --amount 3000000 --day 25 --memo 월급\n"
                "  python -m budget_app recurring list\n  python -m budget_app recurring apply --month 2024-02\n"
                "  python -m budget_app recurring remove --id RC-0001")
    rsub = p.add_subparsers(dest="action", metavar="<add|list|remove|apply>", parser_class=KoreanArgumentParser)
    rsub.required = True
    rp = rsub.add_parser("add", help="반복 규칙 등록 (빠진 옵션은 대화형으로 입력)", parents=[common])
    rp.add_argument("--type", metavar="income|expense")
    rp.add_argument("--category", metavar="NAME")
    rp.add_argument("--amount", metavar="AMOUNT")
    rp.add_argument("--day", metavar="1-31", help="매달 며칠 (그 달에 없는 날은 말일)")
    rp.add_argument("--memo", metavar="TEXT")
    rp.add_argument("--tags", metavar="a,b")
    rsub.add_parser("list", help="반복 규칙 목록", parents=[common])
    rp = rsub.add_parser("remove", help="반복 규칙 삭제", parents=[common])
    rp.add_argument("--id", required=True, metavar="RC-0000")
    rp = rsub.add_parser("apply", help="해당 월 거래 생성 (여러 번 실행해도 중복 생성 안 함)", parents=[common])
    rp.add_argument("--month", required=True, metavar="YYYY-MM")
    return parser


# ============================================================================ 진입점
def main(argv: Optional[List[str]] = None, stdin: Optional[TextIO] = None,
         stdout: Optional[TextIO] = None, stderr: Optional[TextIO] = None) -> int:
    """CLI 진입점. 테스트에서 입출력 스트림을 주입할 수 있다. 종료 코드를 반환한다."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    for stream in (stdout, stderr):  # 콘솔 인코딩이 한글을 못 쓰는 환경에서도 죽지 않도록
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass

    parser = build_parser()
    real_streams = (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = stdout, stderr  # argparse 의 --help/에러 출력도 주입한 스트림으로
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    finally:
        sys.stdout, sys.stderr = real_streams

    for name, default in (("data_dir", DEFAULT_DATA_DIR), ("verbose", False), ("debug", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    ctx = CommandContext(args, stdout=stdout, stderr=stderr, stdin=stdin or sys.stdin)
    return args.func(ctx)
