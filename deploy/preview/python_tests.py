"""Fixed pytest recipe inside the disposable container."""

import sys
import pytest

sys.path.insert(0, "/work/project")
raise SystemExit(
    pytest.main([
        "-q",
        "-p",
        "no:cacheprovider",
        "--override-ini=addopts=",
        "--import-mode=importlib",
        "/work/project",
    ])
)
