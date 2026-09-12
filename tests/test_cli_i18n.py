from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.cli import _status_summary, main  # noqa: E402
from codex_run_budget.report_i18n import LOCALES, ReportText  # noqa: E402
from codex_run_budget.workflow import render  # noqa: E402
from codex_run_budget.workflow import run as workflow_run  # noqa: E402


class CliI18nTest(unittest.TestCase):
    def test_catalogs_have_same_keys_and_placeholders(self):
        base = ReportText("en", domain="cli").values
        for locale in LOCALES:
            values = ReportText(locale, domain="cli").values
            self.assertEqual(values.keys(), base.keys(), locale)
            for key in base:
                expected = sorted(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", base[key]))
                actual = sorted(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", values[key]))
                self.assertEqual(actual, expected, f"{locale}:{key}")

    def test_help_resolves_codex_language_only_for_help(self):
        localized = ReportText("de", domain="cli")
        output = io.StringIO()
        with patch("codex_run_budget.cli.human_text", return_value=localized):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as raised:
                    main(["workflow", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("vorheriger Beobachtungscursor", output.getvalue())
        self.assertIn("vollständige strukturierte Beobachtung", output.getvalue())

    def test_machine_route_does_not_resolve_host_locale(self):
        with patch(
            "codex_run_budget.cli.human_text", side_effect=AssertionError("locale read")
        ), patch("codex_run_budget.report_i18n._catalog", side_effect=AssertionError("catalog")):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["meter", "rates"]), 0)
        self.assertIn('"models"', output.getvalue())

    def test_meter_json_does_not_build_discarded_human_summary(self):
        for action in ("tasks", "estimate", "report", "history"):
            with tempfile.TemporaryDirectory() as directory, patch(
                "codex_run_budget.report_i18n._catalog", side_effect=AssertionError("catalog")
            ), patch("codex_run_budget.report_i18n.resolve_locale",
                     side_effect=AssertionError("locale read")):
                output = io.StringIO()
                arguments = ["--data-dir", directory, "meter", action, "--json"]
                if action != "history":
                    arguments += ["--directory", directory]
                with redirect_stdout(output):
                    self.assertEqual(main(arguments), 0, action)
                self.assertTrue(output.getvalue().strip().startswith(("{", "[")), action)

    def test_status_summary_localizes_human_fields_but_keeps_values(self):
        run = {
            "status": "running",
            "epoch": 2,
            "spent_tokens": 12345,
            "max_tokens": 20000,
            "tool_calls": 3,
            "max_tool_calls": 8,
            "active_agents": 1,
            "max_agents": 2,
            "pending_agents": 1,
            "usage_status": "observed",
            "usage_issues": ["sample_issue"],
        }
        de = _status_summary(run, ReportText("de", domain="cli"))
        self.assertIn("Run Budget", de)
        self.assertIn("12.345", de)
        self.assertIn("beobachtete Tokens", de)
        self.assertIn("sample_issue", de)
        self.assertNotIn("12345", de)

    def test_workflow_markdown_uses_catalog_but_native_name_and_cursor_stay_intact(self):
        result = {
            "tasks": [
                {
                    "thread_hash": "a" * 64,
                    "display_name": "Native Task 名稱",
                    "parent_name": None,
                    "root_name": None,
                    "observation": {
                        "lifecycle": {"kind": "task_complete"},
                        "source_status": "observed",
                    },
                }
            ],
            "selection_limited": False,
            "observed_token_delta": 1234,
            "comparable_tasks": 1,
            "scan_bytes": 2048,
            "model_requests": 0,
            "signals": [],
        }
        output = render(result, text=ReportText("ja", domain="cli"))
        self.assertIn("Workflow 観察", output)
        self.assertIn("Native Task 名稱", output)
        self.assertIn("1,234", output)
        self.assertNotIn("a" * 64, output)

    @staticmethod
    def _workflow_result(*, changed):
        return {
            "schema_version": 1,
            "scope": "s" * 64,
            "captured_at": 1100,
            "baseline_at": None,
            "tasks": [
                {
                    "thread_hash": "a" * 64,
                    "display_name": "Native Task 名稱",
                    "parent_name": None,
                    "root_name": None,
                    "observation": {
                        "lifecycle": {"kind": "task_complete"},
                        "source_status": "observed",
                    },
                }
            ],
            "selection_limited": False,
            "changes": [],
            "removed_from_selection": [],
            "signals": [],
            "new_signals": [],
            "cleared_signals": [],
            "changed": changed,
            "consecutive_unchanged": 0,
            "observed_token_delta": None,
            "comparable_tasks": 0,
            "selected_tasks": 1,
            "scan_bytes": 1,
            "model_requests": 0,
            "live_status": "not_queried",
            "workflow_acceptance": "not_evaluated",
            "cursor": "b" * 64,
        }

    def test_workflow_json_changed_keeps_report_artifact_without_translating_json(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            data = Path(directory) / "data"
            data.joinpath("workflow-observations").mkdir(parents=True)
            args = SimpleNamespace(
                action="observe",
                thread=["selector"],
                include_agents=False,
                limit=8,
                after=None,
                codex_home=Path(directory) / "home",
                data_dir=data,
                json=True,
            )
            output = io.StringIO()
            with (
                patch(
                    "codex_run_budget.workflow.WorkflowObserver.capture",
                    return_value=self._workflow_result(changed=True),
                ),
                patch(
                    "codex_run_budget.workflow.human_text",
                    return_value=ReportText("ja", domain="cli"),
                ) as resolve,
                redirect_stdout(output),
            ):
                workflow_run(args)
            payload = json.loads(output.getvalue())
            report = Path(payload["report_path"])
            self.assertTrue(report.is_file())
            self.assertEqual(resolve.call_count, 1)
            self.assertIn("Workflow 観察", report.read_text())
            self.assertNotIn("Workflow 観察", output.getvalue())

    def test_workflow_json_unchanged_and_targets_skip_locale_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = str(Path(directory).resolve())
            data = Path(directory) / "data"
            common = dict(
                thread=["selector"],
                include_agents=False,
                limit=8,
                after=None,
                codex_home=Path(directory) / "home",
                data_dir=data,
            )
            unchanged = SimpleNamespace(action="observe", json=True, **common)
            with (
                patch(
                    "codex_run_budget.workflow.WorkflowObserver.capture",
                    return_value=self._workflow_result(changed=False),
                ),
                patch(
                    "codex_run_budget.workflow.human_text",
                    side_effect=AssertionError("locale read"),
                ),
                redirect_stdout(io.StringIO()),
            ):
                workflow_run(unchanged)
            human_unchanged = SimpleNamespace(action="observe", json=False, **common)
            human_output = io.StringIO()
            labels = ReportText("fr", domain="cli")
            with (
                patch("codex_run_budget.workflow.WorkflowObserver.capture",
                      return_value=self._workflow_result(changed=False)),
                patch("codex_run_budget.workflow.human_text", return_value=labels) as resolve,
                redirect_stdout(human_output),
            ):
                workflow_run(human_unchanged)
            resolve.assert_called_once()
            self.assertIn(labels("workflow_unchanged"), human_output.getvalue())
            targets = SimpleNamespace(action="targets", json=False, **common)
            with (
                patch(
                    "codex_run_budget.workflow.WorkflowObserver.select",
                    return_value=("s" * 64, [{"display_name": "Native"}], {"child": "path"}, False),
                ),
                patch(
                    "codex_run_budget.workflow.human_text",
                    side_effect=AssertionError("locale read"),
                ),
                redirect_stdout(io.StringIO()),
            ):
                workflow_run(targets)

    def test_json_report_error_does_not_echo_private_argument(self):
        secret = "PRIVATE/secret-argument"
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(stderr):
            self.assertEqual(main(["--data-dir", directory, "show", secret]), 2)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertIn("run-budget", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
