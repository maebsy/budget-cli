"""데코레이터 단위 테스트: 공통 관심사가 핸들러와 분리되어 동작하는지 확인한다."""

import io
import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from budget_app.decorators import CommandContext, command, handle_errors, log_command, timed
from budget_app.errors import EXIT_NOT_FOUND, EXIT_OK, NotFoundError
from budget_app.services import App


def make_ctx(**kwargs) -> CommandContext:
    args = Namespace(command="demo", action=None, verbose=False, debug=False, **kwargs)
    return CommandContext(args, stdout=io.StringIO(), stderr=io.StringIO(), stdin=io.StringIO())


class HandleErrorsTest(unittest.TestCase):
    def test_app_error_becomes_message_and_exit_code(self):
        @handle_errors
        def handler(ctx):
            raise NotFoundError("없는 데이터", "id 를 확인하세요")

        ctx = make_ctx()
        self.assertEqual(handler(ctx), EXIT_NOT_FOUND)
        self.assertEqual(ctx.stderr.getvalue(), "[오류] 없는 데이터\n[힌트] id 를 확인하세요\n")

    def test_keyboard_interrupt(self):
        @handle_errors
        def handler(ctx):
            raise KeyboardInterrupt

        ctx = make_ctx()
        self.assertEqual(handler(ctx), 130)
        self.assertIn("[취소]", ctx.stderr.getvalue())

    def test_wraps_preserves_metadata(self):
        @command
        def cmd_sample(ctx):
            """샘플 핸들러."""
            return EXIT_OK

        self.assertEqual(cmd_sample.__name__, "cmd_sample")
        self.assertEqual(cmd_sample.__doc__, "샘플 핸들러.")


class TimedAndLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timed_records_elapsed(self):
        ctx = make_ctx()
        ctx.args.verbose = True
        timed(lambda c: EXIT_OK)(ctx)
        self.assertIsNotNone(ctx.elapsed_ms)
        self.assertIn("[시간]", ctx.stderr.getvalue())

    def test_log_command_writes_json_line_even_on_error(self):
        app = App(str(self.tmp / "data"))

        @command
        def failing(ctx):
            ctx.app = app
            raise NotFoundError("x")

        ctx = make_ctx(limit="3")
        self.assertEqual(failing(ctx), EXIT_NOT_FOUND)
        entry = json.loads(app.paths.log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(entry["exit_code"], EXIT_NOT_FOUND)
        self.assertEqual(entry["args"]["limit"], "3")
        self.assertEqual(entry["error"], "x")


if __name__ == "__main__":
    unittest.main()
