"""테스트 공용 도구: 임시 데이터 폴더와 CLI 실행 헬퍼."""

import io
import shutil
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from budget_app.cli import main


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def lines(self) -> List[str]:
        return self.out.splitlines()


class CliTestCase(unittest.TestCase):
    """테스트마다 새 임시 데이터 폴더를 만들고 끝나면 지운다."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="budget-test-"))
        self.data_dir = self.tmp / "data"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv: str, stdin: str = "") -> Result:
        out, err = io.StringIO(), io.StringIO()
        code = main(["--data-dir", str(self.data_dir), *argv], stdin=io.StringIO(stdin), stdout=out, stderr=err)
        return Result(code, out.getvalue(), err.getvalue())

    def add(self, when: str, tx_type: str, category: str, amount: str, memo: str = "", tags: str = "") -> str:
        """대화형 add 를 파이프 입력으로 실행하고 생성된 id 를 반환한다."""
        result = self.run_cli("add", stdin="\n".join([when, tx_type, category, amount, memo, tags]) + "\n")
        self.assertEqual(result.code, 0, result.err)
        return result.out.strip().splitlines()[-1].split("id=")[1]

    def write_file(self, name: str, text: str, encoding: str = "utf-8") -> Path:
        path = self.tmp / name
        path.write_text(text, encoding=encoding)
        return path

    def assertNoTraceback(self, result: Result) -> None:
        self.assertNotIn("Traceback", result.err + result.out)
