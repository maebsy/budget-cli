"""공통 관심사(cross-cutting concerns) 데코레이터.

명령 핸들러는 "기능"만 구현하고, 모든 명령에 똑같이 필요한 일은 데코레이터가 감싸서 처리한다.

==================  ==========================================================
데코레이터            하는 일
==================  ==========================================================
``@handle_errors``  예외 → "[오류] 원인 / [힌트] 해결 방법" 출력 + 종료 코드 반환.
                    스택트레이스는 숨긴다(--debug 일 때만 출력).
``@log_command``    명령 이름·인자·종료 코드·소요 시간을 data/app.log 에 JSON 한 줄로 기록
``@timed``          실행 시간 측정. --verbose 일 때 화면에도 출력
==================  ==========================================================

적용 순서(바깥 → 안쪽): ``handle_errors`` → ``log_command`` → ``timed`` → 핸들러.
에러 처리가 가장 바깥이라 로그 기록 중 생긴 문제까지 사용자 메시지로 바뀌고,
로그는 에러로 끝난 명령도 종료 코드와 함께 남긴다.

실패했을 때의 정책 (데코레이터 자신이 문제를 만나도 명령 결과를 망치지 않는다):

* ``handle_errors``  AppError → 그 예외의 종료 코드(2~5) · Ctrl+C → 130 · 그 밖의 예외 → 1.
  스택트레이스는 --debug 일 때만 보여 주고, 평소에는 --debug 로 다시 실행하라는 힌트만 출력한다.
* ``log_command``    로그 파일 쓰기가 실패해도(권한 · 디스크 부족) 조용히 무시한다. 로그는 보조 기능이라
  명령 결과와 종료 코드를 바꾸지 않는다. 데이터 폴더를 열기 전에 실패한 명령은 기록하지 않는다.
* ``timed``          예외가 나도 finally 에서 시간을 기록하고, 예외는 그대로 바깥 데코레이터로 넘긴다.

핸들러 시그니처: ``handler(ctx: CommandContext) -> int`` (종료 코드)
"""

import functools
import json
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, Optional, TextIO

from .errors import EXIT_ERROR, EXIT_INTERRUPTED, EXIT_OK, AppError

Handler = Callable[["CommandContext"], int]

_SENSITIVE_KEYS = {"func", "handler"}


class CommandContext:
    """핸들러에 전달되는 실행 문맥: 파싱된 인자, 입출력 스트림, 공용 상태."""

    def __init__(self, args: Any, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr,
                 stdin: TextIO = sys.stdin) -> None:
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.stdin = stdin
        self.elapsed_ms: Optional[float] = None
        self.app: Any = None  # services.App (명령 실행 시 생성)

    @property
    def command(self) -> str:
        parts = [getattr(self.args, "command", "") or "", getattr(self.args, "action", "") or ""]
        return " ".join(p for p in parts if p)

    def out(self, text: str = "") -> None:
        print(text, file=self.stdout)

    def err(self, text: str) -> None:
        print(text, file=self.stderr)


def handle_errors(func: Handler) -> Handler:
    """예외를 사용자 메시지와 종료 코드로 바꾼다."""

    @functools.wraps(func)
    def wrapper(ctx: CommandContext) -> int:
        try:
            return func(ctx)
        except AppError as exc:
            label = "[취소]" if exc.exit_code == EXIT_INTERRUPTED else "[오류]"
            ctx.err("{} {}".format(label, exc.message))
            if exc.hint:
                ctx.err("[힌트] {}".format(exc.hint))
            return exc.exit_code
        except KeyboardInterrupt:
            ctx.err("[취소] 사용자가 중단했습니다.")
            return EXIT_INTERRUPTED
        except Exception as exc:  # 예상하지 못한 버그도 스택트레이스 대신 안내 메시지로
            ctx.err("[오류] 예기치 못한 문제가 발생했습니다: {}: {}".format(type(exc).__name__, exc))
            if getattr(ctx.args, "debug", False):
                ctx.err(traceback.format_exc().rstrip())
            else:
                ctx.err("[힌트] --debug 옵션을 붙여 다시 실행하면 상세 정보를 볼 수 있습니다.")
            return EXIT_ERROR

    return wrapper


def timed(func: Handler) -> Handler:
    """핸들러 실행 시간을 ``ctx.elapsed_ms`` 에 기록하고, --verbose 면 출력한다."""

    @functools.wraps(func)
    def wrapper(ctx: CommandContext) -> int:
        start = time.perf_counter()
        try:
            return func(ctx)
        finally:
            ctx.elapsed_ms = (time.perf_counter() - start) * 1000
            if getattr(ctx.args, "verbose", False):
                ctx.err("[시간] {} {:.1f}ms".format(ctx.command, ctx.elapsed_ms))

    return wrapper


def _loggable_args(args: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in vars(args).items():
        if key in _SENSITIVE_KEYS or value is None or value is False:
            continue
        result[key] = value if isinstance(value, (int, float, str, bool)) else str(value)
    return result


def log_command(func: Handler) -> Handler:
    """명령 실행 결과를 ``<data-dir>/app.log`` 에 JSON Lines 로 남긴다.

    로그 기록 실패(권한 등)는 본 기능을 방해하지 않도록 조용히 무시한다.
    """

    @functools.wraps(func)
    def wrapper(ctx: CommandContext) -> int:
        code = EXIT_ERROR
        error: Optional[str] = None
        try:
            code = func(ctx)
            return code
        except AppError as exc:
            code, error = exc.exit_code, exc.message
            raise
        except BaseException as exc:
            code, error = (EXIT_INTERRUPTED if isinstance(exc, KeyboardInterrupt) else EXIT_ERROR), type(exc).__name__
            raise
        finally:
            app = ctx.app
            if app is not None:
                entry = {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "command": ctx.command,
                    "args": _loggable_args(ctx.args),
                    "exit_code": code,
                    "elapsed_ms": round(ctx.elapsed_ms, 2) if ctx.elapsed_ms is not None else None,
                }
                if error:
                    entry["error"] = error
                try:
                    with app.paths.log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except OSError:
                    pass

    return wrapper


def command(func: Handler) -> Handler:
    """세 데코레이터를 정해진 순서로 한 번에 적용하는 단축 데코레이터."""
    return handle_errors(log_command(timed(func)))


__all__ = ["CommandContext", "command", "handle_errors", "log_command", "timed", "EXIT_OK"]
