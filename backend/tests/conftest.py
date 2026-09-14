import os
import shutil
from pathlib import Path

import pytest

EFFIGOV = Path(os.environ.get("STRATA_TEST_REPO", Path.home() / "Documents/effigov"))


@pytest.fixture
def effigov_copy(tmp_path) -> Path:
    """A private copy of the real test repo: tests never touch the original."""
    if not EFFIGOV.is_dir():
        pytest.skip(f"test repo not found: {EFFIGOV}")
    dst = tmp_path / "effigov"
    shutil.copytree(
        EFFIGOV,
        dst,
        ignore=shutil.ignore_patterns(".git", "node_modules", ".env*", "venv", ".venv", "__pycache__"),
    )
    return dst
