from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(TESTS))  # for pdfgen


def need_tools(*names: str) -> pytest.MarkDecorator:
    missing = [n for n in names if shutil.which(n) is None]
    return pytest.mark.skipif(bool(missing), reason=f"missing tools: {', '.join(missing)}")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
