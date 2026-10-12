"""구조·품질 요구사항 자동 검증.

* 표준 라이브러리만 사용 (pip install 불필요)
* 3개 이상 모듈로 분리, 계층 의존 방향 준수 (아래 계층이 위 계층을 import 하지 않음)
* 데이터 모델은 dataclass, 클래스 2개 이상
* 데코레이터가 실제 명령 핸들러에 적용됨
* 공개 함수·클래스에 docstring 또는 주석
"""

import ast
import dataclasses
import inspect
import sys
import unittest
from pathlib import Path

import budget_app
from budget_app import cli, models

PACKAGE = Path(budget_app.__file__).parent
MODULES = sorted(p for p in PACKAGE.glob("*.py"))

# 계층: 숫자가 작을수록 아래. 아래 계층은 위 계층을 import 할 수 없다.
LAYERS = {"errors": 0, "models": 1, "validators": 2, "storage": 3, "formatting": 3, "prompts": 3,
          "services": 4, "decorators": 4, "cli": 5, "__main__": 6, "__init__": 0}

STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "argparse", "ast", "calendar", "csv", "dataclasses", "datetime", "enum", "functools", "heapq", "json",
    "os", "pathlib", "re", "sys", "tempfile", "time", "traceback", "typing", "unicodedata", "zipfile"}


def imports_of(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield 0, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.level, node.module or ""


class StructureTest(unittest.TestCase):
    def test_at_least_three_modules(self):
        self.assertGreaterEqual(len([m for m in MODULES if not m.name.startswith("__")]), 3)

    def test_only_standard_library(self):
        for path in MODULES:
            for level, module in imports_of(path):
                if level:  # 패키지 내부 상대 import
                    continue
                with self.subTest(file=path.name, module=module):
                    self.assertIn(module.split(".")[0], STDLIB)

    def test_layer_dependency_direction(self):
        for path in MODULES:
            own = LAYERS[path.stem]
            for level, module in imports_of(path):
                if level and module:
                    target = module.split(".")[0]
                    with self.subTest(file=path.name, imports=target):
                        self.assertLessEqual(LAYERS[target], own, "{} -> {}".format(path.stem, target))

    def test_models_are_dataclasses(self):
        for cls in (models.Transaction, models.Budget, models.Category, models.RecurringRule):
            self.assertTrue(dataclasses.is_dataclass(cls), cls)
        fields = {f.name for f in dataclasses.fields(models.Transaction)}
        self.assertTrue({"id", "type", "date", "amount", "category", "memo", "tags"} <= fields)

    def test_every_command_handler_is_decorated(self):
        handlers = [obj for name, obj in vars(cli).items() if name.startswith("cmd_") and callable(obj)]
        self.assertGreaterEqual(len(handlers), 10)
        for handler in handlers:
            with self.subTest(handler=handler.__name__):
                self.assertTrue(hasattr(handler, "__wrapped__"), "@command 데코레이터가 없습니다")

    def test_public_api_has_type_hints(self):
        from budget_app import services, storage, validators
        for module in (services, storage, validators):
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if func.__module__ != module.__name__ or name.startswith("_"):
                    continue
                with self.subTest(func=name):
                    self.assertIn("return", func.__annotations__)

    def test_docstrings(self):
        for path in MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(module=path.name):
                self.assertIsNotNone(ast.get_docstring(tree))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    with self.subTest(cls=node.name):
                        self.assertIsNotNone(ast.get_docstring(node), "{}.{}".format(path.name, node.name))


if __name__ == "__main__":
    unittest.main()
