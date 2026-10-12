"""대화형 입력 도우미.

``ask()`` 는 검증 함수를 통과할 때까지 같은 질문을 반복한다. 잘못 입력하면
"[오류] 원인 / [힌트] 예시"를 보여주고 다시 묻는다(재입력 요구).
Ctrl+C / Ctrl+D(EOF) 는 ``Cancelled`` 로 바꿔 종료 코드 130 으로 끝낸다.
"""

from typing import Callable, Optional, TextIO, TypeVar

from .errors import Cancelled, NotFoundError, ValidationError

T = TypeVar("T")

MAX_ATTEMPTS = 5  # 파이프 입력이 계속 틀리면 무한 반복하지 않도록


class Prompter:
    """검증 함수를 통과할 때까지 질문을 반복하는 대화형 입력기 (입출력 스트림 주입 가능)."""
    def __init__(self, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def _readline(self, label: str) -> str:
        self.stdout.write(label)
        self.stdout.flush()
        try:
            line = self.stdin.readline()
        except KeyboardInterrupt:
            self.stdout.write("\n")
            raise Cancelled("입력이 취소되었습니다.")
        if line == "":  # EOF (Ctrl+D / Ctrl+Z, 파이프 입력 끝)
            self.stdout.write("\n")
            raise Cancelled("입력이 취소되었습니다.")
        if not self.stdin.isatty():
            self.stdout.write(line if line.endswith("\n") else line + "\n")  # 파이프 입력도 화면에 남긴다
        return line.rstrip("\r\n")

    def ask(self, label: str, parse: Callable[[str], T], optional: bool = False,
            default: Optional[T] = None, on_error: Optional[Callable[[], None]] = None) -> T:
        """검증을 통과할 때까지 묻는다. ``optional`` 이면 빈 입력 시 ``default`` 반환."""
        for _ in range(MAX_ATTEMPTS):
            raw = self._readline(label)
            if optional and not raw.strip():
                return default  # type: ignore[return-value]
            try:
                return parse(raw)
            except (ValidationError, NotFoundError) as exc:
                print("[오류] {}".format(exc.message), file=self.stderr)
                if exc.hint:
                    print("[힌트] {}".format(exc.hint), file=self.stderr)
                if on_error:
                    on_error()
        raise ValidationError("입력이 {}번 연속 올바르지 않아 중단합니다.".format(MAX_ATTEMPTS), "명령을 다시 실행하세요.")
