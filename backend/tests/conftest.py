import os
import shutil
from pathlib import Path

import pytest

from strata.indexer.repo_index import is_indexable

EFFIGOV = Path(os.environ.get("STRATA_TEST_REPO", Path.home() / "Documents/effigov"))


@pytest.fixture
def effigov_copy(tmp_path) -> Path:
    """A private copy of the test repo's indexable .py files: tests never touch the original.

    Only .py files are copied; build output like .next or node_modules would cost hundreds of MB per test.
    """
    if not EFFIGOV.is_dir():
        pytest.skip(f"test repo not found: {EFFIGOV}")
    dst = tmp_path / "effigov"
    for path in EFFIGOV.rglob("*.py"):
        rel = path.relative_to(EFFIGOV).as_posix()
        if is_indexable(rel) and path.is_file():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return dst

# tests/fixtures holds sample repos (including their own test files) that are data, not tests.
collect_ignore_glob = ["fixtures/*"]
