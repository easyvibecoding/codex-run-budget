#!/usr/bin/env python3
"""Opt-in local watcher for paired Codex projects."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from codex_run_budget.paired_review import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
