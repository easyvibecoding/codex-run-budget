from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from time import sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-run-budget/lib"))

from codex_run_budget.auto_report import (  # noqa: E402
    SCAN_BYTES,
    _documents,
    configure,
    handle,
    observed_total,
    recent,
    settings,
    snapshot,
)
from codex_run_budget.governor import Governor  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402


def counter(total):
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "total_tokens": total,
                    "input_tokens": total * 9 // 10,
                    "cached_input_tokens": total * 8 // 10,
                    "output_tokens": total // 10,
                    "reasoning_output_tokens": total // 20,
                }
            },
        },
    }


def native_counter(task, turn, total, *, request=None, turn_total=None):
    def usage(value):
        return counter(value)["payload"]["info"]["total_token_usage"]
    return {"type": "token_usage_record", "payload": {
        "thread_id": task, "session_id": task, "turn_id": turn, "root_turn_id": turn,
        "response_id": "example-response", "usage": usage(request or total),
        "turn_token_usage": usage(turn_total or total), "thread_token_usage": usage(total),
    }}


def baseline_role_case(baseline, case):
    result = dict(baseline)
    if case in ("legacy", "no-evidence"):
        result.pop("source_role", None)
        if case == "no-evidence":
            for key in ("start_event", "root_hash", "parent_hash"):
                result.pop(key, None)
    elif case != "control":
        result["source_role"] = {"parent": "parent", "unknown": "synthetic-unknown-role",
                                 "null": None}[case]
    return result


def synthetic_descendant_subtotal():
    return {"status": "observed", "usage": {"total": 90000, "input": 81000,
            "cached_input": 72000, "output": 9000, "reasoning_output": 4500},
            "agents_seen": 1, "agents_with_usage": 1, "request_count": 1, "rows": []}


class AutoReportTest(unittest.TestCase):
    def setUp(self):
        locale = patch("codex_run_budget.auto_report.resolve_locale",
                       return_value={"locale": "zh-Hant", "locale_source": "test"})
        locale.start()
        self.addCleanup(locale.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.page = self.root / "private-source.jsonl"
        self.meta = {"type": "session_meta", "payload": {"id": "private-session-id"}}
        self.page.write_text(json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n")
        self.payload = {
            "session_id": "private-session-id",
            "turn_id": "private-turn-id",
            "transcript_path": str(self.page),
            "model": "gpt-6-astra",
            "prompt": "DO NOT EXPORT PRIVATE PROMPT",
        }

    def event(self, event, seconds=0, **extra):
        return handle(
            {**self.payload, "hook_event_name": event, **extra},
            self.data,
            wall=1000000 + seconds,
            monotonic=5000 + seconds,
        )

    def start(self, threshold=0):
        configure(self.data, enabled=True, threshold_seconds=threshold)
        result = self.event("UserPromptSubmit")
        self.assertEqual(set(result), {"hookSpecificOutput"})
        return result

    def append(self, item):
        with self.page.open("a") as stream:
            stream.write(json.dumps(item) + "\n")

    def report(self):
        return json.loads(next((self.data / "auto-reports").glob("*.json")).read_text())

    def test_disabled_has_no_report_store_side_effects(self):
        configure(self.data, enabled=False)
        before = set(self.data.rglob("*"))
        self.assertFalse(settings(self.data)["enabled"])
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertEqual(set(self.data.rglob("*")), before)

    def test_missing_settings_default_on_without_writing_preferences(self):
        self.assertEqual(settings(self.data), {"enabled": True, "threshold_seconds": 0})
        self.assertFalse(self.data.exists())
        self.assertIsNotNone(self.event("UserPromptSubmit"))
        self.append(counter(1200))
        self.assertEqual(set(self.event("Stop", 1)), {"systemMessage"})
        self.assertEqual(self.report()["usage"]["total"], 200)
        self.assertFalse((self.data / "auto-report.json").exists())

    def test_switch_is_reread_and_explicit_off_is_not_overridden(self):
        self.event("UserPromptSubmit")
        configure(self.data, enabled=False)
        saved = (self.data / "auto-report.json").read_bytes()
        self.assertIsNone(self.event("Stop", 1))
        self.assertEqual((self.data / "auto-report.json").read_bytes(), saved)
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        configure(self.data, enabled=True)
        self.event("UserPromptSubmit", 2, turn_id="next-turn")
        self.assertIsNotNone(self.event("Stop", 3, turn_id="next-turn"))

    def test_parallel_tasks_can_initialize_shared_store(self):
        configure(self.data, enabled=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda n: self.event("UserPromptSubmit", turn_id=f"turn-{n}"), range(8))
            )
        self.assertTrue(all(set(result) == {"hookSpecificOutput"} for result in results))
        self.assertEqual(len(recent(self.data)), 8)

    def test_parallel_tasks_keep_all_starts_under_write_contention(self):
        from codex_run_budget.auto_report import _connect, _footer

        configure(self.data, enabled=True)
        connection = _connect(self.data)
        connection.close()
        gate = Barrier(8)

        def start(n):
            gate.wait(timeout=10)
            return self.event("UserPromptSubmit", turn_id=f"turn-{n}")

        def slow_footer(*args, **kwargs):
            # Eight starts now need more than the former 0.4-second busy wait.
            sleep(0.09)
            return _footer(*args, **kwargs)

        with patch("codex_run_budget.auto_report._footer", side_effect=slow_footer):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(start, range(8)))
        bad = [(n, sorted(result) if isinstance(result, dict) else result)
               for n, result in enumerate(results)
               if not isinstance(result, dict) or set(result) != {"hookSpecificOutput"}]
        self.assertEqual(bad, [])
        self.assertEqual(len(recent(self.data)), 8)

    def test_schema_and_preflight_reads_share_one_sqlite_wait_deadline(self):
        from codex_run_budget.auto_report import _connect

        configure(self.data, enabled=True)
        connection = _connect(self.data)
        connection.close()
        path = self.data / "auto-reports/timing.sqlite3"
        first = sqlite3.connect(path, isolation_level=None)
        second = sqlite3.connect(path, isolation_level=None)
        entered, connected, proceed = Event(), Event(), Event()
        observed_wait_ms = []

        def two_phase_connect(root, *, deadline=None):
            entered.set()
            result = _connect(root, deadline=deadline)
            observed_wait_ms.append(result.execute("PRAGMA busy_timeout").fetchone()[0])
            connected.set()
            if not proceed.wait(timeout=5):
                result.close()
                raise TimeoutError("second SQLite lock was not established")
            return result

        first.execute("BEGIN EXCLUSIVE")
        try:
            with patch("codex_run_budget.auto_report._connect", side_effect=two_phase_connect):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.event, "UserPromptSubmit")
                    try:
                        self.assertTrue(entered.wait(timeout=5))
                        sleep(0.7)  # CREATE TABLE waits on the first exclusive lock.
                        first.rollback()
                        self.assertTrue(connected.wait(timeout=5))
                        second.execute("BEGIN EXCLUSIVE")
                        proceed.set()  # The preflight SELECT now waits on a second lock.
                        result = future.result(timeout=2.5)
                        self.assertEqual(set(result), {"systemMessage"})
                    finally:
                        proceed.set()
                        second.rollback()
        finally:
            first.close()
            second.close()
        # The first lock consumed part of the two-second budget. The preflight
        # SELECT must not inherit the original two-second busy timeout.
        self.assertEqual(len(observed_wait_ms), 1)
        self.assertLessEqual(observed_wait_ms[0], 1500)
        self.assertEqual(len(recent(self.data)), 0)

    def test_every_turn_default_zero_and_boundary_counts(self):
        self.start()
        self.append(counter(1200))
        message = self.event("Stop", 0)
        self.assertEqual(set(message), {"systemMessage"})
        self.assertLess(len(message["systemMessage"]), 600)
        receipt = self.report()
        self.assertEqual(receipt["elapsed_seconds"], 0)
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertEqual(receipt["usage"]["cached_input"], 160)
        self.assertEqual(receipt["model_requests_for_report"], 0)
        self.assertEqual(receipt["task_hash"], stable_hash("private-session-id"))
        self.assertIsNone(self.event("Stop", 10))
        self.assertEqual(recent(self.data)[0]["state"], "reported")

    def test_start_requests_inline_preview_and_stop_completes_pending_markdown(self):
        result = self.start()
        specific = result["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        context = specific["additionalContext"]
        target = next((self.data / "auto-reports").glob("*.md"))
        self.assertIn(f"--preview {self.payload['session_id']} {self.payload['turn_id']} "
                      "--data-dir ", context)
        self.assertIn("visualize reference", context)
        self.assertLess(len(context), 1300)
        self.assertIn("待結算", target.read_text())
        self.assertNotIn("Token 前後差額", target.read_text())
        self.append(counter(1400))
        self.event("Stop", 10)
        self.assertIn("400", target.read_text())
        self.assertNotIn("待結算", target.read_text())
        final = target.read_bytes()
        self.assertIsNone(self.event("Stop", 20))
        self.assertEqual(target.read_bytes(), final)

    def test_footer_command_quotes_shell_characters(self):
        self.data = self.root / "space >[inject](x)"
        context = self.start()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("'" + str(self.data) + "'", context)
        command = context.split(
            "If eligible, before final run this usage-card preview once: ", 1
        )[1]
        self.assertNotIn("\n", command.split(" --output-dir", 1)[0])

    def test_footer_has_bounded_instruction_and_no_report_body_task(self):
        from codex_run_budget.auto_report import _footer
        from codex_run_budget.report_i18n import ReportText

        directory = self.root / "footer"
        directory.mkdir()
        specific = _footer(directory, "example", self.payload)["hookSpecificOutput"]
        context = specific["additionalContext"]
        self.assertTrue(context.startswith(
            "<run-budget-usage-card>\n"
            "Run Budget usage-card footer only. Continue the user's task normally.\n"
        ))
        self.assertTrue(context.endswith("\n</run-budget-usage-card>"))
        self.assertIn("Use this usage-card command for the parent Task's footer; "
                      "subagents use their own usage-card command.", context)
        eligibility = (
            "Eligibility: the final answer must allow an extra usage-card line. "
            "If the user requires an exact final answer, JSON-only or code-only final output, "
            "or a final-answer schema, "
            "skip this entire footer: do not run the usage-card preview or append its reference."
        )
        self.assertLess(context.index(eligibility), context.index("Use this usage-card command"))
        self.assertLess(
            context.index("Use this usage-card command"),
            context.index("If eligible, before final run this usage-card preview once:")
        )
        self.assertLess(len(context.split("--output-dir", 1)[-1]), 300)
        self.assertIn("Task visualization root from writable roots; else cwd/work", context)
        self.assertIn("Append only your preview's visualize reference unchanged on its own line, "
                      "even in child replies; never relay others' refs.", context)
        self.assertIn("Card only: silently skip disabled/unavailable;", context)
        self.assertIn("no reading, analysis, skills or retries.", context)
        self.assertNotIn(ReportText("zh-Hant")("card_note"), context)

    def fresh_page(self, *, prefix=(), extra_meta=None):
        meta = {"type": "session_meta", "payload": {
            "id": self.payload["session_id"], **(extra_meta or {})
        }}
        records = [meta, *prefix, {"type": "event_msg", "payload": {
            "type": "task_started", "turn_id": self.payload["turn_id"]
        }}, {"type": "turn_context", "payload": {"turn_id": self.payload["turn_id"]}}]
        self.page.write_text("\n".join(map(json.dumps, records)) + "\n")

    def test_verified_first_turn_settles_without_inventing_missing_counter(self):
        self.fresh_page()
        initial = snapshot(str(self.page), self.payload["turn_id"])
        self.assertIsNone(initial["usage"])
        self.assertTrue(initial["fresh_turn_start"])
        self.start()
        self.append(counter(1200))
        self.event("Stop", 1)
        self.assertEqual(self.report()["usage"]["total"], 1200)
        self.assertEqual(self.report()["usage_status"], "verified_first_turn_counter")

    def test_first_request_counter_available_before_post_tool_event(self):
        self.fresh_page()
        self.start()
        request = native_counter(self.payload["session_id"], self.payload["turn_id"], 1200)
        self.append(request)
        self.append(request)  # A repeated cumulative snapshot is never added twice.
        self.event("Stop", 1)
        self.assertEqual(self.report()["usage"]["total"], 1200)
        self.assertEqual(self.report()["usage_status"], "native_turn_counter")

    def test_request_counter_advances_old_event_without_double_counting(self):
        self.start()
        self.append(counter(1200))
        self.append(native_counter("private-session-id", self.payload["turn_id"], 1500,
                                   request=300, turn_total=500))
        self.assertEqual(snapshot(str(self.page), self.payload["turn_id"])["usage"]["total"], 1500)
        self.append(counter(1500))
        self.event("Stop", 1)
        self.assertEqual(self.report()["usage"]["total"], 500)

    def test_interleaved_offset_counters_keep_native_usage_and_turn_usage_together(self):
        from codex_run_budget.auto_report import _delta

        for offset in (9000, -1000):
            with self.subTest(event_offset=offset):
                self.data = self.root / f"offset-{offset}"
                self.page.write_text(json.dumps(self.meta) + "\n"
                                     + json.dumps(counter(1800 + offset)) + "\n")
                before = snapshot(str(self.page), self.payload["turn_id"])
                self.assertEqual(before["counter_source"], "token_count")
                self.start()
                self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                           2000, request=200, turn_total=200))
                self.append(counter(2000 + offset))
                self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                           2300, request=300, turn_total=500))
                native_end = self.page.stat().st_size - 1
                self.append(counter(2300 + offset))
                after = snapshot(str(self.page), self.payload["turn_id"])
                self.assertEqual(after["counter_source"], "native_request")
                self.assertEqual(after["usage"]["total"], 2300)
                self.assertEqual(after["turn_usage"]["total"], 500)
                self.assertEqual(after["usage_end"], native_end)
                self.assertNotIn("counter_reset_end", after)
                usage, status = _delta(before, after)
                self.assertEqual((usage["total"], status), (500, "native_turn_counter"))
                self.event("Stop", 1)
                self.assertEqual(self.report()["usage"]["total"], 500)
                self.assertEqual(self.report()["task_usage"]["total"], 2300)
                self.assertEqual(self.report()["usage_status"], "native_turn_counter")

    def test_native_turn_counter_accepts_legacy_baseline_with_unknown_counter_source(self):
        from codex_run_budget.auto_report import _delta

        self.append(counter(10800))
        before = snapshot(str(self.page), self.payload["turn_id"])
        before.pop("counter_source", None)  # Persisted baseline from an older runtime.
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   2300, request=300, turn_total=500))
        self.append(counter(11300))
        after = snapshot(str(self.page), self.payload["turn_id"])
        usage, status = _delta(before, after)
        self.assertEqual((usage["total"], status), (500, "native_turn_counter"))
        self.assertEqual(after["usage"]["total"], 2300)
        self.assertEqual(after["counter_source"], "native_request")

    def test_real_native_cumulative_and_turn_declines_fail_with_monotone_event_lane(self):
        from codex_run_budget.auto_report import _delta

        for latest_total, latest_turn in ((1900, 600), (2100, 400)):
            with self.subTest(native_total=latest_total, native_turn=latest_turn):
                self.page.write_text(json.dumps(self.meta) + "\n"
                                     + json.dumps(counter(10800)) + "\n")
                before = snapshot(str(self.page), self.payload["turn_id"])
                self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                           2000, request=100, turn_total=500))
                self.append(counter(11000))
                self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                           latest_total, request=100, turn_total=latest_turn))
                self.append(counter(11300))
                after = snapshot(str(self.page), self.payload["turn_id"])
                self.assertEqual(after["counter_source"], "native_request")
                self.assertEqual(after["usage"]["total"], latest_total)
                self.assertIsNone(_delta(before, after)[0])
                legacy = {key: value for key, value in before.items() if key != "counter_source"}
                self.assertIsNone(_delta(legacy, after)[0])
                if latest_total < 2000:
                    self.assertGreater(after["counter_reset_end"], before["size"])
                else:
                    self.assertNotIn("turn_usage", after)

    def test_fallback_event_counter_does_not_subtract_a_native_source_baseline(self):
        from codex_run_budget.auto_report import _delta

        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   1200, request=200, turn_total=200))
        before = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(before["counter_source"], "native_request")
        self.append({"type": "response_item", "payload": {"type": "message", "text": "x" * 4096}})
        self.append(counter(10300))
        with patch("codex_run_budget.auto_report.SCAN_BYTES", 512):
            after = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(after["counter_source"], "token_count")
        self.assertEqual(after["usage"]["total"], 10300)
        self.assertEqual(_delta(before, after), (None, "counter_source_changed"))

    def test_native_source_decline_across_bounded_snapshots_is_not_hidden_by_turn_counter(self):
        from codex_run_budget.auto_report import _delta

        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   3000, request=100, turn_total=500))
        before = snapshot(str(self.page), self.payload["turn_id"])
        self.append({"type": "response_item", "payload": {"type": "message", "text": "x" * 4096}})
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   2800, request=100, turn_total=700))
        with patch("codex_run_budget.auto_report.SCAN_BYTES", 1024):
            after = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(before["counter_source"], "native_request")
        self.assertEqual(after["counter_source"], "native_request")
        self.assertTrue(after["tail_limited"])
        self.assertNotIn("counter_reset_end", after)
        self.assertEqual(after["turn_usage"]["total"], 700)
        self.assertEqual(_delta(before, after), (None, "counter_reset_or_inconsistent"))

    def test_invalid_latest_native_counter_never_falls_back_to_older_or_event_usage(self):
        from codex_run_budget.auto_report import _delta

        for field, missing in (("thread_token_usage", False), ("turn_token_usage", False),
                               ("turn_token_usage", True), ("usage", True), ("response_id", True)):
            with self.subTest(field=field, missing=missing):
                self.page.write_text(json.dumps(self.meta) + "\n"
                                     + json.dumps(counter(10800)) + "\n")
                before = snapshot(str(self.page), self.payload["turn_id"])
                self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                           2000, request=200, turn_total=200))
                broken = native_counter(self.payload["session_id"], self.payload["turn_id"],
                                        2300, request=300, turn_total=500)
                if missing:
                    del broken["payload"][field]
                else:
                    broken["payload"][field] = None
                self.append(broken)
                self.append(counter(11300))
                after = snapshot(str(self.page), self.payload["turn_id"])
                self.assertEqual(after["counter_source"], "native_request")
                self.assertIsNone(after["usage"])
                self.assertNotIn("turn_usage", after)
                self.assertIsNone(_delta(before, after)[0])

    def test_native_counter_rejects_foreign_scope_missing_fields_and_bad_values(self):
        base = native_counter("private-session-id", self.payload["turn_id"], 1200)
        variants = [
            {"thread_id": "other-task"}, {"session_id": "other-session"},
            {"root_turn_id": "other-turn"}, {"response_id": ""},
            {"response_id": "x" * 513}, {"turn_token_usage": None},
            {"usage": counter(1300)["payload"]["info"]["total_token_usage"]},
            {"turn_token_usage": counter(1300)["payload"]["info"]["total_token_usage"]},
        ]
        for field, value in (("total_tokens", True), ("input_tokens", -1),
                             ("cached_input_tokens", 1300), ("output_tokens", 2**64)):
            usage = dict(base["payload"]["thread_token_usage"], **{field: value})
            variants.append({"thread_token_usage": usage})
        for changes in variants:
            with self.subTest(fields=list(changes)):
                self.page.write_text(json.dumps(self.meta) + "\n")
                self.append({**base, "payload": {**base["payload"], **changes}})
                self.assertIsNone(snapshot(str(self.page), self.payload["turn_id"])["usage"])

    def test_request_only_and_foreign_turn_do_not_replace_cumulative_counter(self):
        self.append(native_counter("private-session-id", "other-turn", 9000))
        request = native_counter("private-session-id", self.payload["turn_id"], 1200)
        del request["payload"]["thread_token_usage"]
        self.append(request)
        self.assertEqual(snapshot(str(self.page), self.payload["turn_id"])["usage"]["total"], 1000)

    def test_first_request_counter_reset_invalidates_zero_baseline_proof(self):
        self.fresh_page()
        self.start()
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"], 1200))
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"], 1000))
        self.event("Stop", 1)
        self.assertIsNone(self.report()["usage"])

    def test_native_turn_counter_does_not_need_an_invented_first_turn_baseline(self):
        self.fresh_page()
        self.start()
        self.append({"type": "response_item", "payload": {"type": "message",
                     "role": "assistant", "content": "x" * SCAN_BYTES}})
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"], 1200))
        observed = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(observed["usage"]["total"], 1200)
        self.assertTrue(observed["tail_limited"])
        self.assertFalse(observed["first_turn_only"])
        self.event("Stop", 1)
        self.assertEqual(self.report()["usage"]["total"], 1200)
        self.assertEqual(self.report()["usage_status"], "native_turn_counter")

    def test_segmented_task_native_turn_and_task_totals_remain_distinct(self):
        self.fresh_page(extra_meta={"history_mode": "delta", "history_base": "example-base"})
        self.start()
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   90500, request=200, turn_total=500))
        self.event("Stop", 1)
        receipt = self.report()
        self.assertEqual(receipt["task_usage"]["total"], 90500)
        self.assertEqual(receipt["usage"]["total"], 500)
        self.assertEqual(receipt["usage_status"], "native_turn_counter")
        for path in (self.data / "auto-reports").glob("*.html"):
            html = path.read_text()
            self.assertIn("90,500", html)
            self.assertNotIn("Fast", html)

    def test_first_turn_proof_rejects_history_forks_reset_and_incomplete_prefix(self):
        cases = {
            "inherited": {"prefix": ({"type": "response_item", "payload": {
                "type": "message", "role": "assistant", "content": []
            }},)},
            "forked": {"extra_meta": {"forked_from_id": "example-parent"}},
            "segmented": {"extra_meta": {"history_base": "example-history-base"}},
            "prior_turn": {"prefix": ({"type": "event_msg", "payload": {
                "type": "task_started", "turn_id": "earlier-turn"
            }},)},
            "reset": {}, "malformed": {}, "partial": {}, "another_turn": {},
            "nonobject": {}, "missing_type": {}, "null_payload": {}, "unknown_record": {},
        }
        from codex_run_budget.auto_report import _delta

        for case, options in cases.items():
            with self.subTest(case=case):
                self.fresh_page(**options)
                if case == "malformed":
                    with self.page.open("a") as stream:
                        stream.write("invalid record\n")
                if case == "partial":
                    with self.page.open("a") as stream:
                        stream.write('{"type":')
                invalid = {"nonobject": [], "missing_type": {"payload": {}},
                           "null_payload": {"type": "event_msg", "payload": None},
                           "unknown_record": {"type": "compacted", "payload": {}}}
                if case in invalid:
                    self.append(invalid[case])
                before = snapshot(str(self.page), self.payload["turn_id"])
                self.append(counter(1200))
                if case == "reset":
                    self.append(counter(500))
                if case == "another_turn":
                    self.append({"type": "event_msg", "payload": {
                        "type": "task_started", "turn_id": "later-turn"
                    }})
                after = snapshot(str(self.page), self.payload["turn_id"])
                self.assertIsNone(_delta(before, after)[0])

    def test_pending_file_does_not_claim_report_after_failure_or_disable(self):
        self.start()
        target = next((self.data / "auto-reports").glob("*.md"))
        pending = target.read_bytes()
        configure(self.data, enabled=False)
        self.assertIsNone(self.event("Stop", 1))
        self.assertEqual(target.read_bytes(), pending)

    def test_report_never_overwrites_foreign_markdown_or_symlink(self):
        for mode in ("foreign", "symlink"):
            with self.subTest(mode=mode):
                self.payload["turn_id"] = mode
                self.start()
                row = recent(self.data)[0]
                target = self.data / "auto-reports" / (row["key"] + ".md")
                foreign = self.root / "foreign"
                foreign.write_text("retain")
                if mode == "symlink":
                    target.unlink()
                    target.symlink_to(foreign)
                else:
                    target.write_text("retain")
                self.assertEqual(set(self.event("Stop", 1)), {"systemMessage"})
                self.assertEqual(target.read_text(), "retain")
                self.assertEqual(foreign.read_text(), "retain")
                self.assertEqual(recent(self.data)[0]["state"], "failed")

    def test_governor_preserves_budget_context_with_footer(self):
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        budget = {"systemMessage": "STEER", "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": "budget rules"
        }}
        with patch.object(governor, "_handle_budget", return_value=budget):
            result = governor.handle({**self.payload, "hook_event_name": "UserPromptSubmit"})
        self.assertEqual(result["systemMessage"], "STEER")
        self.assertTrue(
            result["hookSpecificOutput"]["additionalContext"].startswith("budget rules\n")
        )
        self.assertNotIn("decision", result)
        self.assertNotIn("continue", result)

    def test_unproven_subagent_cannot_start_report(self):
        self.assertIsNone(self.event("UserPromptSubmit", agent_id="child"))
        self.meta["payload"]["source"] = {"subagent": {"thread_spawn": {}}}
        self.page.write_text(json.dumps(self.meta) + "\n")
        self.assertIsNone(self.event("UserPromptSubmit"))
        self.assertFalse(self.data.exists())

    def _native_child_fixture(self):
        root_id = "00000000-0000-7000-8000-000000000001"
        child_id = "00000000-0000-7000-8000-000000000002"
        source = {"subagent": {"thread_spawn": {"parent_thread_id": root_id}}}
        root_page = self.root / "synthetic-root.jsonl"
        root_page.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": root_id
        }}) + "\n" + json.dumps(counter(1000)) + "\n")
        child_page = self.root / "synthetic-child.jsonl"
        child_page.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": child_id, "source": source
        }}) + "\n" + json.dumps({"type": "event_msg", "payload": {
            "type": "task_started", "thread_id": child_id, "turn_id": "synthetic-child-turn"
        }}) + "\n" + json.dumps(counter(100)) + "\n")
        with sqlite3.connect(self.root / "state_5.sqlite") as catalog:
            catalog.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY,name TEXT,agent_nickname TEXT,"
                "agent_role TEXT,agent_path TEXT,source TEXT,rollout_path TEXT)"
            )
            catalog.executemany(
                "INSERT INTO threads VALUES(?,?,?,?,?,?,?)",
                (
                    (root_id, "synthetic root", None, None, None, '"vscode"', str(root_page)),
                    (child_id, "same name", "worker", "worker", "/root/worker",
                     json.dumps(source), str(child_page)),
                ),
            )
        payload = {
            "session_id": root_id,
            "agent_id": child_id,
            "turn_id": "synthetic-child-turn",
            "transcript_path": str(child_page),
        }
        return root_id, child_id, root_page, child_page, payload

    def test_native_subagent_start_and_stop_publish_own_receipt_once(self):
        root_id, child_id, root_page, child_page, payload = self._native_child_fixture()
        start = handle({**payload, "hook_event_name": "SubagentStart"}, self.data,
                       wall=1000000, monotonic=5000, home=self.root)
        self.assertEqual(set(start), {"hookSpecificOutput"})
        context = start["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"--preview {child_id} {payload['turn_id']} --data-dir ", context)
        self.assertIn("Use this usage-card command for this subagent's footer; "
                      "inherited usage-card commands belong to other agents.", context)
        self.assertIn("Inherited parent visualization roots are automatically redirected "
                      "to this subagent's output.", context)
        self.assertEqual(len(recent(self.data)), 1)
        native = native_counter(child_id, payload["turn_id"], 300,
                                request=200, turn_total=200)
        native["payload"].update(session_id=root_id, root_turn_id="synthetic-root-turn")
        with child_page.open("a") as output:
            output.write(json.dumps(native) + "\n")
        stop = handle({**payload, "hook_event_name": "SubagentStop",
                       "transcript_path": str(root_page),
                       "agent_transcript_path": str(child_page)},
                      self.data, wall=1000001, monotonic=5001, home=self.root)
        self.assertEqual(set(stop), {"systemMessage"})
        receipts = list((self.data / "auto-reports").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["task_hash"], stable_hash(child_id))
        self.assertEqual(receipt["task"]["selector"], stable_hash(child_id)[:12])
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertTrue(receipt["source_identity_verified"])
        self.assertNotEqual(receipt["task_hash"], stable_hash(root_id))
        self.assertIsNone(handle({**payload, "hook_event_name": "SubagentStop",
                                  "transcript_path": str(root_page),
                                  "agent_transcript_path": str(child_page)},
                                 self.data, wall=1000002, monotonic=5002, home=self.root))
        self.assertIsNone(handle({**payload, "hook_event_name": "Stop"}, self.data,
                                 wall=1000003, monotonic=5003, home=self.root))
        self.assertEqual(len(list((self.data / "auto-reports").glob("*.json"))), 1)

    def test_subagent_stop_rejects_changed_root_with_same_direct_parent(self):
        root_id, child_id, root_page, child_page, payload = self._native_child_fixture()
        self.assertIn("hookSpecificOutput", handle(
            {**payload, "hook_event_name": "SubagentStart"}, self.data,
            wall=1000000, monotonic=5000, home=self.root))
        other_root = "00000000-0000-7000-8000-000000000003"
        with sqlite3.connect(self.root / "state_5.sqlite") as catalog:
            catalog.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?)", (
                other_root, "synthetic other root", None, None, None, '"vscode"', str(root_page)))
            catalog.execute("UPDATE threads SET source=? WHERE id=?", (
                json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": other_root}}}),
                root_id))
        with child_page.open("a") as output:
            output.write(json.dumps(counter(150)) + "\n")
        self.assertIn("systemMessage", handle(
            {**payload, "session_id": other_root, "hook_event_name": "SubagentStop",
             "agent_transcript_path": str(child_page)}, self.data,
            wall=1000001, monotonic=5001, home=self.root))
        receipt = self.report()
        self.assertFalse(receipt["source_identity_verified"])
        self.assertEqual(receipt["usage_status"], "source_identity_unavailable")
        self.assertIsNone(receipt["usage"])
        self.assertIsNone(receipt["task_usage"])
        self.assertIsNone(receipt["task"])
        self.assertEqual(receipt["stop_contexts"], [])
        with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
            baseline = json.loads(timing.execute("SELECT baseline FROM turns").fetchone()[0])
        self.assertEqual(baseline["root_hash"], stable_hash(root_id))
        self.assertEqual(baseline["parent_hash"], stable_hash(root_id))
        self.assertEqual(baseline["usage"]["total"], 100)
        self.assertNotIn(root_id, json.dumps(baseline))
        self.assertNotIn(child_id, json.dumps(baseline))

    def test_subagent_stop_requires_original_root_proof_in_legacy_baseline(self):
        _, _, _, child_page, payload = self._native_child_fixture()
        self.assertIn("hookSpecificOutput", handle(
            {**payload, "hook_event_name": "SubagentStart"}, self.data,
            wall=1000000, monotonic=5000, home=self.root))
        with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
            baseline = json.loads(timing.execute("SELECT baseline FROM turns").fetchone()[0])
            baseline.pop("root_hash", None)
            timing.execute("UPDATE turns SET baseline=?", (json.dumps(baseline),))
        with child_page.open("a") as output:
            output.write(json.dumps(counter(150)) + "\n")
        self.assertIn("systemMessage", handle(
            {**payload, "hook_event_name": "SubagentStop",
             "agent_transcript_path": str(child_page)}, self.data,
            wall=1000001, monotonic=5001, home=self.root))
        receipt = self.report()
        self.assertFalse(receipt["source_identity_verified"])
        self.assertEqual(receipt["usage_status"], "source_identity_unavailable")
        self.assertIsNone(receipt["usage"])

    def test_child_stop_rejects_explicit_role_contradiction_and_keeps_legacy_control(self):
        _, child, _, child_page, payload = self._native_child_fixture()
        original_source = child_page.read_bytes()
        for case in ("parent", "unknown", "null", "legacy", "control"):
            with self.subTest(case=case):
                self.data = self.root / ("child-role-" + case)
                child_page.write_bytes(original_source)
                self.assertIn("hookSpecificOutput", handle(
                    {**payload, "hook_event_name": "SubagentStart"}, self.data,
                    wall=1000000, monotonic=5000, home=self.root))
                with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
                    baseline = json.loads(timing.execute(
                        "SELECT baseline FROM turns").fetchone()[0])
                    timing.execute("UPDATE turns SET baseline=?", (
                        json.dumps(baseline_role_case(baseline, case)),))
                with child_page.open("a") as output:
                    output.write(json.dumps(counter(150)) + "\n")
                self.assertIn("systemMessage", handle(
                    {**payload, "hook_event_name": "SubagentStop",
                     "agent_transcript_path": str(child_page)}, self.data,
                    wall=1000001, monotonic=5001, home=self.root))
                receipt = self.report()
                self.assertEqual(receipt["task_hash"], stable_hash(child))
                if case in ("legacy", "control"):
                    self.assertTrue(receipt["source_identity_verified"])
                    self.assertEqual(receipt["usage"]["total"], 50)
                    self.assertEqual(receipt["task_usage"]["total"], 150)
                else:
                    self.assertFalse(receipt["source_identity_verified"])
                    self.assertEqual(receipt["usage_status"], "source_identity_unavailable")
                    self.assertIsNone(receipt["usage"])
                    self.assertIsNone(receipt["task_usage"])
                    self.assertEqual(receipt["stop_contexts"], [])

    def test_root_stop_keeps_legacy_start_proof_and_rejects_unknown_or_absent_role(self):
        for case in ("unknown", "null", "no-evidence", "legacy", "control"):
            with self.subTest(case=case):
                self.data = self.root / ("root-role-" + case)
                self.page.write_text(json.dumps(self.meta) + "\n"
                                     + json.dumps(counter(1000)) + "\n")
                self.start()
                with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
                    baseline = json.loads(timing.execute(
                        "SELECT baseline FROM turns").fetchone()[0])
                    timing.execute("UPDATE turns SET baseline=?", (
                        json.dumps(baseline_role_case(baseline, case)),))
                self.append(counter(1200))
                self.assertIn("systemMessage", self.event("Stop", 1))
                receipt = self.report()
                if case in ("legacy", "control"):
                    self.assertTrue(receipt["source_identity_verified"])
                    self.assertEqual(receipt["usage"]["total"], 200)
                else:
                    self.assertFalse(receipt["source_identity_verified"])
                    self.assertIsNone(receipt["usage"])

    def test_invalid_child_identity_cannot_collect_or_publish_descendant_subtotal(self):
        _, _, _, child_page, payload = self._native_child_fixture()
        original_source = child_page.read_bytes()
        for field in ("task_hash", "root_hash", "parent_hash", "source_role", "control"):
            with self.subTest(field=field):
                self.data = self.root / ("descendant-scope-" + field)
                child_page.write_bytes(original_source)
                self.assertIn("hookSpecificOutput", handle(
                    {**payload, "hook_event_name": "SubagentStart"}, self.data,
                    wall=1000000, monotonic=5000, home=self.root))
                if field != "control":
                    with sqlite3.connect(self.data / "auto-reports/timing.sqlite3") as timing:
                        baseline = json.loads(timing.execute(
                            "SELECT baseline FROM turns").fetchone()[0])
                        baseline[field] = "parent" if field == "source_role" else "f" * 64
                        timing.execute("UPDATE turns SET baseline=?", (json.dumps(baseline),))
                with child_page.open("a") as output:
                    output.write(json.dumps(counter(150)) + "\n")
                with patch("codex_run_budget.child_usage.collect",
                           return_value=synthetic_descendant_subtotal()) as collect, patch(
                    "codex_run_budget.auto_report.snapshot", wraps=snapshot
                ) as read_source:
                    self.assertIn("systemMessage", handle(
                        {**payload, "hook_event_name": "SubagentStop",
                         "agent_transcript_path": str(child_page)}, self.data,
                        wall=1000001, monotonic=5001, home=self.root))
                receipt = self.report()
                total, complete = observed_total(receipt["usage"], receipt["subagents"])
                if field == "control":
                    read_source.assert_called_once()
                    collect.assert_called_once()
                    self.assertTrue(receipt["source_identity_verified"])
                    self.assertTrue(receipt["subagents_included"])
                    self.assertEqual(receipt["subagents"]["usage"]["total"], 90000)
                    self.assertEqual((total["total"], complete), (90050, True))
                    continue
                read_source.assert_not_called()
                collect.assert_not_called()
                self.assertFalse(receipt["source_identity_verified"])
                self.assertEqual(receipt["scope"], "subagent_turn_stop_boundary")
                self.assertEqual(receipt["subagents"]["status"], "unavailable")
                self.assertIsNone(receipt["subagents"]["usage"])
                self.assertFalse(receipt["subagents_included"])
                self.assertEqual((total, complete), (None, False))
                for extension in ("json", "md", "html"):
                    content = next((self.data / "auto-reports").glob("*." + extension)).read_text()
                    self.assertNotIn("90,000", content)
                    self.assertNotIn("90000", content)

    def test_verified_root_stop_still_collects_descendants_separately(self):
        self.start()
        self.append(counter(1200))
        with patch("codex_run_budget.child_usage.collect",
                   return_value=synthetic_descendant_subtotal()) as collect, patch(
            "codex_run_budget.auto_report.snapshot", wraps=snapshot
        ) as read_source:
            self.assertIn("systemMessage", self.event("Stop", 1))
        read_source.assert_called_once()
        collect.assert_called_once()
        receipt = self.report()
        self.assertTrue(receipt["source_identity_verified"])
        self.assertEqual(receipt["scope"], "user_turn_stop_boundary")
        self.assertEqual(receipt["usage"]["total"], 200)
        self.assertEqual(receipt["subagents"]["usage"]["total"], 90000)
        self.assertEqual(observed_total(receipt["usage"], receipt["subagents"])[0]["total"], 90200)

    def test_child_baseline_cannot_be_reused_as_parent_report(self):
        _, child_id, _, child_page, payload = self._native_child_fixture()
        self.assertIn("hookSpecificOutput", handle(
            {**payload, "hook_event_name": "SubagentStart"}, self.data,
            wall=1000000, monotonic=5000, home=self.root))
        with sqlite3.connect(self.root / "state_5.sqlite") as catalog:
            catalog.execute("UPDATE threads SET source=? WHERE id=?", ('"vscode"', child_id))
        child_page.write_text("".join(json.dumps(item) + "\n" for item in (
            {"type": "session_meta", "payload": {"id": child_id, "source": "vscode"}},
            {"type": "turn_context", "payload": {"turn_id": payload["turn_id"],
                                                "model": "synthetic-other-root-model"}},
            native_counter(child_id, payload["turn_id"], 150, turn_total=50),
        )))
        with patch("codex_run_budget.child_usage.collect",
                   return_value=synthetic_descendant_subtotal()) as collect, patch(
            "codex_run_budget.auto_report.snapshot", wraps=snapshot
        ) as read_source:
            self.assertIn("systemMessage", handle(
                {"session_id": child_id, "turn_id": payload["turn_id"],
                 "hook_event_name": "Stop", "transcript_path": str(child_page)},
                self.data, wall=1000001, monotonic=5001, home=self.root))
        receipt = self.report()
        self.assertEqual(receipt["scope"], "subagent_turn_stop_boundary")
        read_source.assert_not_called()
        collect.assert_not_called()
        self.assertFalse(receipt["source_identity_verified"])
        self.assertIsNone(receipt["usage"])
        self.assertIsNone(receipt["task_usage"])
        self.assertEqual(receipt["stop_contexts"], [])
        self.assertEqual(observed_total(receipt["usage"], receipt["subagents"]), (None, False))
        for content in _documents(receipt):
            self.assertNotIn("主代理", content)
            self.assertNotIn("90,000", content)

    def test_subagent_receipt_documents_show_own_scope_and_escaped_parent(self):
        _, _, _, child_page, payload = self._native_child_fixture()
        handle({**payload, "hook_event_name": "SubagentStart"}, self.data,
               wall=1000000, monotonic=5000, home=self.root)
        with child_page.open("a") as output:
            output.write(json.dumps(counter(150)) + "\n")
        handle({**payload, "hook_event_name": "SubagentStop",
                "agent_transcript_path": str(child_page)}, self.data,
               wall=1000001, monotonic=5001, home=self.root)
        receipt = self.report()
        receipt["task"]["parent_name"] = "Synthetic <parent> [data]"
        for completed in (False, True):
            with self.subTest(completed=completed):
                receipt["completion_observed"] = completed
                receipt["scope"] = ("subagent_turn_completion_boundary" if completed
                                    else "subagent_turn_stop_boundary")
                markdown, html = _documents(receipt)
                self.assertNotIn("主代理", markdown)
                self.assertNotIn("主代理", html)
                self.assertIn("@" + receipt["task"]["selector"], markdown)
                self.assertIn("Synthetic &lt;parent&gt; &#91;data&#93;", markdown)
                self.assertIn("Synthetic &lt;parent&gt; [data]", html)
                self.assertNotIn("Synthetic <parent>", html)
        # Missing identity still has child scope, without invented parent names.
        receipt["task"] = None
        markdown, html = _documents(receipt)
        self.assertNotIn("主代理", markdown)
        self.assertNotIn("主代理", html)

    def test_native_subagent_start_rejects_wrong_lineage_and_foreign_transcript(self):
        root_id, child_id, _, child_page, payload = self._native_child_fixture()
        bad_records = (
            {"id": child_id, "source": {"subagent": {"thread_spawn": {
                "parent_thread_id": "-".join(("00000000", "0000", "7000", "8000", "000000000009"))
            }}}},
            {"id": "-".join(("00000000", "0000", "7000", "8000", "000000000010")), "source": {
                "subagent": {"thread_spawn": {"parent_thread_id": root_id}}
            }},
        )
        for index, metadata in enumerate(bad_records):
            with self.subTest(index=index):
                self.data = self.root / f"bad-data-{index}"
                child_page.write_text(json.dumps({"type": "session_meta", "payload": metadata})
                                      + "\n" + json.dumps(counter(100)) + "\n")
                self.assertIsNone(handle({**payload, "hook_event_name": "SubagentStart"},
                                         self.data, wall=1000000, monotonic=5000,
                                         home=self.root))
                self.assertEqual(recent(self.data), [])
                self.assertFalse(list(self.data.glob("auto-reports/*.json")))

    def test_child_snapshot_ignores_copied_parent_counter_before_own_start(self):
        root_id, child_id, _, child_page, payload = self._native_child_fixture()
        source = {"subagent": {"thread_spawn": {"parent_thread_id": root_id}}}
        child_page.write_text("".join(json.dumps(record) + "\n" for record in (
            {"type": "session_meta", "payload": {"id": child_id, "source": source}},
            {"type": "session_meta", "payload": {"id": root_id}},
            counter(900),
        )))
        before = snapshot(str(child_page), payload["turn_id"], allow_subagent=True,
                          root_hash=stable_hash(root_id))
        self.assertEqual(before["status"], "observed")
        self.assertIsNone(before["usage"])
        with child_page.open("a") as output:
            output.write(json.dumps({"type": "event_msg", "payload": {
                "type": "task_started", "thread_id": child_id,
                "turn_id": payload["turn_id"],
            }}) + "\n" + json.dumps(counter(100)) + "\n")
        after = snapshot(str(child_page), payload["turn_id"], allow_subagent=True,
                         root_hash=stable_hash(root_id))
        self.assertEqual(after["usage"]["total"], 100)

    def test_governor_merges_child_preview_context_and_does_not_start_after_halt(self):
        _, child_id, _, _, payload = self._native_child_fixture()
        event = {**payload, "hook_event_name": "SubagentStart"}
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        existing = {"hookSpecificOutput": {
            "hookEventName": "SubagentStart", "additionalContext": "budget rules",
        }}
        with patch.dict("os.environ", {"CODEX_HOME": str(self.root)}), patch.object(
            governor, "_handle_budget", return_value=existing
        ):
            result = governor.handle(event)
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(context.startswith("budget rules\n"))
        self.assertIn("--preview " + child_id, context)
        self.assertEqual(len(recent(self.data)), 1)

        for denied in (
            {"decision": "block", "systemMessage": "blocked"},
            {"continue": False, "stopReason": "HALT", "systemMessage": "halted"},
            {"systemMessage": "HALT already active"},
        ):
            with self.subTest(denied=denied):
                blocked_event = {**event, "turn_id": "denied-" + str(len(denied))
                                 + str(denied.get("stopReason", ""))}
                with patch.dict("os.environ", {"CODEX_HOME": str(self.root)}), patch.object(
                    governor, "_handle_budget", return_value=denied
                ):
                    self.assertEqual(governor.handle(blocked_event), denied)
                self.assertEqual(len(recent(self.data)), 1)

    def test_optional_threshold_strictly_exceeds_and_start_idempotent(self):
        self.start(300)
        self.assertIsNone(self.event("UserPromptSubmit", 200))
        self.append(counter(1500))
        self.assertIsNone(self.event("Stop", 300))
        self.assertIsNotNone(self.event("Stop", 301, stop_hook_active=True))
        self.assertEqual(self.report()["elapsed_seconds"], 301)
        self.assertTrue(self.report()["stop_hook_active"])

    def test_interruption_end_and_missing_start_never_fabricate_completion(self):
        self.start()
        self.event("Interrupt", 200)
        self.assertIsNone(self.event("Stop", 400))
        self.assertFalse(list((self.data / "auto-reports").glob("*.json")))
        self.assertIsNone(self.event("Stop", 400, turn_id="another"))
        self.event("UserPromptSubmit", 500, turn_id="another")
        self.event("SessionEnd", 600, turn_id=None)
        self.assertIsNone(self.event("Stop", 700, turn_id="another"))

    def test_clock_discontinuity_and_other_events_do_not_report(self):
        self.start()
        self.event("SessionStart", 10)
        self.event("PreCompact", 20)
        result = handle(
            {**self.payload, "hook_event_name": "Stop"}, self.data, wall=1001000, monotonic=5001
        )
        self.assertIsNone(result)
        self.assertEqual(recent(self.data)[0]["state"], "clock_discontinuity")

    def test_source_replacement_reset_and_missing_usage_are_unknown(self):
        for mode in ("replacement", "reset", "missing", "no-baseline"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                data = Path(root) / "store"
                configure(data, enabled=True)
                if mode == "no-baseline":
                    self.page.write_text(json.dumps(self.meta) + "\n")
                handle(
                    {**self.payload, "hook_event_name": "UserPromptSubmit"},
                    data,
                    wall=10,
                    monotonic=10,
                )
                if mode == "replacement":
                    self.page.rename(self.root / "old-page")
                    self.page.write_text(
                        json.dumps(self.meta) + "\n" + json.dumps(counter(2000)) + "\n"
                    )
                elif mode == "missing":
                    self.append(
                        {"type": "event_msg", "payload": {"type": "token_count", "info": {}}}
                    )
                else:
                    self.append(counter(100 if mode == "reset" else 3000))
                handle({**self.payload, "hook_event_name": "Stop"}, data, wall=11, monotonic=11)
                receipt = json.loads(next((data / "auto-reports").glob("*.json")).read_text())
                self.assertIsNone(receipt["usage"])
                self.page.write_text(
                    json.dumps(self.meta) + "\n" + json.dumps(counter(1000)) + "\n"
                )

    def test_observed_reset_recovery_and_truncated_tail_are_not_valid_differences(self):
        from codex_run_budget.auto_report import _delta

        before = snapshot(str(self.page), self.payload["turn_id"])
        self.append(counter(100))
        self.append(counter(1500))
        after = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(after["counter_source"], "token_count")
        self.assertGreater(after["counter_reset_end"], before["size"])
        self.assertIsNone(_delta(before, after)[0])
        # A reset already present before the new boundary does not poison it.
        self.append(counter(1600))
        next_snapshot = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(_delta(after, next_snapshot)[0]["total"], 100)
        with self.page.open("a") as stream:
            stream.write('{"type":"event_msg",')
        self.assertEqual(_delta(after, snapshot(str(self.page), self.payload["turn_id"])),
                         (None, "snapshot_incomplete"))

    def test_partial_baseline_cannot_establish_boundary_difference(self):
        from codex_run_budget.auto_report import _delta

        pending = json.dumps(counter(1500)) + "\n"
        with self.page.open("a") as stream:
            stream.write(pending[:45])
        before = snapshot(str(self.page), self.payload["turn_id"])
        self.assertTrue(before["invalid_records"])
        with self.page.open("a") as stream:
            stream.write(pending[45:])
        self.append(counter(1600))
        after = snapshot(str(self.page), self.payload["turn_id"])
        self.assertEqual(_delta(before, after), (None, "snapshot_incomplete"))
        # A validated native turn counter does not depend on that baseline.
        self.append(native_counter("private-session-id", self.payload["turn_id"], 1700,
                                   request=100, turn_total=200))
        usage, status = _delta(before, snapshot(str(self.page), self.payload["turn_id"]))
        self.assertEqual((usage["total"], status), (200, "native_turn_counter"))

    def test_repeated_prior_counter_is_pending_but_new_zero_observation_is_valid(self):
        from codex_run_budget.auto_report import _delta

        before = snapshot(str(self.page), self.payload["turn_id"])
        self.append({"type": "turn_context", "payload": {"turn_id": self.payload["turn_id"]}})
        self.assertEqual(_delta(before, snapshot(str(self.page), self.payload["turn_id"])),
                         (None, "turn_usage_pending"))
        self.append(counter(1000))
        usage, status = _delta(before, snapshot(str(self.page), self.payload["turn_id"]))
        self.assertEqual((usage["total"], status), (0, "boundary_counter_difference"))

    def test_foreign_start_stop_and_both_never_publish_another_tasks_counters(self):
        for stage in ("start", "stop", "both"):
            with self.subTest(stage=stage):
                self.data = self.root / ("identity-" + stage)
                self.page.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": "foreign-task" if stage in ("start", "both")
                    else self.payload["session_id"]}}) + "\n" + json.dumps(counter(1000)) + "\n")
                self.start()
                if stage == "stop":
                    self.page.write_text(json.dumps({"type": "session_meta", "payload": {
                        "id": "foreign-task"}}) + "\n")
                elif stage == "start":
                    self.page.write_text(json.dumps({"type": "session_meta", "payload": {
                        "id": self.payload["session_id"]}}) + "\n")
                self.append({"type": "turn_context", "payload": {
                    "turn_id": self.payload["turn_id"], "model": "example-foreign-model",
                    "effort": "high"}})
                self.append(counter(98000))
                self.event("Stop", 10)
                receipt = self.report()
                self.assertEqual(receipt["task_hash"], stable_hash(self.payload["session_id"]))
                self.assertFalse(receipt["source_identity_verified"])
                self.assertEqual(receipt["usage_status"], "source_identity_unavailable")
                self.assertIsNone(receipt["usage"])
                self.assertIsNone(receipt["task_usage"])
                self.assertEqual(receipt["stop_contexts"], [])
                self.assertTrue(receipt["contexts_limited"])
                for path in (self.data / "auto-reports").glob("*.html"):
                    content = path.read_text()
                    self.assertNotIn("98,000", content)
                    self.assertNotIn("example-foreign-model", content)

    def test_context_is_exact_turn_unknown_fast_not_false_and_safe(self):
        self.start()
        self.append(
            {
                "type": "turn_context",
                "payload": {"turn_id": "old-turn", "effort": "ultra", "service_tier": "fast"},
            }
        )
        self.append(
            {
                "type": "turn_context",
                "payload": {
                    "turn_id": self.payload["turn_id"],
                    "model": "gpt-6-astra",
                    "effort": "high",
                    "service_tier": "priority",
                },
            }
        )
        self.append(counter(2000))
        self.event("Stop", 1, model="</script>private")
        receipt = self.report()
        self.assertEqual(len(receipt["stop_contexts"]), 1)
        self.assertEqual(receipt["stop_contexts"][0]["reasoning_effort"], "high")
        self.assertIsNone(receipt["stop_contexts"][0]["fast_mode"])
        for path in (self.data / "auto-reports").iterdir():
            raw = path.read_bytes()
            for secret in (
                b"private-source",
                b"private-session-id",
                b"private-session-id",
                b"private-turn-id",
                b"PRIVATE PROMPT",
                b"</script>",
            ):
                self.assertNotIn(secret, raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_no_subagent_reports_and_scan_is_bounded(self):
        self.start()
        self.assertIsNone(self.event("Stop", 5, agent_id="subagent"))
        with self.page.open("ab") as stream:
            stream.write(b" " * (SCAN_BYTES + 100) + b"\n")
            stream.write((json.dumps(counter(2000)) + "\n").encode())
        result = snapshot(str(self.page), self.payload["turn_id"])
        self.assertTrue(result["tail_limited"])
        self.assertLessEqual(result["scan_bytes"], SCAN_BYTES + 128 * 1024)
        self.assertEqual(result["usage"]["total"], 2000)
        self.meta["payload"]["source"] = {"subagent": {"thread_spawn": {}}}
        self.page.write_text(json.dumps(self.meta) + "\n")
        self.assertEqual(snapshot(str(self.page), "turn")["status"], "subagent")

    def test_concurrent_stops_publish_once(self):
        self.start()
        self.append(counter(2000))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.event("Stop", 3), range(2)))
        self.assertEqual(sum(bool(r) for r in results), 1)
        self.assertEqual(len(list((self.data / "auto-reports").glob("*.md"))), 1)

    def test_symlinks_and_generation_failure_do_not_continue_or_override_halt(self):
        self.start()
        link = self.root / "link.jsonl"
        link.symlink_to(self.page)
        self.assertEqual(snapshot(str(link), "turn")["status"], "unavailable")
        with patch("codex_run_budget.auto_report._publish", side_effect=OSError):
            message = self.event("Stop", 3)
        self.assertEqual(set(message), {"systemMessage"})
        self.assertIsNone(self.event("Stop", 4))
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        with (
            patch.object(
                governor, "_handle_budget", return_value={"continue": False, "stopReason": "HALT"}
            ),
            patch("codex_run_budget.auto_report.handle", return_value={"systemMessage": "report"}),
        ):
            result = governor.handle({**self.payload, "hook_event_name": "Stop"})
        self.assertFalse(result["continue"])
        self.assertEqual(result["stopReason"], "HALT")

    def test_denied_prompt_does_not_start_and_disable_preserves_files(self):
        self.start()
        governor = Governor(self.data)
        self.addCleanup(governor.close)
        with (
            patch.object(governor, "_handle_budget", return_value={"decision": "block"}),
            patch("codex_run_budget.auto_report.handle") as reporter,
        ):
            governor.handle({**self.payload, "hook_event_name": "UserPromptSubmit"})
            reporter.assert_not_called()
        self.event("Stop", 1)
        paths = set((self.data / "auto-reports").iterdir())
        configure(self.data, enabled=False)
        self.assertIsNone(self.event("UserPromptSubmit", 2, turn_id="next"))
        self.assertEqual(paths, set((self.data / "auto-reports").iterdir()))

    def test_turn_decline_across_bounded_snapshots_is_not_hidden_by_rising_task_counter(self):
        from codex_run_budget.auto_report import _delta

        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   3000, request=100, turn_total=500))
        before = snapshot(str(self.page), self.payload["turn_id"])
        self.append({"type": "response_item", "payload": {"type": "message", "text": "x" * 4096}})
        self.append(native_counter(self.payload["session_id"], self.payload["turn_id"],
                                   3100, request=100, turn_total=400))
        with patch("codex_run_budget.auto_report.SCAN_BYTES", 1024):
            after = snapshot(str(self.page), self.payload["turn_id"])
        self.assertTrue(after["tail_limited"])
        self.assertNotIn("counter_reset_end", after)
        self.assertEqual(before["requested_turn_hash"], after["requested_turn_hash"])
        self.assertEqual((before["usage"]["total"], after["usage"]["total"]), (3000, 3100))
        self.assertEqual((before["turn_usage"]["total"], after["turn_usage"]["total"]), (500, 400))
        self.assertEqual(_delta(before, after), (None, "counter_reset_or_inconsistent"))



if __name__ == "__main__":
    unittest.main()
