from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget import auto_preview  # noqa: E402
from codex_run_budget.auto_preview import preview, render_card  # noqa: E402
from codex_run_budget.auto_report import configure, handle, observed_total, recent  # noqa: E402
from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.report_i18n import LOCALES, ReportText  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402
from test_auto_report import baseline_role_case, counter, native_counter  # noqa: E402

TASK = "00000000-0000-7000-8000-000000000001"


class AutoPreviewTest(unittest.TestCase):
    def setUp(self):
        quota_source = patch("codex_run_budget.turn_quota.read_meter_sources", return_value={})
        quota_source.start()
        self.addCleanup(quota_source.stop)
        for module in ("auto_preview", "auto_report"):
            locale = patch("codex_run_budget." + module + ".resolve_locale",
                           return_value={"locale": "zh-Hant", "locale_source": "test"})
            locale.start()
            self.addCleanup(locale.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        self.workspace = self.root / "workspace"
        self.output = self.workspace / "visuals"
        self.transcript = self.root / "secret-source.jsonl"
        self.meta = {"type": "session_meta", "payload": {"id": TASK}}
        self.transcript.write_text(json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n")
        self.db = sqlite3.connect(self.root / "state_5.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY,name TEXT,agent_nickname TEXT,"
            "agent_role TEXT,agent_path TEXT,source TEXT,rollout_path TEXT)"
        )
        self.db.execute("INSERT INTO threads VALUES (?, ?, NULL, NULL, NULL, 'vscode', ?)",
                        (TASK, '改善 <報告> $total', str(self.transcript)))
        self.db.commit()
        self.db.execute("ALTER TABLE threads ADD COLUMN cwd TEXT")
        self.db.execute("UPDATE threads SET cwd=? WHERE id=?", (str(self.workspace), TASK))
        self.db.commit()
        self.payload = {
            "session_id": TASK, "turn_id": "turn-1", "hook_event_name": "UserPromptSubmit",
            "transcript_path": str(self.transcript), "model": "gpt-6-astra",
        }
        handle(self.payload, self.data)
        with self.transcript.open("a") as output:
            output.write(json.dumps({"type": "turn_context", "payload": {
                "turn_id": "turn-1", "model": "gpt-6-astra", "effort": "xhigh"
            }}) + "\n" + json.dumps(counter(1500)) + "\n")

    def preview(self, **extra):
        return preview(self.data, TASK, "turn-1", output_dir=self.output, home=self.root, **extra)

    def nested_child(self, child="00000000-0000-7000-8000-000000000003"):
        parent = "00000000-0000-7000-8000-000000000002"
        turn = "synthetic-nested-turn"
        parent_source = {"subagent": {"thread_spawn": {"parent_thread_id": TASK}}}
        child_source = {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
        transcript = self.root / "synthetic-nested.jsonl"
        stamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        transcript.write_text("".join(json.dumps(row) + "\n" for row in (
            {"type": "session_meta", "timestamp": stamp,
             "payload": {"id": child, "source": child_source}},
            {"type": "event_msg", "timestamp": stamp,
             "payload": {"type": "task_started", "turn_id": turn, "thread_id": child}},
            counter(100),
        )))
        self.db.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (parent, 'direct <parent> "example"', "parent", "worker", "/root/parent",
                 json.dumps(parent_source), None, str(self.workspace)),
                (child, "nested <child>", "child", "worker", "/root/parent/child",
                 json.dumps(child_source), str(transcript), str(self.workspace)),
            ),
        )
        self.db.commit()
        payload = {"session_id": TASK, "agent_id": child, "turn_id": turn,
                   "hook_event_name": "SubagentStart", "transcript_path": str(transcript)}
        self.assertEqual(set(handle(payload, self.data, home=self.root)), {"hookSpecificOutput"})
        with transcript.open("a") as output:
            output.write("".join(json.dumps(row) + "\n" for row in (
                {"type": "turn_context", "payload": {
                    "turn_id": turn, "model": "synthetic-child-model", "effort": "high"
                }},
                counter(150),
            )))
        return child, parent, turn, transcript

    def test_nested_child_card_shows_own_usage_and_escaped_direct_parent(self):
        child, parent, turn, _ = self.nested_child()
        result = preview(self.data, child, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "preview")
        content = next(self.output.glob("*.html")).read_text()
        for expected in ("nested &lt;child&gt;", "@" + stable_hash(child)[:12],
                         '由 direct &lt;parent&gt; &quot;example&quot; 派生',
                         "Task 累積 Token（此子代理）", "本輪增加 Token（此子代理）",
                         "本輪此子代理設定", "此子代理＋其後代", "後代已觀測小計",
                         'data-metric="task-total">150</dd>',
                         'data-metric="turn-delta">+50</dd>'):
            self.assertIn(expected, content)
        for unexpected in ("<parent>", "<child>", "主代理", parent, child, TASK):
            self.assertNotIn(unexpected, content)

    def test_inherited_root_moves_nested_child_to_own_uuid_date_and_preserves_parent(self):
        child, _, turn, _ = self.nested_child("00000526-5c00-7000-8000-000000000003")
        inherited = self.root / "visualizations/1970/01/01" / TASK / "cards/nested"
        parent = preview(self.data, TASK, "turn-1", output_dir=inherited, home=self.root)
        parent_path = Path(json.loads(parent["reference"].split("\ue202")[1][:-1])["path"])
        parent_content = parent_path.read_bytes()

        result = preview(self.data, child, turn, output_dir=inherited, home=self.root)
        target = Path(json.loads(result["reference"].split("\ue202")[1][:-1])["path"])
        own = self.root / "visualizations/1970/01/02" / child / "cards/nested"
        self.assertEqual(target.parent, own)
        self.assertIn('data-metric="turn-delta">+50</dd>', target.read_text())
        self.assertEqual(list(inherited.glob("*.html")), [parent_path])
        self.assertEqual(parent_path.read_bytes(), parent_content)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

        direct = preview(self.data, child, turn, output_dir=own, home=self.root)
        direct_path = Path(json.loads(direct["reference"].split("\ue202")[1][:-1])["path"])
        self.assertEqual(direct_path.parent, own)
        self.assertNotEqual(direct_path, target)

    def test_inherited_root_does_not_bypass_missing_or_changed_source_evidence(self):
        child, _, turn, transcript = self.nested_child()
        inherited = self.root / "visualizations/1970/01/01" / TASK
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": TASK
        }}) + "\n")
        with patch("codex_run_budget.auto_preview.collect") as children, patch(
            "codex_run_budget.turn_quota.observe"
        ) as quota:
            result = preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertEqual(result["status"], "source_unavailable")
        children.assert_not_called()
        quota.assert_not_called()
        self.assertFalse((self.root / "visualizations").exists())

    def test_child_relocation_rejects_foreign_roots_and_unsafe_source_or_destination(self):
        child, parent, turn, _ = self.nested_child()
        roots = self.root / "visualizations/1970/01/01"
        inherited = roots / TASK
        own = roots / child
        self.workspace.mkdir()
        inherited.mkdir(parents=True)
        (inherited / "alias").symlink_to(self.workspace, target_is_directory=True)
        outside = (
            roots / "00000000-0000-7000-8000-000000000099",
            roots / parent,
            self.root / "visualizations/1970/01/02" / TASK,
            inherited / ".." / child,
            inherited / "alias/cards",
            Path("relative/cards"),
        )
        with patch("codex_run_budget.auto_preview.snapshot") as observed, patch(
            "codex_run_budget.auto_preview.collect"
        ) as children, patch("codex_run_budget.turn_quota.observe") as quota:
            for directory in outside:
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    preview(self.data, child, turn, output_dir=directory, home=self.root)
            own.symlink_to(self.workspace, target_is_directory=True)
            with self.assertRaises(ValueError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
            observed.assert_not_called()
            children.assert_not_called()
            quota.assert_not_called()
        self.assertFalse(list(self.workspace.rglob("*.html")))
        self.assertFalse(list(inherited.glob("*.html")))

    def test_inherited_source_path_is_rechecked_after_collection(self):
        child, _, turn, _ = self.nested_child()
        roots = self.root / "visualizations/1970/01/01"
        roots.mkdir(parents=True)
        inherited = roots / TASK
        with patch("codex_run_budget.turn_quota.observe", side_effect=lambda *a, **k:
                   inherited.symlink_to(self.workspace, target_is_directory=True)):
            with self.assertRaises(ValueError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertFalse((roots / child).exists())

    def test_inherited_source_path_is_rechecked_after_rendering(self):
        child, _, turn, _ = self.nested_child()
        roots = self.root / "visualizations/1970/01/01"
        roots.mkdir(parents=True)
        inherited = roots / TASK

        def replace_source(receipt):
            inherited.symlink_to(self.workspace, target_is_directory=True)
            return render_card(receipt)

        with patch("codex_run_budget.auto_preview.render_card", side_effect=replace_source):
            with self.assertRaises(ValueError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertTrue(inherited.is_symlink())
        self.assertFalse((roots / child).exists())
        self.assertFalse(self.workspace.exists())

    def test_relocated_permission_error_falls_back_once_to_child_workspace_same_snapshot(self):
        child, _, turn, _ = self.nested_child()
        child_workspace = self.root / "child-workspace"
        self.db.execute("UPDATE threads SET cwd=? WHERE id=?", (str(child_workspace), child))
        self.db.commit()
        roots = self.root / "visualizations/1970/01/01"
        inherited = roots / TASK / "cards"
        own = roots / child / "cards"
        original_open = os.open
        attempts = []

        def deny_native(target, *args, **kwargs):
            if Path(target).suffix == ".html":
                attempts.append(Path(target))
            if Path(target).parent == own:
                raise PermissionError("synthetic native directory denial")
            return original_open(target, *args, **kwargs)

        with patch("codex_run_budget.auto_preview.os.open", side_effect=deny_native), patch(
            "codex_run_budget.auto_preview.snapshot", wraps=auto_preview.snapshot
        ) as observed, patch(
            "codex_run_budget.auto_preview.collect", wraps=auto_preview.collect
        ) as children, patch(
            "codex_run_budget.turn_quota.observe", return_value=None
        ) as quota, patch(
            "codex_run_budget.auto_preview.render_card", wraps=render_card
        ) as renderer:
            result = preview(self.data, child, turn, output_dir=inherited, home=self.root)
        target = Path(json.loads(result["reference"].split("\ue202")[1][:-1])["path"])
        self.assertEqual(target.parent, child_workspace / "work/codex-usage-cards")
        self.assertTrue(target.is_relative_to(child_workspace))
        self.assertIn('data-metric="turn-delta">+50</dd>', target.read_text())
        self.assertEqual(attempts, [own / target.name, target])
        for reader in (observed, children, quota, renderer):
            reader.assert_called_once()
        self.assertFalse(list(own.glob("*.html")))
        self.assertFalse(inherited.exists())
        self.assertFalse(self.workspace.exists())

    def test_relocated_mkdir_denial_falls_back_but_parent_or_own_root_denial_does_not(self):
        child, _, turn, _ = self.nested_child()
        roots = self.root / "visualizations/1970/01/01"
        inherited = roots / TASK
        own = roots / child
        original_mkdir = Path.mkdir

        def deny_native(directory, *args, **kwargs):
            if directory in (own, inherited):
                raise PermissionError("synthetic mkdir denial")
            return original_mkdir(directory, *args, **kwargs)

        with patch.object(Path, "mkdir", new=deny_native):
            for task, task_turn, directory in ((TASK, "turn-1", inherited), (child, turn, own)):
                with self.subTest(task=task), self.assertRaises(PermissionError):
                    preview(self.data, task, task_turn, output_dir=directory, home=self.root)
            self.assertFalse(self.workspace.exists())
            result = preview(self.data, child, turn, output_dir=inherited, home=self.root)
        target = Path(json.loads(result["reference"].split("\ue202")[1][:-1])["path"])
        self.assertEqual(target.parent, self.workspace / "work/codex-usage-cards")
        self.assertTrue(target.is_file())

    def test_fallback_rejects_missing_relative_parent_or_symlink_workspace(self):
        child, _, turn, _ = self.nested_child()
        inherited = self.root / "visualizations/1970/01/01" / TASK
        original_mkdir = Path.mkdir
        own = self.root / "visualizations/1970/01/01" / child

        def deny_native(directory, *args, **kwargs):
            if directory == own:
                raise PermissionError("synthetic mkdir denial")
            return original_mkdir(directory, *args, **kwargs)

        alias = self.root / "workspace-alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        workspaces = (None, "relative", str(self.workspace / ".." / "escape"), str(alias))
        with patch.object(Path, "mkdir", new=deny_native):
            for workspace in workspaces:
                with self.subTest(workspace=workspace):
                    self.db.execute("UPDATE threads SET cwd=? WHERE id=?", (workspace, child))
                    self.db.commit()
                    with self.assertRaises((PermissionError, ValueError)):
                        preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertFalse(self.workspace.exists())
        self.assertFalse((self.root / "escape").exists())

    def test_fallback_rechecks_inherited_source_after_permission_error(self):
        child, _, turn, _ = self.nested_child()
        roots = self.root / "visualizations/1970/01/01"
        roots.mkdir(parents=True)
        inherited = roots / TASK
        own = roots / child
        original_mkdir = Path.mkdir

        def deny_native_and_replace_source(directory, *args, **kwargs):
            if directory == own:
                inherited.symlink_to(self.workspace, target_is_directory=True)
                raise PermissionError("synthetic mkdir denial with source replacement")
            return original_mkdir(directory, *args, **kwargs)

        with patch.object(Path, "mkdir", new=deny_native_and_replace_source):
            with self.assertRaises(ValueError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertTrue(inherited.is_symlink())
        self.assertFalse(own.exists())
        self.assertFalse(self.workspace.exists())

    def test_fallback_rejects_symlink_subdirectory_and_never_overwrites_existing_card(self):
        child, _, turn, _ = self.nested_child()
        inherited = self.root / "visualizations/1970/01/01" / TASK
        own = self.root / "visualizations/1970/01/01" / child
        original_mkdir = Path.mkdir

        def deny_native(directory, *args, **kwargs):
            if directory == own:
                raise PermissionError("synthetic mkdir denial")
            return original_mkdir(directory, *args, **kwargs)

        self.workspace.mkdir()
        alias = self.workspace / "work"
        alias.symlink_to(self.root, target_is_directory=True)
        with patch.object(Path, "mkdir", new=deny_native):
            with self.assertRaises(ValueError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertFalse((self.root / "codex-usage-cards").exists())
        alias.unlink()
        fallback = self.workspace / "work/codex-usage-cards"
        fallback.mkdir(parents=True)
        target = fallback / ("codex-turn-" + stable_hash([child, turn])[:16] + "-123.html")
        target.write_text("synthetic existing card")
        with patch.object(Path, "mkdir", new=deny_native), patch(
            "codex_run_budget.auto_preview.time.time_ns", return_value=123
        ):
            with self.assertRaises(FileExistsError):
                preview(self.data, child, turn, output_dir=inherited, home=self.root)
        self.assertEqual(target.read_text(), "synthetic existing card")
        self.assertFalse(inherited.exists())

    def test_child_preview_rejects_changed_ancestor_root_before_reading_usage(self):
        child, parent, turn, _ = self.nested_child()
        other_root = "00000000-0000-7000-8000-000000000004"
        self.db.execute("INSERT INTO threads VALUES (?, ?, NULL, NULL, NULL, 'vscode', NULL, ?)",
                        (other_root, "synthetic other root", str(self.workspace)))
        self.db.execute("UPDATE threads SET source=? WHERE id=?", (
            json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": other_root}}}), parent
        ))
        self.db.commit()
        self.assert_child_identity_unavailable(child, turn)

    def test_child_preview_rejects_legacy_baseline_without_root_evidence(self):
        child, _, turn, _ = self.nested_child()
        with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
            key = stable_hash([child, turn])
            baseline = json.loads(timing.execute(
                "SELECT baseline FROM turns WHERE key=?", (key,)
            ).fetchone()[0])
            baseline.pop("root_hash", None)
            timing.execute("UPDATE turns SET baseline=? WHERE key=?", (json.dumps(baseline), key))
        self.assert_child_identity_unavailable(child, turn)

    def test_child_preview_rejects_conflicting_or_unknown_explicit_role(self):
        child, _, turn, _ = self.nested_child()
        key = stable_hash([child, turn])
        with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
            baseline = json.loads(timing.execute(
                "SELECT baseline FROM turns WHERE key=?", (key,)).fetchone()[0])
        for case in ("parent", "unknown", "null", "legacy", "control"):
            with self.subTest(case=case):
                with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
                    timing.execute("UPDATE turns SET baseline=? WHERE key=?", (
                        json.dumps(baseline_role_case(baseline, case)), key))
                if case in ("legacy", "control"):
                    result = preview(self.data, child, turn, output_dir=self.output, home=self.root)
                    self.assertEqual(result["status"], "preview")
                    path = Path(json.loads(result["reference"].split("\ue202")[1][:-1])["path"])
                    self.assertIn('data-metric="turn-delta">+50</dd>', path.read_text())
                else:
                    self.assertEqual(preview(self.data, child, turn,
                        output_dir=self.output, home=self.root)["status"], "source_unavailable")
                    self.assert_child_identity_unavailable(child, turn)

    def test_child_preview_rejects_changed_direct_parent_before_reading_usage(self):
        child, _, turn, transcript = self.nested_child()
        source = {"subagent": {"thread_spawn": {"parent_thread_id": TASK}}}
        self.db.execute("UPDATE threads SET source=? WHERE id=?", (json.dumps(source), child))
        self.db.commit()
        rows = [json.loads(row) for row in transcript.read_text().splitlines()]
        rows[0]["payload"]["source"] = source
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.assert_child_identity_unavailable(child, turn)

    def test_child_preview_rejects_role_change_to_root_with_foreign_usage_and_settings(self):
        child, _, turn, transcript = self.nested_child()
        self.db.execute("UPDATE threads SET source='vscode' WHERE id=?", (child,))
        self.db.commit()
        rows = [json.loads(row) for row in transcript.read_text().splitlines()]
        rows[0]["payload"]["source"] = "vscode"
        rows.extend((
            {"type": "turn_context", "payload": {
                "turn_id": turn, "model": "synthetic-foreign-root-model", "effort": "low"
            }},
            counter(98700),
        ))
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = preview(self.data, child, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertFalse(self.output.exists())
        self.assert_child_identity_unavailable(child, turn)

    def test_root_preview_rejects_role_change_to_child(self):
        other_root = "00000000-0000-7000-8000-000000000004"
        source = {"subagent": {"thread_spawn": {"parent_thread_id": other_root}}}
        self.db.execute("INSERT INTO threads VALUES (?, ?, NULL, NULL, NULL, 'vscode', NULL, ?)",
                        (other_root, "synthetic other root", str(self.workspace)))
        self.db.execute("UPDATE threads SET source=? WHERE id=?", (json.dumps(source), TASK))
        self.db.commit()
        rows = [json.loads(row) for row in self.transcript.read_text().splitlines()]
        rows[0]["payload"]["source"] = source
        self.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.assertEqual(self.preview()["status"], "source_unavailable")
        self.assert_child_identity_unavailable(TASK, "turn-1")

    def assert_child_identity_unavailable(self, child, turn):
        with patch("codex_run_budget.auto_preview.snapshot") as observed, patch(
            "codex_run_budget.auto_preview.collect"
        ) as children, patch("codex_run_budget.turn_quota.observe") as quota, patch(
            "codex_run_budget.auto_preview.render_card"
        ) as renderer:
            result = preview(self.data, child, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "source_unavailable")
        observed.assert_not_called()
        children.assert_not_called()
        quota.assert_not_called()
        renderer.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_inline_reference_real_snapshot_escaped_private_and_no_state_change(self):
        before = recent(self.data)
        result = self.preview()
        self.assertEqual(result["status"], "preview")
        self.assertLess(len(json.dumps(result)), 700)
        target = next(self.output.glob("*.html"))
        self.assertEqual(
            result["reference"],
            '\ue200visualize\ue202{"path":'
            + json.dumps(str(target), ensure_ascii=False) + '}\ue201'
        )
        content = target.read_text()
        for expected in ("500", "450", "400", "50", "25", "gpt-6-astra", "xhigh"):
            self.assertIn(expected, content)
        self.assertIn('data-metric="task-total">1,500</dd>', content)
        self.assertIn('data-metric="turn-delta">+500</dd>', content)
        self.assertNotIn("Fast", content)
        self.assertIn("改善 &lt;報告&gt; $total", content)
        for forbidden in (TASK, "secret-source", "<!doctype", "<html", "<script", "fetch("):
            self.assertNotIn(forbidden, content)
        self.assertEqual(recent(self.data), before)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        handle({**self.payload, "hook_event_name": "Stop"}, self.data)
        self.assertEqual(target.read_text(), content)
        self.assertEqual(recent(self.data)[0]["state"], "reported")

    def test_disable_and_threshold_avoid_preview_side_effects(self):
        configure(self.data, enabled=False)
        self.assertEqual(self.preview()["status"], "disabled")
        configure(self.data, enabled=True, threshold_seconds=300)
        self.assertEqual(self.preview()["status"], "below_threshold")
        self.assertFalse(self.output.exists())

    def test_wrong_turn_source_and_subagent_do_not_leak_another_task(self):
        self.assertEqual(preview(self.data, TASK, "other", output_dir=self.output,
                                 home=self.root)["status"], "no_active_start")
        self.transcript.write_text('{}\n')
        self.assertEqual(self.preview()["status"], "source_unavailable")
        self.db.execute("UPDATE threads SET source=?", (json.dumps({"subagent": {}}),))
        self.db.commit()
        self.assertEqual(self.preview()["status"], "subagent")
        self.assertFalse(self.output.exists())

    def test_missing_counter_is_not_zero_and_symlink_output_is_rejected(self):
        self.transcript.write_text(json.dumps(self.meta) + "\n")
        self.preview()
        card = next(self.output.glob("*.html")).read_text()
        self.assertIn('data-metric="task-total">未觀測</dd>', card)
        self.assertIn('data-metric="turn-delta">未觀測</dd>', card)
        link = self.root / "link"
        link.symlink_to(self.output)
        with self.assertRaises(ValueError):
            preview(self.data, TASK, "turn-1", output_dir=link, home=self.root)

    def test_desktop_readable_root_required_before_quota_or_child_collection(self):
        outside = (
            self.root / ".local/state/example/reports",
            self.root / "workspace-other/reports",
            self.root / "visualizations/1970/01/01/00000000-0000-7000-8000-000000000002",
            self.root / "visualizations/1970/01/02" / TASK,
            self.workspace / ".." / "private-reports",
            Path("relative/reports"),
        )
        with patch("codex_run_budget.turn_quota.observe") as quota, patch(
            "codex_run_budget.auto_preview.collect"
        ) as children:
            for directory in outside:
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    preview(self.data, TASK, "turn-1", output_dir=directory, home=self.root)
                self.assertFalse(directory.exists())
            quota.assert_not_called()
            children.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_native_visualization_root_uses_task_uuid_utc_date(self):
        directory = self.root / "visualizations/1970/01/01" / TASK
        self.db.execute("UPDATE threads SET cwd=NULL")
        self.db.commit()
        result = preview(self.data, TASK, "turn-1", output_dir=directory, home=self.root)
        target = next(directory.glob("*.html"))
        reference = json.loads(result["reference"].split("\ue202")[1][:-1])
        self.assertEqual(reference, {"path": str(target)})
        self.assertRegex(target.name, r"^[a-z0-9]+(?:-[a-z0-9]+)*\.html$")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.preview()

    def test_symlink_ancestor_does_not_authorize_an_external_directory(self):
        self.workspace.mkdir()
        (self.workspace / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            preview(self.data, TASK, "turn-1", output_dir=self.workspace / "alias/reports",
                    home=self.root)
        self.assertFalse((self.root / "reports").exists())

    def test_path_is_rechecked_after_collection(self):
        self.workspace.mkdir()
        with patch("codex_run_budget.turn_quota.observe", side_effect=lambda *a, **k:
                   self.output.symlink_to(self.root, target_is_directory=True)):
            with self.assertRaises(ValueError):
                self.preview()
        self.assertFalse(list(self.root.glob("*.html")))

    def test_incomplete_scope_is_not_promoted_to_complete_or_zero(self):
        zero = {key: 0 for key in ("total", "input", "cached_input", "output", "reasoning_output")}
        self.assertEqual(observed_total(None, {"status": "none", "usage": zero}), (None, False))
        for status in ("observed", "partial", "unavailable"):
            self.assertEqual(observed_total(None, {"status": status, "usage": zero}), (None, False))
        for issue in ("pending_agents", "missing_agents", "selection_limited"):
            self.assertFalse(observed_total(zero, {"status": "observed", "usage": zero,
                                                  issue: 1})[1])

    def test_first_turn_pending_preview_and_separate_stop_settlement(self):
        turn = "fresh-turn"
        self.transcript.write_text("".join(json.dumps(row) + "\n" for row in (
            self.meta,
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}},
            {"type": "turn_context", "payload": {"turn_id": turn}},
        )))
        payload = {**self.payload, "turn_id": turn}
        handle(payload, self.data)
        result = preview(self.data, TASK, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "preview")
        card_path = next(self.output.glob("*.html"))
        card = card_path.read_text()
        self.assertIn('data-metric="task-total">未觀測</dd>', card)
        self.assertIn('data-metric="turn-delta">等待用量寫入</dd>', card)
        self.assertIn("首筆請求用量尚未寫入", card)
        self.assertNotIn('data-metric="turn-delta">0</dd>', card)
        with self.transcript.open("a") as output:
            output.write(json.dumps(counter(1200)) + "\n")
        handle({**payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertEqual(receipt["usage"]["total"], 1200)
        self.assertEqual(receipt["usage_status"], "verified_first_turn_counter")
        self.assertEqual(card_path.read_text(), card)

    def test_first_request_is_visible_inline_before_cumulative_event(self):
        turn = "fresh-request-turn"
        self.transcript.write_text("".join(json.dumps(row) + "\n" for row in (
            self.meta,
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}},
            {"type": "turn_context", "payload": {"turn_id": turn}},
        )))
        payload = {**self.payload, "turn_id": turn}
        handle(payload, self.data)
        with self.transcript.open("a") as output:
            output.write(json.dumps(native_counter(TASK, turn, 1200)) + "\n")
        result = preview(self.data, TASK, turn, output_dir=self.output, home=self.root)
        self.assertEqual(result["status"], "preview")
        card_path = next(self.output.glob("*.html"))
        card = card_path.read_text()
        self.assertIn('data-metric="task-total">1,200</dd>', card)
        self.assertIn('data-metric="turn-delta">+1,200</dd>', card)
        self.assertNotIn("等待用量寫入", card)
        with self.transcript.open("a") as output:
            output.write(json.dumps(native_counter(TASK, turn, 1500,
                                                   request=300, turn_total=1500)) + "\n")
            output.write(json.dumps(counter(1500)) + "\n")
        handle({**payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertEqual(receipt["usage"]["total"], 1500)
        self.assertEqual(card_path.read_text(), card)

    def test_child_stop_and_final_card_merge_without_model_self_report(self):
        child = "aaaaaaaa-1234-1234-1234-123456789abc"
        source = {"subagent": {"thread_spawn": {"parent_thread_id": TASK}}}
        transcript = self.root / "private-child.jsonl"
        stamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        request = {"type": "token_usage_record", "timestamp": stamp, "payload": {
            "thread_id": child, "turn_id": "child-turn", "response_id": "private-response",
            "usage": {"total_tokens": 200, "input_tokens": 180, "output_tokens": 20,
                      "cached_input_tokens": 100, "reasoning_output_tokens": 10},
        }}
        records = [
            {"type": "session_meta", "timestamp": stamp, "payload": {
                "id": child, "source": source}}, request,
            {"type": "event_msg", "timestamp": stamp, "payload": {
                "type": "task_complete", "turn_id": "child-turn"}},
        ]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in records))
        self.db.execute("INSERT INTO threads VALUES (?, ?, ?, NULL, NULL, ?, ?, NULL)",
                        (child, None, '<測試代理> $total', json.dumps(source), str(transcript)))
        self.db.commit()
        child_stop = {"session_id": TASK, "turn_id": "child-turn", "agent_id": child,
                      "hook_event_name": "SubagentStop", "agent_transcript_path": str(transcript)}
        self.assertIsNone(handle(child_stop, self.data, home=self.root))
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        result = self.preview()
        self.assertEqual(result["status"], "preview")
        card = next(self.output.glob("*.html")).read_text()
        for expected in ("700", "500", "200", "&lt;測試代理&gt; $total", "改善 &lt;報告&gt;"):
            self.assertIn(expected, card)
        self.assertIn('data-metric="task-total">1,500</dd>', card)
        self.assertIn('data-metric="turn-delta">+500</dd>', card)
        self.assertNotIn('data-metric="turn-delta">+700</dd>', card)
        for private in (child, "private-child", "private-response"):
            self.assertNotIn(private, card)
        handle({**self.payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertTrue(receipt["subagents_included"])
        self.assertEqual(receipt["subagents"]["usage"]["total"], 200)
        self.assertEqual(receipt["usage"]["total"], 500)
        self.assertEqual(next(self.output.glob("*.html")).read_text(), card)

    def test_native_child_start_preview_matches_same_name_rows_in_root_card(self):
        child = "00000000-0000-7000-8000-000000000002"
        sibling = "00000000-0000-7000-8000-000000000003"
        child_turn = "synthetic-child-turn"
        sibling_turn = "synthetic-sibling-turn"
        source = {"subagent": {"thread_spawn": {"parent_thread_id": TASK}}}
        stamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        child_page = self.root / "synthetic-child.jsonl"
        sibling_page = self.root / "synthetic-sibling.jsonl"
        child_page.write_text("".join(json.dumps(row) + "\n" for row in (
            {"type": "session_meta", "timestamp": stamp,
             "payload": {"id": child, "source": source}},
            counter(100),
        )))
        sibling_page.write_text("".join(json.dumps(row) + "\n" for row in (
            {"type": "session_meta", "timestamp": stamp,
             "payload": {"id": sibling, "source": source}},
            {"type": "token_usage_record", "timestamp": stamp, "payload": {
                "thread_id": sibling, "session_id": TASK,
                "turn_id": sibling_turn, "root_turn_id": "turn-1",
                "response_id": "synthetic-sibling-response", "usage": {
                    "total_tokens": 70, "input_tokens": 60, "output_tokens": 10,
                    "cached_input_tokens": 30, "reasoning_output_tokens": 5,
                },
            }},
            {"type": "event_msg", "timestamp": stamp,
             "payload": {"type": "task_complete", "turn_id": sibling_turn}},
        )))
        unsafe_name = "same <worker> [bad](https://example.invalid)"
        self.db.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (child, unsafe_name, "worker", "worker", "/root/worker",
                 json.dumps(source), str(child_page), str(self.workspace)),
                (sibling, unsafe_name, "worker", "worker", "/root/worker",
                 json.dumps(source), str(sibling_page), str(self.workspace)),
            ),
        )
        self.db.commit()
        child_payload = {
            "session_id": TASK, "agent_id": child, "turn_id": child_turn,
            "hook_event_name": "SubagentStart", "transcript_path": str(child_page),
        }
        start = handle(child_payload, self.data, home=self.root)
        self.assertEqual(set(start), {"hookSpecificOutput"})
        self.assertIn("--preview " + child, start["hookSpecificOutput"]["additionalContext"])
        native = native_counter(child, child_turn, 300, request=200, turn_total=200)
        native["timestamp"] = stamp
        native["payload"].update(session_id=TASK, root_turn_id="turn-1",
                                 response_id="synthetic-child-response")
        with child_page.open("a") as output:
            output.write("".join(json.dumps(row) + "\n" for row in (
                {"type": "turn_context", "payload": {
                    "turn_id": child_turn, "model": "gpt-6-sol", "effort": "high"
                }},
                native,
                counter(300),
            )))

        own = preview(self.data, child, child_turn, output_dir=self.output, home=self.root)
        self.assertEqual(own["status"], "preview")
        own_path = Path(json.loads(own["reference"].split("\ue202")[1][:-1])["path"])
        own_card = own_path.read_text()
        child_selector = "@" + stable_hash(child)[:12]
        sibling_selector = "@" + stable_hash(sibling)[:12]
        self.assertIn(child_selector, own_card)
        self.assertNotIn(sibling_selector, own_card)
        self.assertIn("same &lt;worker&gt;", own_card)
        self.assertIn("由 改善 &lt;報告&gt; $total 派生", own_card)
        self.assertIn("本輪增加 Token（此子代理）", own_card)
        self.assertIn("本輪此子代理設定", own_card)
        self.assertNotIn("主代理", own_card)
        self.assertIn('data-metric="task-total">300</dd>', own_card)
        self.assertIn('data-metric="turn-delta">+200</dd>', own_card)
        root_visuals = self.root / "visualizations/1970/01/01" / TASK
        shared = preview(self.data, child, child_turn, output_dir=root_visuals, home=self.root)
        self.assertEqual(shared["status"], "preview")
        shared_path = Path(json.loads(shared["reference"].split("\ue202")[1][:-1])["path"])
        self.assertEqual(shared_path.parent, root_visuals.parent / child)
        self.assertFalse(root_visuals.exists())

        parent = self.preview()
        self.assertEqual(parent["status"], "preview")
        parent_path = Path(json.loads(parent["reference"].split("\ue202")[1][:-1])["path"])
        parent_card = parent_path.read_text()
        self.assertIn(child_selector, parent_card)
        self.assertIn(sibling_selector, parent_card)
        self.assertIn('data-metric="turn-delta">+500</dd>', parent_card)
        self.assertIn("Task 累積 Token（主代理）", parent_card)
        self.assertIn("本輪增加 Token（主代理）", parent_card)
        self.assertIn("本輪主代理設定", parent_card)
        self.assertNotIn('data-metric="turn-delta">+770</dd>', parent_card)
        self.assertNotIn(child, parent_card)
        self.assertNotIn(sibling, parent_card)

        stop = handle({**child_payload, "hook_event_name": "SubagentStop",
                       "transcript_path": str(self.transcript),
                       "agent_transcript_path": str(child_page)}, self.data, home=self.root)
        self.assertEqual(set(stop), {"systemMessage"})
        handle({**self.payload, "hook_event_name": "Stop"}, self.data, home=self.root)
        receipts = [json.loads(path.read_text())
                    for path in (self.data / "auto-reports").glob("*.json")]
        self.assertEqual(len(receipts), 2)
        by_task = {receipt["task_hash"]: receipt for receipt in receipts}
        self.assertEqual(by_task[stable_hash(child)]["task"]["selector"], child_selector[1:])
        self.assertEqual(by_task[stable_hash(child)]["usage"]["total"], 200)
        root = by_task[stable_hash(TASK)]
        self.assertEqual(root["usage"]["total"], 500)
        self.assertEqual(root["subagents"]["usage"]["total"], 270)
        self.assertEqual(root["subagents"]["request_count"], 2)
        parent_markdown = (self.data / "auto-reports" / (
            stable_hash([TASK, "turn-1"]) + ".md"
        )).read_text()
        self.assertIn("&#91;bad&#93;", parent_markdown)
        self.assertNotIn("[bad](https://example.invalid)", parent_markdown)

    def test_card_preserves_paired_turn_switches_and_does_not_render_fast(self):
        contexts = [
            {"model": "example-a", "reasoning_effort": "low", "fast_mode": True},
            {"model": "example-b", "reasoning_effort": "high", "fast_mode": False},
            {"model": "example-a", "reasoning_effort": "low", "fast_mode": None},
        ]
        zero = dict.fromkeys(("total", "input", "cached_input", "output", "reasoning_output"), 0)
        current = {"task_hash": stable_hash(TASK), "usage": {**zero, "total": 1500},
                   "contexts": contexts, "contexts_limited": True}
        with patch("codex_run_budget.auto_preview.snapshot", return_value=current), patch(
            "codex_run_budget.auto_preview._delta", return_value=({**zero, "total": 500}, "test")
        ), patch("codex_run_budget.auto_preview.render_card", wraps=render_card) as renderer:
            self.preview()
        self.assertEqual(renderer.call_args.args[0]["task_usage"], {**zero, "total": 1500})
        self.assertTrue(renderer.call_args.args[0]["contexts_limited"])
        card = next(self.output.glob("*.html")).read_text()
        ordered = (
            '<ol class="report-context-list"><li>example-a · 思考 low</li>'
            '<li>example-b · 思考 high</li><li>example-a · 思考 low</li></ol>'
        )
        self.assertIn(ordered, card)
        self.assertIn("切換紀錄可能不完整", card)
        self.assertNotIn("Fast", card)

    def test_legacy_card_missing_task_total_and_empty_context_remain_unknown(self):
        receipt = {
            "key": "example", "task_name": "Example task", "locale": "zh-Hant",
            "usage": {key: 0 for key in (
                "total", "input", "cached_input", "output", "reasoning_output"
            )}, "contexts": [], "elapsed_seconds": 0, "captured_at": "12:00:00 UTC",
            "subagents": {"status": "none"},
        }
        card = render_card(receipt)
        self.assertIn('data-metric="task-total">未觀測</dd>', card)
        self.assertIn('data-metric="turn-delta">0</dd>', card)
        self.assertIn('<p class="report-context-single">未觀測</p>', card)
        self.assertNotIn("Fast", card)

    def test_child_and_root_card_scopes_are_localized_in_all_nine_languages(self):
        receipt = {
            "key": "synthetic", "task_name": "Synthetic example", "usage": None,
            "contexts": [], "elapsed_seconds": 0, "captured_at": "12:00:00 UTC",
            "subagents": {"status": "none"},
        }
        labels = {
            "parent": "own_agent", "combined": "child_combined",
            "task_total": "child_task_total", "turn_delta": "child_turn_delta",
            "context_heading": "child_context_heading",
            "child_subtotal": "child_descendant_subtotal", "card_note": "child_card_note",
        }
        for locale in LOCALES:
            with self.subTest(locale=locale):
                text = ReportText(locale)
                root = render_card({**receipt, "locale": locale, "scope": "parent"})
                for scope in ("subagent", "subagent_turn_stop_boundary"):
                    child = render_card({**receipt, "locale": locale, "scope": scope})
                    for root_key, child_key in labels.items():
                        self.assertIn(escape(text(root_key)), root)
                        self.assertIn(escape(text(child_key)), child)
                        if root_key != "parent":
                            self.assertNotIn(escape(text(root_key)), child)

    def test_old_task_counter_without_this_turn_write_is_pending_not_zero(self):
        lines = self.transcript.read_text().splitlines()
        self.transcript.write_text("\n".join(lines[:-1]) + "\n")
        self.preview()
        card = next(self.output.glob("*.html")).read_text()
        self.assertIn('data-metric="task-total">1,000</dd>', card)
        self.assertIn('data-metric="turn-delta">等待用量寫入</dd>', card)
        self.assertNotIn('data-metric="turn-delta">0</dd>', card)

    def test_quota_read_stays_in_one_preview_and_stop_reuses_same_capture(self):
        from test_turn_quota import source

        with patch("codex_run_budget.turn_quota.read_meter_sources",
                   return_value=source()) as reader:
            self.preview()
            card = next(self.output.glob("*.html")).read_text()
            self.assertIn("80%", card)
            self.assertIn("Pro", card)
            handle({**self.payload, "hook_event_name": "Stop"}, self.data, home=self.root)
            reader.assert_called_once()
        receipt = json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())
        self.assertEqual(receipt["quota"]["rows"][0]["remaining_percent"], 80)
        self.assertFalse(receipt["native_quota_refreshed"])
        self.assertEqual(next(self.output.glob("*.html")).read_text(), card)

    def test_disabled_child_capture_and_governor_decision_are_preserved(self):
        event = {**self.payload, "hook_event_name": "SubagentStop", "agent_id": "child"}
        configure(self.data, enabled=False)
        with patch("codex_run_budget.child_usage.capture") as capture:
            self.assertIsNone(handle(event, self.data, home=self.root))
            capture.assert_not_called()
        configure(self.data, enabled=True)
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        budget = {"continue": False, "stopReason": "HALT", "systemMessage": "HALT"}
        with patch.object(governor, "_handle_budget", return_value=budget), patch(
            "codex_run_budget.child_usage.capture"
        ) as capture:
            self.assertEqual(governor.handle(event), budget)
            capture.assert_called_once()


if __name__ == "__main__":
    unittest.main()
