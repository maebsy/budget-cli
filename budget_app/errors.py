"""사용자에게 보여줄 에러와 종료 코드.

모든 에러는 "원인(message) + 해결 힌트(hint)" 를 가진다. CLI 는 스택트레이스 대신 이 두 줄을 출력하고
에러 종류별 종료 코드로 끝난다. 다른 프로그램(쉘 스크립트, cron)은 종료 코드로 성공/실패를 구분할 수 있다.

=====  ==================  =========================================
코드    상수                 의미
=====  ==================  =========================================
0      EXIT_OK             정상 종료
1      EXIT_ERROR          예기치 못한 오류 (버그 가능성)
2      EXIT_USAGE          잘못된 입력·옵션 (사용자가 고칠 수 있음)
3      EXIT_NOT_FOUND      없는 거래 id, 없는 카테고리·파일
4      EXIT_CONFLICT       사용 중인 카테고리 삭제, 중복 등록 등 상태 충돌
5      EXIT_DATA           저장 파일 손상·읽기/쓰기 실패
130    EXIT_INTERRUPTED    Ctrl+C / 입력 취소 (쉘 관례: 128 + SIGINT(2))
=====  ==================  =========================================
"""

from typing import Optional

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_DATA = 5
EXIT_INTERRUPTED = 130


class AppError(Exception):
    """사용자에게 보여줄 에러의 기반 클래스."""

    exit_code = EXIT_ERROR

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ValidationError(AppError):
    """입력 형식 오류 (날짜, 금액, 타입, 옵션 조합 등)."""

    exit_code = EXIT_USAGE


class NotFoundError(AppError):
    """대상이 존재하지 않음 (거래 id, 카테고리, 파일)."""

    exit_code = EXIT_NOT_FOUND


class ConflictError(AppError):
    """현재 상태와 충돌하는 요청 (사용 중인 카테고리 삭제, 중복 카테고리 등)."""

    exit_code = EXIT_CONFLICT


class StorageError(AppError):
    """저장 파일 읽기/쓰기 실패 또는 손상."""

    exit_code = EXIT_DATA


class Cancelled(AppError):
    """사용자가 입력을 취소함 (Ctrl+C, Ctrl+D)."""

    exit_code = EXIT_INTERRUPTED
