"""Run unittest cases and the existing plain test functions in every test_*.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
        for name, value in sorted(vars(module).items()):
            if name.startswith("test_") and callable(value):
                case = unittest.FunctionTestCase(value, description=f"{path.stem}.{name}")
                suite.addTest(case)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
