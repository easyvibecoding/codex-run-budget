#!/usr/bin/env python3
"""Install through Codex while retaining versioned hooks used by older tasks.

Run with other tasks idle: Codex may briefly remove caches during installation.
No config, trust state, budget state, or hook policy is changed by this helper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

MAX_RUNTIME_BYTES = 1024 * 1024

# macOS exposes these stable aliases on a number of installations.  They are
# not user-controlled indirections and are used by TemporaryDirectory on the
# test runner, so rejecting every ancestor symlink would reject valid paths.
_SYSTEM_ALIASES = {
    Path("/var"): Path("/private/var"),
    Path("/tmp"): Path("/private/tmp"),
    Path("/etc"): Path("/private/etc"),
}


def _lexists(path: Path) -> bool:
    """Return whether a path exists, including a dangling symlink."""

    return os.path.lexists(os.fspath(path))


def _is_system_alias(path: Path) -> bool:
    expected = _SYSTEM_ALIASES.get(path)
    if expected is None or not path.is_symlink():
        return False
    try:
        return path.resolve(strict=True) == expected
    except OSError:
        return False


def _absolute(path: Path) -> Path:
    """Make a lexical absolute path without resolving symlinks."""

    return Path(os.path.abspath(os.fspath(path)))


def _validate_path(path: Path, label: str, *, reject_final: bool = True) -> Path:
    """Reject user-controlled symlink components before any write.

    ``Path.is_symlink`` only checks the final component.  Walk existing
    components lexically so a link such as ``root/link/cache`` cannot redirect
    the updater into an unrelated tree.  The known macOS aliases above are
    explicitly allowed.
    """

    path = _absolute(Path(path))
    parts = path.parts
    prefixes = []
    current = Path(parts[0])
    prefixes.append(current)
    for part in parts[1:]:
        current /= part
        prefixes.append(current)
    final_index = len(prefixes) - 1
    for index, component in enumerate(prefixes):
        if not component.is_symlink():
            continue
        if index == final_index and not reject_final:
            continue
        if index != final_index and _is_system_alias(component):
            continue
        raise ValueError(f"{label} must not contain a symlink: {component}")
    return path


def _read_regular(path: Path, *, limit: int | None = None) -> bytes:
    """Read a regular file without following a symlink."""

    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(os.fspath(path), flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"expected a regular file: {path}")
        if limit is not None and info.st_size > limit:
            raise ValueError(f"file exceeds limit: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            blob = stream.read(None if limit is None else limit + 1)
        if limit is not None and len(blob) > limit:
            raise ValueError(f"file grew beyond limit: {path}")
        return blob
    except OSError as exc:
        raise ValueError(f"unable to read regular file: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _tree_identity(root: Path) -> str:
    """Hash source content while ignoring generated ``__pycache__`` trees."""

    digest = hashlib.sha256()

    def visit(directory: Path, relative: Path) -> None:
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda entry: entry.name)
        except OSError as exc:
            raise ValueError(f"unable to inspect plugin version: {directory}") from exc
        for entry in entries:
            entry_relative = relative / entry.name
            if entry.is_symlink():
                raise ValueError(f"version cache contains a symlink: {entry.path}")
            if "__pycache__" in entry_relative.parts:
                continue
            if entry.is_dir(follow_symlinks=False):
                digest.update(b"D\0" + entry_relative.as_posix().encode() + b"\0")
                visit(Path(entry.path), entry_relative)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError(f"unexpected non-file cache entry: {entry.path}")
            digest.update(b"F\0" + entry_relative.as_posix().encode() + b"\0")
            descriptor = None
            try:
                descriptor = os.open(
                    entry.path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                )
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"unexpected non-file cache entry: {entry.path}")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = None
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
            except OSError as exc:
                raise ValueError(f"unable to read plugin version: {entry.path}") from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)

    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"plugin version must be a real directory: {root}")
    visit(root, Path())
    return digest.hexdigest()


def _add_error_note(error: BaseException, note: str) -> None:
    """Annotate an error where Python provides PEP 678 (3.11+)."""

    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)


def _quarantine(path: Path, backup_root: Path, *, label: str) -> Path:
    """Move an exact substituted path without dereferencing it."""

    backup_root = _validate_path(backup_root, "retention directory")
    if backup_root.is_symlink() or not backup_root.is_dir():
        raise ValueError("retention directory must be a real directory")
    quarantine = Path(tempfile.mkdtemp(prefix="quarantine-", dir=backup_root))
    destination = quarantine / (label or path.name)
    try:
        # os.replace renames the directory entry itself.  In particular, a
        # symlink at ``path`` is moved as a symlink and its outside target is
        # never opened or removed.
        os.replace(os.fspath(path), os.fspath(destination))
    except BaseException:
        try:
            quarantine.rmdir()
        except OSError:
            pass
        raise
    return destination


def _restore_version(cache: Path, backup_version: Path, version_name: str) -> None:
    """Atomically install a copy of one validated backup into ``cache``."""

    if cache.is_symlink() or not cache.is_dir():
        raise ValueError("plugin cache is not a real directory during restore")
    staging = Path(tempfile.mkdtemp(prefix="restore-", dir=cache))
    staged_version = staging / version_name
    try:
        shutil.copytree(backup_version, staged_version)
        os.replace(os.fspath(staged_version), os.fspath(cache / version_name))
    finally:
        if staged_version.exists() or staged_version.is_symlink():
            shutil.rmtree(staged_version)
        try:
            staging.rmdir()
        except OSError:
            pass


def _ensure_cache_directory(cache: Path, backup_root: Path) -> bool:
    """Make cache a real directory, quarantining a substituted root."""

    _validate_path(cache.parent, "plugin cache parent")
    if cache.is_symlink() or (_lexists(cache) and not cache.is_dir()):
        _quarantine(cache, backup_root, label="cache")
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        return True
    if not _lexists(cache):
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    return False


def _recover_versions(
    cache: Path,
    versions: list[Path],
    identities: dict[str, str],
    backup: Path,
    backup_root: Path,
) -> list[str]:
    """Restore deleted/changed versions and report integrity violations."""

    cache_replaced = _ensure_cache_directory(cache, backup_root)
    violations = ["cache"] if cache_replaced else []
    for version in versions:
        target = cache / version.name
        substituted = False
        if _lexists(target):
            if target.is_symlink() or not target.is_dir():
                substituted = True
            else:
                try:
                    substituted = _tree_identity(target) != identities[version.name]
                except ValueError:
                    substituted = True
        if substituted:
            _quarantine(target, backup_root, label=version.name)
            violations.append(version.name)
        if not _lexists(target):
            _restore_version(cache, backup / version.name, version.name)
    return violations


def preserve_install(cache: Path, install, *, backup_root: Path | None = None) -> int:
    """Keep a persistent recovery copy before calling the installer.

    Missing versions are restored even if install fails. Existing versions are
    never overwritten. Retention backups deliberately survive this command.
    """
    cache = _validate_path(cache, "plugin cache")
    if cache.is_symlink():
        raise ValueError("plugin cache must not be a symlink")
    if _lexists(cache) and not cache.is_dir():
        raise ValueError("plugin cache must be a directory")
    versions = sorted(cache.iterdir(), key=lambda path: path.name) if cache.exists() else []
    identities = {}
    for version in versions:
        if version.is_symlink() or not version.is_dir():
            raise ValueError("unexpected entry in plugin version cache")
        identity = _tree_identity(version)
        manifest_path = version / ".codex-plugin/plugin.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("plugin version manifest must be a regular file")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("name") != "codex-run-budget":
            raise ValueError("unexpected plugin in version cache")
        identities[version.name] = identity
    backup_root = _absolute(backup_root or cache.parent / "run-budget-retained")
    _validate_path(backup_root, "retention directory")
    if backup_root == cache or cache in backup_root.parents:
        raise ValueError("retention directory must be outside plugin cache")
    if backup_root.is_symlink():
        raise ValueError("retention directory must not be a symlink")
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="upgrade-", dir=backup_root))
    for version in versions:
        shutil.copytree(version, backup / version.name)
    print(f"Recovery backup: {backup}", flush=True)
    install_result = None
    install_error = None
    try:
        try:
            install_result = install()
        except BaseException as exc:
            install_error = exc
    finally:
        recovery_error = None
        violations = []
        try:
            violations = _recover_versions(cache, versions, identities, backup, backup_root)
            for version in versions:
                target = cache / version.name
                if _lexists(target) and not target.is_symlink() and target.is_dir():
                    # A missing old version is restored above.  Existing
                    # versions are only announced after their identity is
                    # verified, so a changed same-version tree is not silently
                    # treated as a successful install.
                    if version.name not in violations:
                        print(f"Retained hook version: {version.name}", flush=True)
        except BaseException as exc:
            recovery_error = exc
        if recovery_error is not None:
            if install_error is not None:
                _add_error_note(recovery_error, f"installer error: {install_error!r}")
            raise recovery_error
        if violations:
            message = "plugin cache changed during install; substituted paths were quarantined"
            integrity_error = ValueError(message + ": " + ", ".join(violations))
            if install_error is not None:
                _add_error_note(integrity_error, f"installer error: {install_error!r}")
            raise integrity_error
        if install_error is not None:
            raise install_error
    return install_result


def prewarm_runtime(plugin: Path, data_root: Path) -> bool:
    """Copy a generated, command-pinned runtime without executing plugin code.

    Legacy versions have no zipapp and still need a one-time task restart.
    No trust setting or ledger is read or written here.
    """
    plugin = _validate_path(plugin, "plugin source")
    archive = _validate_path(
        plugin / "runtime/hook.pyz", "runtime archive", reject_final=False
    )
    # ``exists`` is false for a dangling symlink; inspect the directory entry
    # first so a broken link cannot be mistaken for a legacy version.
    if archive.is_symlink():
        raise ValueError("invalid runtime archive")
    if not _lexists(archive):
        return False
    runtime = _read_regular(archive, limit=MAX_RUNTIME_BYTES)
    digest = hashlib.sha256(runtime).hexdigest()
    bootstrap = _read_regular(_validate_path(plugin / "scripts/bootstrap.py", "bootstrap")).decode(
        "utf-8"
    )
    hooks = json.loads(
        _read_regular(_validate_path(plugin / "hooks/hooks.json", "hook configuration"))
    )["hooks"]
    commands = [
        (event, hook["command"])
        for event, groups in hooks.items()
        for group in groups
        for hook in group["hooks"]
    ]
    if not commands:
        raise ValueError("missing runtime commands")
    for event, command in commands:
        if shlex.split(command) != ["python3", "-I", "-c", bootstrap, event, digest]:
            raise ValueError("runtime and trusted command identities differ")
    data_root = _validate_path(data_root, "runtime data directory")
    directory = _validate_path(data_root / "runtimes", "runtime directory")
    if data_root.is_symlink() or directory.is_symlink():
        raise ValueError("runtime directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / (digest + ".pyz")
    descriptor, temporary = tempfile.mkstemp(prefix="runtime-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(runtime)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    if hashlib.sha256(_read_regular(target, limit=MAX_RUNTIME_BYTES)).hexdigest() != digest:
        raise ValueError("saved runtime verification failed")
    print(f"Prepared durable hook runtime: {digest}", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    parser.add_argument(
        "--retain-only",
        action="store_true",
        help="back up current versions without installing or changing settings",
    )
    args = parser.parse_args()
    codex_home = _validate_path(args.codex_home, "Codex home")
    cache = _validate_path(
        codex_home / "plugins/cache/codex-run-budget/codex-run-budget", "plugin cache"
    )
    data_root = _validate_path(
        Path(os.environ.get("CODEX_RUN_BUDGET_HOME") or codex_home / "run-budget"),
        "runtime data directory",
    )
    # Validate the data path before entering preserve_install.  The installer
    # must not run if the configured retention location would follow a user
    # supplied link.
    _validate_path(data_root / "cache-backups", "retention directory")

    def install() -> int:
        if args.retain_only:
            return 0
        result = subprocess.run(
            ["codex", "plugin", "add", "codex-run-budget@codex-run-budget", "--json"],
            env={**os.environ, "CODEX_HOME": str(codex_home)},
            check=False,
        ).returncode
        if result == 0:
            if cache.is_symlink() or (_lexists(cache) and not cache.is_dir()):
                raise ValueError("plugin cache is not a real directory after install")
            if not _lexists(cache):
                return result
            for version in sorted(cache.iterdir()):
                if version.is_symlink() or not version.is_dir():
                    raise ValueError("unexpected entry in plugin version cache after install")
                prewarm_runtime(version, data_root)
        return result

    result = preserve_install(
        cache,
        install,
        backup_root=data_root / "cache-backups",
    )
    if result == 0 and not args.retain_only:
        print(
            "Installation complete; hook trust was not changed. Review changed "
            "codex-run-budget hooks in Codex CLI /hooks, then start a new Task. "
            "Installed/enabled plugins may still have modified hooks that are skipped; "
            "restarting the app does not grant trust.",
            flush=True,
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
