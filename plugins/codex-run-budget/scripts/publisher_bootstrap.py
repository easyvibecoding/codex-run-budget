"""Stable publisher-trust entry point. Embedded source + public key require trust.

Only RSA-3072/SHA-256 signed runtimes for this plugin and this exact bootstrap
contract can execute. Updating this file or POLICY changes the native hook hash.
No native trust record, plugin cache, credential, or model API is modified here.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import importlib.abc
import importlib.util
import io
import json
import os
import re
import signal
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

MAX_RUNTIME = 8 * 1024 * 1024
MAX_MANIFEST = 16384
PLUGINS = {"codex-run-budget": "run-budget", "codex-usage-reports": "usage-reports"}
FIELDS = {"schema", "plugin", "channel", "version", "sequence", "bootstrap_sha256",
          "runtime_sha256", "runtime_size", "signature"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def entry(source, policy):
    return ("import base64,json\ns=base64.b64decode(" + repr(base64.b64encode(source).decode())
            + ")\np=json.loads(" + repr(canonical(policy).decode()) + ")\n"
            "exec(compile(s,'<publisher-bootstrap>','exec'),"
            "{'__name__':'__main__','SOURCE':s,'POLICY':p})\n")


def contract(source, policy):
    return hashlib.sha256(source + b"\0" + canonical(policy)).hexdigest()


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate metadata key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def verified(manifest, policy, source, *, compatible=True):
    """RFC 8017 sections 8.2.2/9.2; exact EMSA encoding, no permissive ASN.1."""
    if not isinstance(manifest, dict) or set(manifest) != FIELDS:
        raise ValueError("invalid release metadata")
    if (manifest["schema"] != 1 or manifest["plugin"] != policy["plugin"]
            or manifest["channel"] != "stable"
            or type(manifest["sequence"]) is not int or not 0 < manifest["sequence"] < 2**63
            or type(manifest["runtime_size"]) is not int
            or not 0 < manifest["runtime_size"] <= MAX_RUNTIME
            or not isinstance(manifest["version"], str)
            or not re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}(?:\+[\w.-]{1,70})?",
                                manifest["version"])):
        raise ValueError("invalid release identity")
    for key in ("runtime_sha256", "bootstrap_sha256"):
        if not isinstance(manifest[key], str) or not re.fullmatch("[0-9a-f]{64}", manifest[key]):
            raise ValueError("invalid release digest")
    modulus = int(policy["rsa_n"], 16)
    if modulus.bit_length() != 3072 or modulus % 2 != 1 or policy["rsa_e"] != 65537:
        raise ValueError("unsupported publisher key")
    signature = base64.b64decode(manifest["signature"], validate=True)
    number = int.from_bytes(signature, "big")
    if len(signature) != 384 or number >= modulus:
        raise ValueError("invalid signature length")
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    digest_info += hashlib.sha256(canonical(unsigned)).digest()
    expected = b"\x00\x01" + b"\xff" * (384 - len(digest_info) - 3) + b"\x00" + digest_info
    actual = pow(number, 65537, modulus).to_bytes(384, "big")
    if not hmac.compare_digest(actual, expected):
        raise ValueError("invalid publisher signature")
    if compatible and manifest["bootstrap_sha256"] != contract(source, policy):
        raise ValueError("plugin update requires a new bootstrap")
    return manifest


def safe(path):
    path = Path(path).expanduser().absolute()
    aliases = {Path("/var"): Path("/private/var"), Path("/tmp"): Path("/private/tmp"),
               Path("/etc"): Path("/private/etc")}
    for part in (path, *path.parents):
        if part.is_symlink() and (part not in aliases or part.resolve() != aliases[part]):
            raise ValueError("symlink path")
    return path


def read(path, limit):
    descriptor = os.open(safe(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("invalid file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("oversized file")
    return raw


def runtime_bytes(path, manifest):
    raw = read(path, MAX_RUNTIME)
    if (len(raw) != manifest["runtime_size"]
            or hashlib.sha256(raw).hexdigest() != manifest["runtime_sha256"]):
        raise ValueError("runtime integrity failure")
    return raw


def fetch(url, limit):
    context = ssl.create_default_context()
    if (sys.platform == "darwin" and not context.cert_store_stats()["x509_ca"]
            and not os.environ.get("SSL_CERT_FILE") and not os.environ.get("SSL_CERT_DIR")
            and Path("/etc/ssl/cert.pem").is_file()):
        context.load_verify_locations(cafile="/etc/ssl/cert.pem")
    request = urllib.request.Request(url, headers={"User-Agent": "Codex-Signed-Runtime/1"})
    with urllib.request.urlopen(request, timeout=4, context=context) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("oversized download")
    return raw


class Publisher:
    """The update, activation, rollback and per-Task version seam."""

    def __init__(self, root, policy, source):
        if policy["plugin"] not in PLUGINS:
            raise ValueError("unknown plugin")
        self.root, self.policy, self.source = safe(root), policy, source
        self.namespace = contract(source, policy) + ":"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = safe(self.root / "runtimes")
        self.directory.mkdir(exist_ok=True, mode=0o700)
        path = safe(self.root / "publisher-updates.sqlite3")
        for suffix in ("-wal", "-shm", "-journal"):
            safe(Path(str(path) + suffix))
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path, timeout=1.5)
        try:
            self._enable_wal()
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(
                "CREATE TABLE IF NOT EXISTS releases("
                "digest TEXT PRIMARY KEY, manifest TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS tasks("
                "task TEXT PRIMARY KEY, digest TEXT NOT NULL, at REAL);"
            )
        except BaseException:
            self.db.close()
            raise

    def _enable_wal(self):
        # Rollback-journal commits can block even immutable pinned reads. WAL
        # keeps those readers independent of cold retention and fresh-pin writes.
        # The first journal transition itself can return BUSY without waiting.
        deadline = time.monotonic() + 1.5
        delay = 0.01
        while True:
            try:
                if self.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                    return
                if self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise ValueError("publisher requires WAL journal mode")
                return
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", None)
                busy = (code & 0xFF == 5 if code is not None
                        else str(error) == "database is locked")
                remaining = deadline - time.monotonic()
                if not busy or remaining <= 0:
                    raise
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, 0.08)

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?",
                              (self.namespace + key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                        (self.namespace + key, json.dumps(value)))

    def load(self, digest):
        row = self.db.execute("SELECT manifest FROM releases WHERE digest=?",
                              (self.namespace + str(digest),)).fetchone()
        if not row:
            raise ValueError("release unavailable")
        manifest = verified(parse(row[0]), self.policy, self.source)
        if manifest["runtime_sha256"] != digest:
            raise ValueError("release identity mismatch")
        return manifest, runtime_bytes(self.directory / (digest + ".pyz"), manifest)

    def retain(self, manifest, blob):
        manifest = verified(manifest, self.policy, self.source)
        digest = manifest["runtime_sha256"]
        if len(blob) != manifest["runtime_size"] or hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError("runtime integrity failure")
        # Validate the container before activation; code executes only after signature validation.
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = archive.namelist()
            if ("__main__.py" not in names or len(names) != len(set(names))
                    or sum(i.file_size for i in archive.infolist()) > MAX_RUNTIME):
                raise ValueError("invalid runtime archive")
            if archive.testzip() is not None:
                raise ValueError("corrupt runtime archive")
        target = safe(self.directory / (digest + ".pyz"))
        if not target.exists() or read(target, MAX_RUNTIME) != blob:
            fd, temporary = tempfile.mkstemp(prefix="signed-", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(blob)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        key, encoded = self.namespace + digest, canonical(manifest).decode()
        row = self.db.execute("SELECT manifest FROM releases WHERE digest=?", (key,)).fetchone()
        if row and row[0] == encoded:
            return digest
        with self.db:
            # Another cold-start hook may have retained these exact bytes since
            # our read. Do not force a delete/insert and durable commit for it.
            self.db.execute("INSERT INTO releases VALUES (?,?) ON CONFLICT(digest) "
                            "DO UPDATE SET manifest=excluded.manifest "
                            "WHERE releases.manifest != excluded.manifest", (key, encoded))
        return digest

    def activate(self, manifest, blob, *, require_enabled=False):
        digest = self.retain(manifest, blob)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if require_enabled and not self.get("enabled", True):
                return False
            if manifest["sequence"] <= self.get("high_water", 0):
                return False
            previous = self.get("active")
            if previous and previous != digest:
                self.put("previous", previous)
            self.put("active", digest)
            self.put("high_water", manifest["sequence"])
        return True

    def seed(self, plugin_root):
        if not plugin_root:
            return
        try:
            manifest = verified(parse(read(Path(plugin_root) / "runtime/release.json",
                                           MAX_MANIFEST)), self.policy, self.source)
            digest = manifest["runtime_sha256"]
            # Every hook seeds the installed package. Once considered, it must not
            # rewrite releases or contend with Task pins. select() still verifies
            # the selected manifest and exact runtime bytes on every invocation.
            if self.get("active") and manifest["sequence"] <= self.get("high_water", 0):
                return
            try:
                blob = self.load(digest)[1]
            except sqlite3.Error:
                raise
            except Exception:
                blob = runtime_bytes(Path(plugin_root) / "runtime/publisher.pyz", manifest)
            self.activate(manifest, blob)
        except sqlite3.Error:
            raise
        except Exception:
            # Existing verified state survives plugin cache eviction/replacement.
            if not self.get("active"):
                raise

    def select(self, task=None):
        task_hash = (hashlib.sha256((self.namespace + task).encode()).hexdigest()
                     if task else None)
        # Pinned hooks only read. Do not hold any transaction while verifying a
        # signature or reading/hashing the archive, including for a fresh Task.
        for _ in range(4):
            row = (self.db.execute("SELECT digest FROM tasks WHERE task=?", (task_hash,)).fetchone()
                   if task_hash else None)
            if row:
                return (*self.load(row[0]), False)
            active = self.get("active")
            previous = None
            try:
                selected = self.load(active)
            except sqlite3.Error:
                raise
            except Exception:
                previous = self.get("previous")
                selected = self.load(previous)
            if not task_hash and previous is None:
                return (*selected, True)
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                # A peer may have pinned this Task or activated another release
                # during verification. Retry outside the lock using that state.
                if task_hash and self.db.execute(
                        "SELECT 1 FROM tasks WHERE task=?", (task_hash,)).fetchone():
                    continue
                if (self.get("active") != active or
                        (previous is not None and self.get("previous") != previous)):
                    continue
                if previous is not None:
                    self.put("active", previous)
                    self.put("last_result", {"status": "fallback_previous"})
                if task_hash:
                    self.db.execute("INSERT INTO tasks VALUES (?,?,?)",
                                    (task_hash, selected[0]["runtime_sha256"], time.time()))
                    self.db.execute("DELETE FROM tasks WHERE task NOT IN "
                                    "(SELECT task FROM tasks ORDER BY at DESC LIMIT 10000)")
            return (*selected, True)
        raise RuntimeError("runtime selection changed repeatedly; retry")

    def status(self):
        result = {"plugin": self.policy["plugin"], "enabled": self.get("enabled", True),
                  "active": None, "previous": None, "last_check": self.get("last_check"),
                  "last_result": self.get("last_result", {"status": "not_checked"})}
        for key in ("active", "previous"):
            try:
                manifest, _ = self.load(self.get(key))
                result[key] = {k: manifest[k] for k in ("version", "sequence", "runtime_sha256")}
            except Exception:
                pass
        return result

    def update(self, fetcher=fetch, *, automatic=False):
        base = ("https://raw.githubusercontent.com/easyvibecoding/" + self.policy["plugin"]
                + "/main/plugins/" + self.policy["plugin"] + "/runtime/")
        result = {"status": "unavailable"}
        try:
            if automatic and not self.get("enabled", True):
                return {"status": "disabled"}
            manifest = verified(parse(fetcher(base + "release.json", MAX_MANIFEST)),
                                self.policy, self.source, compatible=False)
            if manifest["bootstrap_sha256"] != contract(self.source, self.policy):
                result = {"status": "requires_plugin_update", "version": manifest["version"]}
            elif manifest["sequence"] <= self.get("high_water", 0):
                result = {"status": "current_or_older"}
            else:
                blob = fetcher(base + "publisher.pyz", MAX_RUNTIME)
                changed = self.activate(manifest, blob, require_enabled=automatic)
                result = {"status": "updated" if changed else "current_or_older",
                          "version": manifest["version"]}
        except Exception:
            # No provider error text, URL, path, or unverified metadata is persisted.
            result = {"status": "unavailable_or_rejected"}
        with self.db:
            self.put("last_check", time.time())
            self.put("lease_until", 0)
            self.put("last_result", result)
        return result

    def control(self, action):
        if action == "update":
            return self.update()
        with self.db:
            if action in {"on", "off"}:
                self.put("enabled", action == "on")
            elif action == "rollback":
                self.db.execute("BEGIN IMMEDIATE")
                previous = self.get("previous")
                self.load(previous)
                self.put("active", previous)
                self.put("previous", None)
                self.put("last_result", {"status": "rolled_back"})
            elif action != "status":
                raise ValueError("unknown update action")
        return self.status()

    def schedule(self):
        if (os.environ.get("CODEX_PLUGIN_AUTO_UPDATE") == "0" or os.environ.get(
                self.policy["plugin"].upper().replace("-", "_") + "_AUTO_UPDATE") == "0"):
            return False
        now = time.time()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            interval = (600 if self.get("last_result", {}).get("status") ==
                        "unavailable_or_rejected" else 6 * 3600)
            last = self.get("last_check", 0)
            if (not self.get("enabled", True) or self.get("lease_until", 0) > now
                    or 0 <= now - last < interval):
                return False
            self.put("lease_until", now + 60)
        command = [sys.executable, "-I", "-c", entry(self.source, self.policy),
                   "--worker", str(self.root)]
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            return True
        except Exception:
            with self.db:
                self.put("lease_until", 0)
            return False


class RuntimeLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, blob, package):
        self.archive = zipfile.ZipFile(io.BytesIO(blob))
        self.package = package
        self.runtime_digest = hashlib.sha256(blob).hexdigest()

    def member(self, fullname):
        if fullname != self.package and not fullname.startswith(self.package + "."):
            return None
        base = fullname.replace(".", "/")
        return next((p for p in (base + "/__init__.py", base + ".py")
                     if p in self.archive.namelist()), None)

    def find_spec(self, fullname, path=None, target=None):
        member = self.member(fullname)
        if member:
            return importlib.util.spec_from_loader(fullname, self,
                                                  is_package=member.endswith("/__init__.py"))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = "<publisher-runtime>/" + self.member(module.__name__)
        exec(compile(self.archive.read(self.member(module.__name__)), module.__file__, "exec"),
             module.__dict__)

    def get_data(self, path):
        prefix = "<publisher-runtime>/"
        normalized = path.replace("\\", "/")
        if not normalized.startswith(prefix):
            raise OSError("resource outside runtime")
        return self.archive.read(normalized[len(prefix):])

    def run(self, args):
        sys.meta_path.insert(0, self)
        sys.argv = ["publisher-runtime", *args]
        try:
            exec(compile(self.archive.read("__main__.py"), "<publisher-entry>", "exec"),
                 {"__name__": "__main__"})
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise
        finally:
            sys.meta_path.remove(self)


def data_root(policy):
    name = policy["plugin"]
    return Path(os.environ.get(name.upper().replace("-", "_") + "_HOME",
                               str(Path.home() / ".codex" / PLUGINS[name])))


class HookInputError(ValueError):
    """Input failure labels/counts only; never echo input or parser messages."""

    def __init__(self, code, byte_count):
        super().__init__(code)
        self.code = code
        self.byte_count = byte_count


def read_hook_input(stream, event):
    """Parse complete stdin; preserve accepted bytes for the Governor."""
    raw = stream.read()
    try:
        payload = parse(raw)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise HookInputError("HOOK_INPUT_INVALID_JSON", len(raw)) from error
    if not isinstance(payload, dict) or payload.get("hook_event_name") != event:
        raise HookInputError("HOOK_INPUT_INVALID_METADATA", len(raw))
    task = payload.get("session_id")
    if not isinstance(task, str) or not 0 < len(task) <= 256:
        raise HookInputError("HOOK_INPUT_INVALID_SESSION", len(raw))
    return raw, payload


def failure_message(phase, error):
    """Emit fixed phase/class labels and counts, never exception text or payload."""
    phases = {"publisher-initialize", "publisher-seed", "hook-event", "hook-input",
              "runtime-select", "update-schedule", "runtime-execute", "runtime-output",
              "runtime-notice"}
    phase = phase if phase in phases else "runtime"
    cause = error.__cause__ if isinstance(error, HookInputError) and error.__cause__ else error
    classes = (HookInputError, json.JSONDecodeError, UnicodeDecodeError, RecursionError,
               sqlite3.OperationalError, sqlite3.DatabaseError,
               FileNotFoundError, PermissionError, MemoryError, ValueError, OSError, RuntimeError)
    name = next((cls.__name__ for cls in classes if isinstance(cause, cls)), "Exception")
    codes = {"HOOK_INPUT_INVALID_JSON", "HOOK_INPUT_INVALID_METADATA",
             "HOOK_INPUT_INVALID_SESSION"}
    if isinstance(error, HookInputError) and error.code in codes:
        return (f"Signed Run Budget {error.code} [{phase}; {name}; "
                f"input_bytes={error.byte_count}]. "
                "Operation remains blocked.")
    return f"Signed Run Budget failure [{phase}; {name}]. Operation remains blocked."


def unavailable(event, enforcing, *, phase=None, error=None):
    if not enforcing:
        return {}
    message = "Signed Run Budget runtime unavailable; restore a verified version."
    if error is not None:
        message = failure_message(phase, error)
    result = {"systemMessage": message}
    if event == "PreToolUse":
        result["hookSpecificOutput"] = {"hookEventName": event, "permissionDecision": "deny",
                                        "permissionDecisionReason": message}
    elif event == "UserPromptSubmit":
        result.update(decision="block", reason=message)
    else:
        result.update({"continue": False, "stopReason": message})
    return result


def main(source, policy, argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    event = args[0] if args else "unknown"
    publisher = None
    phase = "publisher-initialize"
    try:
        root = Path(args[1]) if event in {"--worker", "--control", "--cli"} else data_root(policy)
        publisher = Publisher(root, policy, source)
        plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
        if event == "--worker":
            # Bound DNS, TLS and stream stalls too. No model or scheduler is invoked.
            def expired(signum, frame):
                raise SystemExit(0)
            signal.signal(signal.SIGALRM, expired)
            signal.alarm(20)
            publisher.update(automatic=True)
            return 0
        phase = "publisher-seed"
        publisher.seed(plugin_root)
        if event == "--control":
            print(json.dumps(publisher.control(args[2]), ensure_ascii=False))
            return 0
        if event == "--cli":
            _, blob, _ = publisher.select()
            RuntimeLoader(blob, policy["plugin"].replace("-", "_")).run(["--cli", *args[2:]])
            return 0
        phase = "hook-event"
        if event not in policy["events"]:
            raise ValueError("unknown hook event")
        phase = "hook-input"
        raw, payload = read_hook_input(sys.stdin.buffer, event)
        task = payload["session_id"]
        phase = "runtime-select"
        manifest, blob, fresh = publisher.select(task)
        if event == "UserPromptSubmit" and not payload.get("agent_id"):
            phase = "update-schedule"
            publisher.schedule()
        output = io.StringIO()
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        phase = "runtime-execute"
        with contextlib.redirect_stdout(output):
            RuntimeLoader(blob, policy["plugin"].replace("-", "_")).run(["--event", event])
        phase = "runtime-output"
        result = parse(output.getvalue() or "{}")
        phase = "runtime-notice"
        if fresh and event in {"SessionStart", "UserPromptSubmit"}:
            message = f"{policy['plugin']}: verified signed runtime {manifest['version']}. "
            message += "此任務固定使用這一版 / version pinned for this Task."
            notice = publisher.get("last_result", {})
            if notice.get("status") == "requires_plugin_update":
                message += (" 外掛入口有更新，請更新外掛後到 codex → /hooks 重新授權。"
                            " Plugin update and hook review required.")
            result["systemMessage"] = "\n".join(
                filter(None, (result.get("systemMessage"), message)))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        if event in {"--cli", "--control"}:
            print(json.dumps({"status": "unavailable"}))
            return 1
        if event != "--worker":
            print(json.dumps(unavailable(event, policy["plugin"] == "codex-run-budget",
                                         phase=phase, error=error)))
        return 0
    finally:
        if publisher is not None:
            publisher.close()


def runtime_cli(plugin, argv):
    """Use the verified active runtime for manual CLI work once initialized."""
    policy = parse(read(plugin / "runtime/publisher.json", MAX_MANIFEST))
    root = data_root(policy)
    index = 0
    while index < len(argv) and argv[index] in {"--data-dir", "--codex-home", "--locale"}:
        if index + 1 >= len(argv):
            return None  # Leave argparse's normal error handling in place.
        if argv[index] == "--data-dir":
            root = Path(argv[index + 1])
        index += 2
    if not (root / "publisher-updates.sqlite3").is_file():
        return None
    os.environ["PLUGIN_ROOT"] = str(plugin)
    source = read(plugin / "scripts/publisher_bootstrap.py", MAX_RUNTIME)
    return main(source, policy, ["--cli", str(root), *argv])


if __name__ == "__main__":
    raise SystemExit(main(SOURCE, POLICY))  # noqa: F821 - embedded by the build script
