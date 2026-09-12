from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))
from codex_run_budget.cli import main  # noqa: E402
from codex_run_budget.report import build_report, render_report  # noqa: E402
from codex_run_budget.task_catalog import TaskCatalog, task_description  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402
from test_report import TASK_A, TASK_B, event, request  # noqa: E402

TASK_C = "32345678-1234-1234-1234-123456789abc"


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / "state_5.sqlite"
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY,name TEXT,title TEXT,"
            "agent_nickname TEXT,agent_role TEXT,agent_path TEXT,source TEXT,updated_at INT)"
        )
        for identifier, name, parent, nickname, number in (
            (TASK_A, "改善報告", None, None, 1),
            (TASK_B, None, TASK_A, "Curie", 2),
            (TASK_C, None, TASK_B, "Erdos", 3),
        ):
            source = (
                json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": parent}}})
                if parent
                else "vscode"
            )
            connection.execute(
                "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    name,
                    "PRIVATE PROMPT FALLBACK",
                    nickname,
                    "worker" if parent else None,
                    "/root/helper" if parent else None,
                    source,
                    number,
                ),
            )
        connection.commit()
        connection.close()
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        for identifier, parent in ((TASK_A, None), (TASK_B, TASK_A), (TASK_C, TASK_B)):
            page = self.sessions / f"rollout-2026-01-01-{identifier}.jsonl"
            metadata = {"id": identifier}
            if parent:
                metadata["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
            page.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        event(999000, "session_meta", metadata),
                        event(999001, "turn_context", {"model": "gpt-6-astra", "turn_id": "t"}),
                        request(999900, identifier),
                    )
                )
                + "\n"
            )
            os.utime(page, (1000000, 1000000))

    def test_native_name_not_prompt_fallback_and_nested_ownership(self):
        before = self.db.read_bytes()
        with TaskCatalog(self.root) as catalog:
            root = catalog.get(TASK_A)
            self.assertEqual(root["display_name"], "改善報告")
            leaf = catalog.describe(catalog.get(stable_hash(TASK_C)[:12]))
            self.assertEqual(leaf["root_name"], "改善報告")
            self.assertEqual(leaf["parent_name"], "Curie / helper")
            self.assertEqual(leaf["parent_hash"], stable_hash(TASK_B))
            self.assertEqual(len(catalog.family(root)), 3)
        self.assertNotIn("PRIVATE PROMPT", json.dumps(leaf))
        self.assertNotIn(TASK_A, json.dumps(leaf))
        self.assertEqual(self.db.read_bytes(), before)

    def test_unknown_schema_missing_parent_cycles_and_limits(self):
        with TaskCatalog(self.root) as catalog:
            self.assertEqual(len(catalog.family(catalog.get(TASK_A), 2)), 2)
            self.assertTrue(catalog.limited)
        connection = sqlite3.connect(self.db)
        connection.execute(
            "UPDATE threads SET source=? WHERE id=?",
            (
                json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": TASK_C}}}),
                TASK_A,
            ),
        )
        connection.commit()
        connection.close()
        self.assertEqual(
            task_description(TASK_C, self.root)["lineage_status"], "cycle_or_depth_limit"
        )
        self.assertIsNone(task_description(TASK_A, self.root / "missing"))
        self.assertIsNone(task_description("bad", self.root))

    def test_scope_filters_before_audit_and_names_render_safely(self):
        with TaskCatalog(self.root) as catalog:
            metadata = {stable_hash(TASK_C): catalog.describe(catalog.get(TASK_C))}
        report = build_report(
            sessions=self.sessions, thread_ids=[TASK_C], now=1000000, task_metadata=metadata
        )
        self.assertEqual(report["coverage"]["selection"]["selected_files"], 1)
        self.assertEqual(report["windows"][0]["usage"]["total_tokens"], 1000)
        self.assertIn("Curie", render_report(report))
        self.assertIn("改善報告", render_report(report, "html"))
        report["task_catalog"][stable_hash(TASK_C)]["display_name"] = "<script>x</script>[bad](x)"
        self.assertNotIn("<script>x", render_report(report, "html"))
        self.assertNotIn("[bad](x)", render_report(report))
        with self.assertRaises(ValueError):
            build_report(sessions=self.sessions, now=1000000)

    def test_menu_and_agents_do_not_audit_and_default_artifact_is_compact(self):
        with (
            patch("codex_run_budget.report.survey_transcripts", side_effect=AssertionError),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(["report"]), 0)
            self.assertLess(len(output.getvalue()), 1200)
            self.assertEqual(
                main(["report", "agents", "--thread", TASK_A, "--codex-home", str(self.root)]), 0
            )
        artifact = self.root / "named.md"
        with (
            patch("codex_run_budget.report.time.time", return_value=1000000),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = main(
                [
                    "report",
                    "task",
                    "--thread",
                    TASK_C,
                    "--codex-home",
                    str(self.root),
                    "--directory",
                    str(self.sessions),
                    "--output",
                    str(artifact),
                ]
            )
        self.assertEqual(result, 0)
        self.assertLess(len(output.getvalue()), 900)
        self.assertIn("改善報告", artifact.read_text())
        self.assertIn("Erdos", output.getvalue())
        self.assertNotIn("私人", artifact.read_text())
        with (
            redirect_stderr(io.StringIO()),
            redirect_stdout(io.StringIO()),
            patch.dict(os.environ, {"CODEX_THREAD_ID": ""}),
        ):
            self.assertEqual(main(["report", "task"]), 2)
            self.assertEqual(main(["report", "window", "--all-tasks"]), 2)


if __name__ == "__main__":
    unittest.main()
