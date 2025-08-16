# Ensure the repository root is on sys.path so `task_printer` can be imported in tests.

import sys
from pathlib import Path


def _ensure_repo_root_on_syspath() -> None:
    # This file lives at: <repo_root>/tests/conftest.py
    # We want to add <repo_root> to sys.path (if not already present).
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


_ensure_repo_root_on_syspath()
