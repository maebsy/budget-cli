"""[보너스] 출력 포맷터: 외부 라이브러리 없이 표를 정렬한다.

한글은 터미널에서 영문 2글자 폭을 차지하기 때문에 ``str.ljust`` 로 맞추면 열이 어긋난다.
``unicodedata.east_asian_width`` 로 글자마다 화면 폭(1 또는 2)을 계산해 정렬한다.
"""

import unicodedata
from typing import List, Sequence

from .models import Transaction


def display_width(text: str) -> int:
    """터미널에 표시되는 폭. 전각(W, F) 문자는 2칸, 결합 문자는 0칸."""
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def truncate(text: str, max_width: int) -> str:
    """화면 폭 기준으로 자르고 말줄임표를 붙인다."""
    if display_width(text) <= max_width:
        return text
    out, width = [], 0
    for ch in text:
        w = display_width(ch)
        if width + w > max_width - 1:
            break
        out.append(ch)
        width += w
    return "".join(out) + "…"


def pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - display_width(text))
    return " " * gap + text if align == "right" else text + " " * gap


def money(amount: int) -> str:
    return "{:,}원".format(amount)


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], aligns: Sequence[str]) -> List[str]:
    """머리글 + 구분선 + 행. 열 폭은 내용 중 가장 넓은 값에 맞춘다."""
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    lines = ["  ".join(pad(h, widths[i], aligns[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)).rstrip())
    return lines


def transaction_table(txs: Sequence[Transaction]) -> List[str]:
    headers = ("ID", "날짜", "타입", "카테고리", "금액", "메모", "태그")
    rows = []
    for tx in txs:
        rows.append((tx.id, tx.date.isoformat(), tx.type.value, tx.category, money(tx.amount),
                     truncate(tx.memo, 24), " ".join("#" + t for t in tx.tags)))
    return render_table(headers, rows, ("left", "left", "left", "left", "right", "left", "left"))


def transaction_plain(tx: Transaction) -> str:
    """과제 예시와 같은 ``|`` 구분 한 줄 형식 (--plain)."""
    return "{} | {} | {:<7} | {} | {} | {}".format(tx.id, tx.date.isoformat(), tx.type.value, tx.category,
                                                   tx.amount, tx.memo).rstrip()


def progress_bar(ratio: float, width: int = 20) -> str:
    filled = min(width, int(round(min(ratio, 1.0) * width)))
    return "[" + "#" * filled + "." * (width - filled) + "]"
