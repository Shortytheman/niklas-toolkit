import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GODOT_SCRIPTS = ROOT / "packs" / "godot" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(GODOT_SCRIPTS))


def godot_available() -> bool:
    return bool(os.environ.get("GODOT_BIN") or shutil.which("godot") or shutil.which("godot4"))


needs_godot = pytest.mark.skipif(not godot_available(), reason="set GODOT_BIN to run tests that start Godot")


@pytest.fixture
def project_copy(tmp_path):
    """A fresh copy of a fixture project, so tests never write into tests/fixtures."""
    def make(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(FIXTURES / name, dst, ignore=shutil.ignore_patterns(".godot"))
        return dst
    return make
