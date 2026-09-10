"""Embedded verbatim in trusted hook commands: no cache file is needed to start.

The SHA-256 argument pins one zipapp. Saved runtimes live with the budget data,
outside Codex's replaceable plugin cache, and are never garbage-collected here.
This adapter makes no governance decision; unavailable code denies admission
with event-specific JSON and never returns exit 2 from a Stop hook.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

MAX_RUNTIME_BYTES = 1024 * 1024


class RuntimeResources:
    def __init__(self, archive, prefix):
        self.archive, self.prefix = archive, prefix

    def open_resource(self, resource):
        return io.BytesIO(self.archive.read(self.prefix + resource))

    def resource_path(self, resource):
        raise FileNotFoundError("runtime resources are held in memory")

    def is_resource(self, name):
        return self.prefix + name in self.archive.namelist()

    def contents(self):
        return iter(
            {
                name[len(self.prefix) :].split("/")[0]
                for name in self.archive.namelist()
                if name.startswith(self.prefix)
            }
        )


class RuntimeLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import only this package from already-verified bytes, never by pathname."""

    def __init__(self, blob):
        self.archive = zipfile.ZipFile(io.BytesIO(blob))

    def member(self, fullname):
        if fullname != "codex_run_budget" and not fullname.startswith("codex_run_budget."):
            return None
        base = fullname.replace(".", "/")
        for name in (base + "/__init__.py", base + ".py"):
            if name in self.archive.namelist():
                return name
        return None

    def find_spec(self, fullname, path=None, target=None):
        name = self.member(fullname)
        if name:
            return importlib.util.spec_from_loader(
                fullname, self, is_package=name.endswith("/__init__.py")
            )
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = self.member(module.__name__)
        module.__file__ = "<run-budget-runtime>/" + name
        exec(compile(self.archive.read(name), module.__file__, "exec"), module.__dict__)

    def get_resource_reader(self, fullname):
        return RuntimeResources(self.archive, fullname.replace(".", "/") + "/")

    def run(self, event):
        sys.meta_path.insert(0, self)
        sys.argv = ["run-budget-runtime", "--event", event]
        exec(
            compile(self.archive.read("__main__.py"), "<run-budget-entry>", "exec"),
            {"__name__": "__main__"},
        )


def verified_bytes(path: Path, expected: str) -> bytes | None:
    descriptor = None
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RUNTIME_BYTES:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            blob = stream.read(MAX_RUNTIME_BYTES + 1)
        if len(blob) <= MAX_RUNTIME_BYTES and hashlib.sha256(blob).hexdigest() == expected:
            return blob
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return None


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    temporary = None
    try:
        if not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("invalid runtime identity")
        root = Path(
            os.environ.get("CODEX_RUN_BUDGET_HOME") or Path.home() / ".codex" / "run-budget"
        ).expanduser()
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("invalid data directory")
        directory = root / "runtimes"
        if directory.is_symlink():
            raise ValueError("invalid runtime directory")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / (expected + ".pyz")
        if verified_bytes(target, expected) is None:
            source_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
            if not source_root:
                raise ValueError("missing source")
            blob = verified_bytes(Path(source_root) / "runtime" / "hook.pyz", expected)
            if blob is None:
                raise ValueError("runtime unavailable")
            descriptor, temporary = tempfile.mkstemp(prefix="runtime-", dir=directory)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        runtime = verified_bytes(target, expected)
        if runtime is None:
            raise ValueError("runtime integrity failed")
        RuntimeLoader(runtime).run(event)
    except Exception:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        message = (
            "Run Budget runtime is unavailable or failed integrity validation. "
            "Restore the installed runtime before retrying; budget state is unchanged."
        )
        result = {"systemMessage": message}
        if event == "PreToolUse":
            result["hookSpecificOutput"] = {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        elif event == "UserPromptSubmit":
            result.update(decision="block", reason=message)
        else:
            result.update({"continue": False, "stopReason": message})
        print(json.dumps(result))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
