"""Offline contention tests with synthetic keys, stores and Task identities."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_governor import Governor, token_line
from test_publisher_updates import BOOT, PLUGIN, ROOT, SOURCE, PublisherFixture


class PublisherConcurrencyTest(PublisherFixture):
    # Keep safe phase/class labels visible when only a few workers fail in CI.
    maxDiff = None

    def parallel_hooks(self, payloads, plugin, *, data=None):
        """Start separate native-command interpreters, then release them together."""
        gate = self.root / ("gate-" + uuid.uuid4().hex)
        ready = [gate.with_name(gate.name + f"-{index}") for index in range(len(payloads))]
        env = {**os.environ, "CODEX_PLUGIN_AUTO_UPDATE": "0",
               "PLUGIN_ROOT": str(plugin), "CODEX_RUN_BUDGET_HOME": str(data or self.root / "data"),
               "CODEX_HOME": str(self.root / "native")}

        def invoke(index):
            diagnostics = ready[index].with_suffix(".sqlite-errors")
            prelude = (
                (ROOT / "tests/sqlite_probe.py").read_text()
                + f"\ninstall({str(diagnostics)!r})\n"
                +
                "import pathlib,time\n"
                f"pathlib.Path({str(ready[index])!r}).touch()\n"
                "deadline=time.monotonic()+15\n"
                f"while not pathlib.Path({str(gate)!r}).exists():\n"
                " if time.monotonic()>deadline: raise TimeoutError('test start gate')\n"
                " time.sleep(.005)\n"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", prelude + BOOT.entry(SOURCE, self.policy),
                 payloads[index]["hook_event_name"]], input=json.dumps(payloads[index]),
                capture_output=True, text=True, env=env, timeout=20,
            )
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            return json.loads(result.stdout)

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            futures = [pool.submit(invoke, index) for index in range(len(payloads))]
            try:
                deadline = time.monotonic() + 15
                while not all(path.exists() for path in ready):
                    self.assertLess(time.monotonic(), deadline,
                                    "workers failed to reach start gate")
                    time.sleep(.005)
            finally:
                gate.touch()
            outputs = [future.result() for future in futures]
            failed = next((output for output in outputs if
                           "internal error" in json.dumps(output) or
                           "Signed Run Budget failure" in json.dumps(output)), None)
            if failed is not None:
                failed["test_sqlite_timelines"] = {
                    str(index): json.loads(path.with_suffix(".sqlite-errors").read_text())
                    for index, path in enumerate(ready)
                    if path.with_suffix(".sqlite-errors").exists()
                }
            return outputs

    def governor_runtime(self):
        spec = importlib.util.spec_from_file_location("concurrency_builder",
                                                     ROOT / "scripts/build_hook_runtime.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        return builder.artifacts(PLUGIN)[PLUGIN / "runtime/publisher.pyz"]

    def packaged(self, manifest, blob):
        plugin = self.root / "package"
        (plugin / "runtime").mkdir(parents=True)
        (plugin / "runtime/release.json").write_bytes(BOOT.canonical(manifest))
        (plugin / "runtime/publisher.pyz").write_bytes(blob)
        return plugin

    def test_existing_pin_and_seed_are_read_only_during_another_writer(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        self.publisher.select("synthetic-pinned")
        plugin = self.packaged(manifest, blob)
        writer = sqlite3.connect(self.root / "data/publisher-updates.sqlite3")
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        try:
            peer = BOOT.Publisher(self.root / "data", self.policy, SOURCE)
            try:
                peer.seed(plugin)
                self.assertEqual(peer.db.total_changes, 0)
                selected, retained, fresh = peer.select("synthetic-pinned")
                self.assertEqual((selected, retained, fresh), (manifest, blob, False))
                self.assertEqual(peer.db.total_changes, 0)
                self.assertFalse(peer.db.in_transaction)
            finally:
                peer.close()
        finally:
            writer.rollback()

    def test_retaining_identical_release_is_read_only_during_another_writer(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        writer = sqlite3.connect(self.root / "data/publisher-updates.sqlite3")
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        changes = self.publisher.db.total_changes
        try:
            self.assertEqual(self.publisher.retain(manifest, blob), manifest["runtime_sha256"])
        finally:
            writer.rollback()
        self.assertEqual(self.publisher.db.total_changes, changes)
        with self.assertRaises(ValueError):
            self.publisher.retain(manifest, blob + b"corrupt")

    def test_24_readers_do_not_serialize_runtime_verification(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        self.publisher.select("synthetic-pinned")
        gate = threading.Barrier(24)
        original = BOOT.runtime_bytes

        def slow_read(path, release):
            time.sleep(0.025)
            return original(path, release)

        def select(_):
            peer = BOOT.Publisher(self.root / "data", self.policy, SOURCE)
            try:
                gate.wait(timeout=10)
                return peer.select("synthetic-pinned")
            finally:
                peer.close()

        with patch.object(BOOT, "runtime_bytes", side_effect=slow_read):
            with ThreadPoolExecutor(max_workers=24) as pool:
                results = list(pool.map(select, range(24)))
        self.assertEqual(results, [(manifest, blob, False)] * 24)

    def test_validation_never_holds_the_selection_write_lock(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        original = BOOT.runtime_bytes

        def verify_without_writer(path, release):
            self.assertFalse(self.publisher.db.in_transaction)
            probe = sqlite3.connect(self.root / "data/publisher-updates.sqlite3", timeout=0)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            finally:
                probe.close()
            return original(path, release)

        with patch.object(BOOT, "runtime_bytes", side_effect=verify_without_writer):
            self.assertEqual(self.publisher.select("synthetic-fresh"), (manifest, blob, True))

    def test_sqlite_failure_keeps_class_without_private_error_text(self):
        error = sqlite3.OperationalError("PRIVATE_PATH_MUST_NOT_APPEAR")
        result = BOOT.unavailable("PreToolUse", True, phase="runtime-select", error=error)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("OperationalError", result["systemMessage"])
        self.assertNotIn("PRIVATE_PATH_MUST_NOT_APPEAR", str(result))

    def test_24_process_cold_start_same_pin_and_distinct_jobs(self):
        manifest, blob = self.release(1, "SAFE", runtime=self.governor_runtime())
        plugin = self.packaged(manifest, blob)
        data = self.root / "cold-data"
        same = [{"hook_event_name": "PreToolUse", "session_id": "synthetic-shared"}] * 24
        for payloads in (same, same, [dict(same[0], session_id=f"synthetic-job-{i}")
                                    for i in range(24)]):
            self.assertEqual(self.parallel_hooks(payloads, plugin, data=data), [{}] * 24)
        with sqlite3.connect(data / "publisher-updates.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 25)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM releases").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_24_process_governor_replay_accounting_isolation_and_halt(self):
        manifest, blob = self.release(1, "SAFE", runtime=self.governor_runtime())
        self.publisher.activate(manifest, blob)
        plugin = self.packaged(manifest, blob)
        governor = Governor(self.root / "data")
        self.addCleanup(governor.close)
        bases = []
        for job in range(3):
            transcript = self.root / f"synthetic-{job}.jsonl"
            transcript.write_text(token_line(0) + "\n")
            base = {"session_id": f"synthetic-run-{job}", "transcript_path": str(transcript)}
            result = governor.handle(dict(base, hook_event_name="UserPromptSubmit",
                                          prompt="run-budget:start tokens=1k inflight=32"))
            self.assertIn("Started", json.dumps(result))
            transcript.write_text(token_line((job + 1) * 120) + "\n")
            bases.append(base)
        pre = [dict(bases[index % 3], hook_event_name="PreToolUse", tool_name="Read",
                    tool_use_id=f"synthetic-call-{index}", tool_input={"index": index})
               for index in range(24)]
        post = [dict(payload, hook_event_name="PostToolUse", tool_response={"ok": True})
                for payload in pre]
        for payloads in (pre, pre, post, post):
            self.assertEqual(self.parallel_hooks(payloads, plugin), [{}] * 24)
        for job, base in enumerate(bases):
            run = governor.ledger.get_run(base["session_id"])
            self.assertEqual((run["spent_tokens"], run["tool_calls"], run["in_flight"]),
                             ((job + 1) * 120, 8, 0))
            events = governor.ledger.events(base["session_id"])
            for kind, count in (("usage_observed", 1), ("tool_admitted", 8), ("tool_completed", 8)):
                self.assertEqual(sum(event["kind"] == kind for event in events), count)
        Path(bases[0]["transcript_path"]).write_text(token_line(1001) + "\n")
        next_calls = [dict(payload, tool_use_id=payload["tool_use_id"] + "-next")
                      for payload in pre]
        results = self.parallel_hooks(next_calls, plugin)
        for index, result in enumerate(results):
            denied = result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            self.assertEqual(denied, index % 3 == 0)
            self.assertNotIn("internal error", json.dumps(result))
        run = governor.ledger.get_run(bases[0]["session_id"])
        self.assertEqual((run["spent_tokens"], run["tool_calls"], run["status"]),
                         (1001, 8, "halted"))

    def test_activation_during_validation_rechecks_before_pinning(self):
        a, blob_a = self.release(1, "A")
        b, blob_b = self.release(2, "B")
        self.publisher.activate(a, blob_a)
        peer = BOOT.Publisher(self.root / "data", self.policy, SOURCE)
        self.addCleanup(peer.close)
        original = BOOT.runtime_bytes
        activated = False

        def changed(path, manifest):
            nonlocal activated
            blob = original(path, manifest)
            if not activated:
                activated = True
                peer.activate(b, blob_b)
            return blob

        with patch.object(BOOT, "runtime_bytes", side_effect=changed):
            self.assertEqual(self.publisher.select("synthetic-racing"), (b, blob_b, True))
        self.assertEqual(peer.select("synthetic-racing"), (b, blob_b, False))

    def test_peer_pin_wins_during_validation(self):
        a, blob_a = self.release(1, "A")
        b, blob_b = self.release(2, "B")
        self.publisher.activate(a, blob_a)
        peer = BOOT.Publisher(self.root / "data", self.policy, SOURCE)
        self.addCleanup(peer.close)
        original = BOOT.runtime_bytes
        pinned = False

        def changed(path, manifest):
            nonlocal pinned
            blob = original(path, manifest)
            if not pinned:
                pinned = True
                peer.select("synthetic-racing")
                peer.activate(b, blob_b)
            return blob

        with patch.object(BOOT, "runtime_bytes", side_effect=changed):
            self.assertEqual(self.publisher.select("synthetic-racing"), (a, blob_a, False))

    def test_constructor_failure_closes_connection(self):
        real_connect = BOOT.sqlite3.connect
        connections = []

        class BrokenConnection(sqlite3.Connection):
            def executescript(self, script):
                raise sqlite3.OperationalError("synthetic failure")

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=BrokenConnection)
            connections.append(connection)
            return connection

        with patch.object(BOOT.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(sqlite3.OperationalError):
                BOOT.Publisher(self.root / "data", self.policy, SOURCE)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")

    def test_fallback_does_not_overwrite_concurrent_activation(self):
        a, blob_a = self.release(1, "A")
        b, blob_b = self.release(2, "B")
        c, blob_c = self.release(3, "C")
        self.publisher.activate(a, blob_a)
        self.publisher.activate(b, blob_b)
        (self.root / "data/runtimes" / (b["runtime_sha256"] + ".pyz")).write_bytes(b"corrupt")
        peer = BOOT.Publisher(self.root / "data", self.policy, SOURCE)
        self.addCleanup(peer.close)
        original = BOOT.runtime_bytes

        def changed(path, manifest):
            blob = original(path, manifest)
            if manifest == a:
                peer.activate(c, blob_c)
            return blob

        with patch.object(BOOT, "runtime_bytes", side_effect=changed):
            self.assertEqual(self.publisher.select("synthetic-racing"), (c, blob_c, True))
        self.assertEqual(self.publisher.get("active"), c["runtime_sha256"])

    def test_selection_churn_is_bounded_and_leaves_no_transaction_or_pin(self):
        a, blob_a = self.release(1, "A")
        b, blob_b = self.release(2, "B")
        self.publisher.activate(a, blob_a)
        self.publisher.retain(b, blob_b)
        original = BOOT.runtime_bytes
        calls = []

        def changed(path, manifest):
            blob = original(path, manifest)
            calls.append(manifest["runtime_sha256"])
            with self.publisher.db:
                self.publisher.put("active", (b if manifest == a else a)["runtime_sha256"])
            return blob

        with patch.object(BOOT, "runtime_bytes", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "changed repeatedly"):
                self.publisher.select("synthetic-racing")
        self.assertEqual(len(calls), 4)
        self.assertFalse(self.publisher.db.in_transaction)
        self.assertEqual(self.publisher.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertTrue(self.publisher.select("synthetic-racing")[2])

    def test_busy_failure_is_visible_then_retry_commits_once(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        writer = sqlite3.connect(self.root / "data/publisher-updates.sqlite3")
        self.addCleanup(writer.close)
        writer.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.publisher.select("synthetic-retry")
        finally:
            writer.rollback()
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(self.publisher.db.in_transaction)
        self.assertTrue(self.publisher.select("synthetic-retry")[2])
        self.assertFalse(self.publisher.select("synthetic-retry")[2])
        self.assertEqual(self.publisher.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)

    def test_seed_does_not_hide_database_errors(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        newer, newer_blob = self.release(2, "NEW")
        plugin = self.packaged(newer, newer_blob)
        with patch.object(self.publisher, "activate", side_effect=sqlite3.OperationalError("busy")):
            with self.assertRaises(sqlite3.OperationalError):
                self.publisher.seed(plugin)

    def test_process_crash_before_and_after_pin_commit_is_replayable(self):
        manifest, blob = self.release(1, "SAFE")
        self.publisher.activate(manifest, blob)
        for after_commit in (False, True):
            task = f"synthetic-crash-{after_commit}"
            code = (
                SOURCE.decode().split('if __name__ == "__main__":')[0]
                + f"\np=Publisher({str(self.root / 'data')!r},{self.policy!r},{SOURCE!r})\n"
                + ("" if after_commit else
                   "p.db.set_trace_callback(lambda sql: os._exit(73) "
                   "if sql.startswith('DELETE FROM tasks') else None)\n")
                + f"p.select({task!r})\nos._exit(74)\n"
            )
            result = subprocess.run([sys.executable, "-I", "-c", code],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 74 if after_commit else 73, result.stderr)
            self.assertEqual(self.publisher.select(task), (manifest, blob, not after_commit))
            self.assertFalse(self.publisher.select(task)[2])
        self.assertEqual(self.publisher.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        self.assertEqual(self.publisher.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_ledger_process_crash_and_replay_preserve_exact_accounting(self):
        governor = Governor(self.root / "data")
        self.addCleanup(governor.close)
        transcript = self.root / "synthetic-crash.jsonl"
        transcript.write_text(token_line(0) + "\n")
        base = {"session_id": "synthetic-crash", "transcript_path": str(transcript)}
        governor.handle(dict(base, hook_event_name="UserPromptSubmit",
                             prompt="run-budget:start tokens=1k"))
        transcript.write_text(token_line(123) + "\n")
        for after_commit in (False, True):
            payload = dict(base, hook_event_name="PreToolUse", tool_name="Read",
                           tool_use_id=f"synthetic-crash-{after_commit}",
                           tool_input={"index": after_commit})
            code = (
                "import os,sys\n"
                f"sys.path.insert(0,{str(PLUGIN / 'lib')!r})\n"
                "from codex_run_budget.governor import Governor\n"
                "from pathlib import Path\n"
                f"g=Governor(Path({str(self.root / 'data')!r}))\n"
                + ("" if after_commit else
                   "g.ledger.conn.set_trace_callback(lambda sql: os._exit(73) "
                   "if sql.startswith('UPDATE runs SET tool_calls=') else None)\n")
                + f"g.handle({payload!r})\nos._exit(74)\n"
            )
            result = subprocess.run([sys.executable, "-I", "-c", code],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 74 if after_commit else 73, result.stderr)
            self.assertIsNone(governor.handle(payload))
            self.assertIsNone(governor.handle(payload))
            self.assertIsNone(governor.handle(dict(payload, hook_event_name="PostToolUse",
                                                   tool_response={"ok": True})))
        run = governor.ledger.get_run(base["session_id"])
        self.assertEqual((run["spent_tokens"], run["tool_calls"], run["in_flight"]), (123, 2, 0))
        events = governor.ledger.events(base["session_id"])
        for kind, count in (("usage_observed", 1), ("tool_admitted", 2), ("tool_completed", 2)):
            self.assertEqual(sum(event["kind"] == kind for event in events), count)
