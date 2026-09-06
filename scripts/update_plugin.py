#!/usr/bin/env python3
"""Install through Codex while retaining versioned hooks used by older tasks.

Run with other tasks idle: Codex may briefly remove caches during installation.
No config, trust state, budget state, or hook policy is changed by this helper.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def preserve_install(cache: Path, install) -> int:
    """Keep a persistent recovery copy before calling the installer.

    Missing versions are restored even if install fails. Existing versions are
    never overwritten. Retention backups deliberately survive this command.
    """
    if cache.is_symlink():
        raise ValueError("plugin cache must not be a symlink")
    versions = sorted(cache.iterdir()) if cache.exists() else []
    for version in versions:
        if version.is_symlink() or not version.is_dir():
            raise ValueError("unexpected entry in plugin version cache")
        manifest = json.loads((version / ".codex-plugin/plugin.json").read_text())
        if manifest.get("name") != "codex-run-budget":
            raise ValueError("unexpected plugin in version cache")
        if any(p.is_symlink() for p in version.rglob("*")):
            raise ValueError("version cache contains a symlink")
    backup_root = cache.parent / "run-budget-retained"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="upgrade-", dir=backup_root))
    for version in versions:
        shutil.copytree(version, backup / version.name)
    print(f"Recovery backup: {backup}", flush=True)
    try:
        return install()
    finally:
        for version in versions:
            target = cache / version.name
            if not target.exists():
                # Copy before renaming so readers never see a partially restored tree.
                staging = Path(tempfile.mkdtemp(prefix="restore-", dir=backup_root))
                shutil.copytree(backup / version.name, staging / version.name)
                cache.mkdir(parents=True, exist_ok=True)
                (staging / version.name).rename(target)
                staging.rmdir()
                print(f"Retained hook version: {version.name}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    args = parser.parse_args()
    cache = args.codex_home / "plugins/cache/codex-run-budget/codex-run-budget"
    return preserve_install(
        cache,
        lambda: (
            subprocess.run(
                ["codex", "plugin", "add", "codex-run-budget@codex-run-budget", "--json"],
                env={**os.environ, "CODEX_HOME": str(args.codex_home)},
                check=False,
            ).returncode
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
