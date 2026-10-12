"""입력 검증·정규화 함수.

대화형 입력, 옵션 인자, CSV import 가 모두 같은 함수를 사용한다.
그래서 "같은 값이 입력 경로에 따라 다르게 허용되는" 일이 생기지 않는다.

모든 함수는 문자열을 받아 정규화된 값을 반환하거나, 원인과 힌트를 담은
``ValidationError`` 를 던진다.
"""

import calendar
import re
from datetime import date
from typing import Optional, Tuple

from .errors import ValidationError
from .models import TxType

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_ID_RE = re.compile(r"^TX-\d{6,}$")
MAX_AMOUNT = 10 ** 12          # 1조 원: 오타(0 을 너무 많이 입력)를 잡기 위한 상한
MAX_MEMO = 200
MAX_CATEGORY = 30

_TYPE_ALIASES = {"income": TxType.INCOME, "수입": TxType.INCOME,
                 "expense": TxType.EXPENSE, "지출": TxType.EXPENSE}


def parse_date(text: str) -> date:
    """``YYYY-MM-DD`` 형식의 실제 존재하는 날짜만 허용한다 (예: 2024-02-30 거부)."""
    value = text.strip()
    if not _DATE_RE.match(value):
        raise ValidationError("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).", "예: 2024-01-15")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError("존재하지 않는 날짜입니다: {}".format(value), "월은 01~12, 일은 그 달의 마지막 날까지 입력하세요.")


def parse_month(text: str) -> str:
    """``YYYY-MM`` 형식을 검증하고 그대로 반환한다."""
    value = text.strip()
    if not _MONTH_RE.match(value) or not 1 <= int(value[5:]) <= 12:
        raise ValidationError("월 형식이 올바르지 않습니다 (YYYY-MM).", "예: 2024-01")
    return value


def month_range(month: str) -> Tuple[date, date]:
    """``YYYY-MM`` → (그 달 1일, 그 달 말일)"""
    year, mon = int(month[:4]), int(month[5:])
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def parse_amount(text: str) -> int:
    """양의 정수 금액. ``15,000`` 이나 ``15000원`` 처럼 쉼표·'원'은 허용한다."""
    value = text.strip().replace(",", "").replace("_", "")
    if value.endswith("원"):
        value = value[:-1].strip()
    if not value.lstrip("-").isdigit():
        raise ValidationError("금액은 숫자(정수)로 입력하세요: {}".format(text.strip()), "예: 15000 또는 15,000 (소수점 불가)")
    amount = int(value)
    if amount <= 0:
        raise ValidationError("금액은 0보다 커야 합니다: {}".format(text.strip()), "지출도 양수로 입력하고 타입(expense)으로 구분합니다.")
    if amount > MAX_AMOUNT:
        raise ValidationError("금액이 너무 큽니다: {}".format(text.strip()), "1조 원 이하로 입력하세요.")
    return amount


def parse_type(text: str) -> TxType:
    """``income`` / ``expense`` (한글 ``수입`` / ``지출`` 도 허용)."""
    key = text.strip().lower()
    if key not in _TYPE_ALIASES:
        raise ValidationError("허용되지 않는 타입입니다: {}".format(text.strip()), "income(수입) 또는 expense(지출) 중 하나를 입력하세요.")
    return _TYPE_ALIASES[key]


def normalize_category(text: str) -> str:
    """카테고리 이름 정규화: 앞뒤 공백 제거, 연속 공백 하나로, 영문 소문자."""
    name = " ".join(text.split()).lower()
    if not name:
        raise ValidationError("카테고리 이름이 비어 있습니다.", "예: food, transport, 식비")
    if len(name) > MAX_CATEGORY or "," in name:
        raise ValidationError("카테고리 이름은 쉼표 없이 {}자 이하여야 합니다.".format(MAX_CATEGORY), "예: food")
    return name


def parse_tags(text: Optional[str]) -> Tuple[str, ...]:
    """쉼표로 구분된 태그 → 정규화된 튜플 (소문자, 공백 제거, 중복 제거, 입력 순서 유지)."""
    if not text:
        return ()
    seen = []
    for raw in text.split(","):
        tag = "".join(raw.split()).lower().lstrip("#")
        if tag and tag not in seen:
            seen.append(tag)
    return tuple(seen)


def parse_memo(text: Optional[str]) -> str:
    memo = (text or "").strip()
    if len(memo) > MAX_MEMO:
        raise ValidationError("메모는 {}자 이하로 입력하세요.".format(MAX_MEMO))
    return memo


def parse_positive_int(text: str, name: str, maximum: Optional[int] = None) -> int:
    value = text.strip()
    if not value.isdigit() or int(value) <= 0:
        raise ValidationError("{} 은(는) 1 이상의 정수여야 합니다: {}".format(name, text), "예: 10")
    number = int(value)
    if maximum is not None and number > maximum:
        raise ValidationError("{} 은(는) {} 이하여야 합니다: {}".format(name, maximum, text))
    return number


def parse_tx_id(text: str) -> str:
    value = text.strip().upper()
    if not _ID_RE.match(value):
        raise ValidationError("거래 id 형식이 올바르지 않습니다: {}".format(text), "예: TX-000012 (list 명령으로 id 를 확인하세요)")
    return value


def parse_day(text: str) -> int:
    """반복 내역의 '매달 n일' (1~31)."""
    return parse_positive_int(text, "day", maximum=31)
