"""데이터 모델 계층: 거래 · 예산 · 카테고리 · 반복 규칙.

모델은 "데이터가 어떤 모양이고 어떤 값이 올바른가"만 안다. 파일이나 화면은 모른다.
저장 형식(JSONL 한 줄)과의 변환은 ``to_record`` / ``from_record`` 로 모델 안에 둔다.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class TxType(str, Enum):
    """거래 타입. ``str`` 을 상속해 JSON/CSV 에 그대로 쓸 수 있다."""

    INCOME = "income"
    EXPENSE = "expense"

    def label(self) -> str:
        return "수입" if self is TxType.INCOME else "지출"


def now_iso() -> str:
    """기록용 타임스탬프 (초 단위)."""
    return datetime.now().replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Transaction:
    """거래 1건. ``frozen=True`` 라 수정은 ``with_changes()`` 로 새 객체를 만든다."""

    id: str
    type: TxType
    date: date
    amount: int                       # 원 단위 양의 정수 (float 오차를 피하기 위해 int)
    category: str
    memo: str = ""
    tags: Tuple[str, ...] = ()
    source: Optional[str] = None      # 반복 내역으로 생성됐다면 "RC-0001@2024-01" (중복 생성 방지 키)
    created_at: str = field(default_factory=now_iso)
    updated_at: Optional[str] = None

    @property
    def month(self) -> str:
        return self.date.strftime("%Y-%m")

    @property
    def signed_amount(self) -> int:
        return self.amount if self.type is TxType.INCOME else -self.amount

    def with_changes(self, **changes: Any) -> "Transaction":
        return replace(self, updated_at=now_iso(), **changes)

    def to_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "date": self.date.isoformat(),
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": list(self.tags),
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Transaction":
        return cls(
            id=str(record["id"]),
            type=TxType(record["type"]),
            date=date.fromisoformat(record["date"]),
            amount=int(record["amount"]),
            category=str(record["category"]),
            memo=str(record.get("memo") or ""),
            tags=tuple(record.get("tags") or ()),
            source=record.get("source"),
            created_at=str(record.get("created_at") or ""),
            updated_at=record.get("updated_at"),
        )


@dataclass(frozen=True)
class Budget:
    """월 예산."""

    month: str          # YYYY-MM
    amount: int
    updated_at: str = field(default_factory=now_iso)

    def to_record(self) -> Dict[str, Any]:
        return {"month": self.month, "amount": self.amount, "updated_at": self.updated_at}

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Budget":
        return cls(str(record["month"]), int(record["amount"]), str(record.get("updated_at") or ""))


@dataclass(frozen=True)
class Category:
    """거래 분류."""

    name: str
    created_at: str = field(default_factory=now_iso)

    def to_record(self) -> Dict[str, Any]:
        return {"name": self.name, "created_at": self.created_at}

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Category":
        return cls(str(record["name"]), str(record.get("created_at") or ""))


@dataclass(frozen=True)
class RecurringRule:
    """[보너스] 월급·월세처럼 매달 반복되는 거래 규칙."""

    id: str
    type: TxType
    category: str
    amount: int
    day: int                 # 1~31. 그 달에 없는 날(예: 2월 30일)은 말일로 맞춘다
    memo: str = ""
    tags: Tuple[str, ...] = ()
    created_at: str = field(default_factory=now_iso)

    def to_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "category": self.category,
            "amount": self.amount,
            "day": self.day,
            "memo": self.memo,
            "tags": list(self.tags),
            "created_at": self.created_at,
        }

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "RecurringRule":
        return cls(
            id=str(record["id"]),
            type=TxType(record["type"]),
            category=str(record["category"]),
            amount=int(record["amount"]),
            day=int(record["day"]),
            memo=str(record.get("memo") or ""),
            tags=tuple(record.get("tags") or ()),
            created_at=str(record.get("created_at") or ""),
        )


@dataclass(frozen=True)
class SearchFilter:
    """검색 조건. 모든 조건은 AND 로 결합한다. None 인 조건은 무시한다."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    category: Optional[str] = None
    type: Optional[TxType] = None
    query: Optional[str] = None        # 메모 부분 일치 (대소문자 무시)
    tag: Optional[str] = None          # 태그 정확히 일치

    def matches(self, tx: Transaction) -> bool:
        if self.date_from and tx.date < self.date_from:
            return False
        if self.date_to and tx.date > self.date_to:
            return False
        if self.category and tx.category != self.category:
            return False
        if self.type and tx.type is not self.type:
            return False
        if self.query and self.query.casefold() not in tx.memo.casefold():
            return False
        if self.tag and self.tag not in tx.tags:
            return False
        return True
