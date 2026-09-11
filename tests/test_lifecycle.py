from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-run-budget"
sys.path.insert(0, str(PLUGIN / "lib"))

from codex_run_budget.audit import audit_transcript, audit_transcripts  # noqa: E402
from codex_run_budget.lifecycle import aggregate_lifecycle  # noqa: E402
from codex_run_budget.util import stable_hash  # noqa: E402

BASE = 1788998400.0


def record(kind: str, payload: dict, second: int = 0, *, stamp: str | None = None) -> dict:
    return {
        "type": kind,
        "payload": payload,
        "timestamp": stamp or f"2026-09-10T00:00:{second:02d}Z",
    }


def write_page(root: Path, name: str, records: list[dict]) -> Path:
    path = root / name
    path.write_text("".join(json.dumps(item) + "\n" for item in records))
    return path


def context(thread: str = "thread", turn: str = "turn", second: int = 0) -> list[dict]:
    return [
        record("session_meta", {"id": thread, "session_id": "shared-session"}, second),
        record(
            "turn_context",
            {"turn_id": turn, "model": "gpt-5.6-sol"},
            second + 1,
        ),
    ]


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def audit(self, records: list[dict], *, since: float | None = None, until: float | None = None):
        page = write_page(self.root, "transcript.jsonl", records)
        if since is None and until is None:
            return audit_transcript(page)["lifecycle"]
        return audit_transcripts([page], since=since, until=until)["lifecycle"]

    def test_empty_input_has_stable_schema(self) -> None:
        lifecycle = self.audit([])
        self.assertEqual(lifecycle["schema_version"], 1)
        self.assertEqual(lifecycle["summary"]["turns"], 0)
        self.assertEqual(lifecycle["turns"], [])
        self.assertIn("missing_terminal", lifecycle["diagnostics"])

    def test_normal_finish_uses_explicit_duration_and_keeps_only_hashes(self) -> None:
        lifecycle = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record(
                    "event_msg",
                    {
                        "type": "task_complete",
                        "duration_ms": 120,
                        "time_to_first_token_ms": 7,
                        "last_agent_message": "private message",
                    },
                    3,
                ),
            ]
        )
        self.assertEqual(lifecycle["summary"]["completed"], 1)
        row = lifecycle["turns"][0]
        self.assertEqual(row["state"], "completed")
        self.assertEqual(row["duration_ms"], 120)
        self.assertEqual(row["duration_source"], "explicit")
        self.assertEqual(row["time_to_first_token_ms"], 7)
        self.assertEqual(row["role"], "parent")
        serialized = json.dumps(lifecycle, sort_keys=True)
        self.assertNotIn("private message", serialized)

    def test_aborted_and_no_terminal_turns_record_later_start(self) -> None:
        records = context() + [
            record("event_msg", {"type": "task_started"}, 2),
            record("event_msg", {"type": "turn_aborted", "reason": "interrupted"}, 3),
            record("turn_context", {"turn_id": "later", "model": "gpt-5.6-sol"}, 4),
            record("event_msg", {"type": "task_started"}, 5),
        ]
        lifecycle = self.audit(records)
        rows = {row["turn_hash"]: row for row in lifecycle["turns"]}
        first = rows[stable_hash("turn")]
        self.assertEqual(first["state"], "aborted")
        self.assertTrue(first["later_turn_observed"])
        self.assertEqual(first["next_turn_hash"], stable_hash("later"))
        self.assertEqual(lifecycle["summary"]["aborted_with_later_turn"], 1)

        noend = self.audit(
            context(thread="thread-2", turn="turn-2")
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record("turn_context", {"turn_id": "later-2", "model": "gpt-5.6-sol"}, 4),
                record("event_msg", {"type": "task_started"}, 5),
            ]
        )
        noend_rows = {row["turn_hash"]: row for row in noend["turns"]}
        self.assertTrue(noend_rows[stable_hash("turn-2")]["later_turn_observed"])
        self.assertEqual(noend["summary"]["no_terminal_with_later_turn"], 1)

    def test_window_start_before_context_and_future_terminal_is_censored(self) -> None:
        records = context() + [
            record("event_msg", {"type": "task_started"}, 0),
            record("event_msg", {"type": "task_complete", "duration_ms": 400}, 3),
        ]
        lifecycle = self.audit(records, since=BASE + 1, until=BASE + 5)
        row = lifecycle["turns"][0]
        self.assertTrue(row["started_before_window"])
        self.assertTrue(row["start_observed"])
        self.assertEqual(row["started_at"], BASE)
        self.assertEqual(row["ended_at"], BASE + 3)
        self.assertEqual(row["state"], "completed")

        future = self.audit(
            context(thread="future-thread", turn="future-turn")
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record("event_msg", {"type": "task_complete"}, 9),
            ],
            since=BASE + 1,
            until=BASE + 5,
        )
        self.assertEqual(future["turns"][0]["state"], "no_terminal_observed")
        self.assertIsNone(future["turns"][0]["ended_at"])

    def test_replay_and_reverse_pages_are_canonical_and_terminal_conflict_is_visible(self) -> None:
        base = context() + [
            record("event_msg", {"type": "task_started"}, 2),
            record("event_msg", {"type": "task_complete", "duration_ms": 10}, 3),
        ]
        first = write_page(self.root, "a.jsonl", base)
        second = write_page(self.root, "b.jsonl", base)
        forward = audit_transcripts([first, second])["lifecycle"]
        reverse = audit_transcripts([second, first])["lifecycle"]
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["summary"]["completed"], 1)
        self.assertGreaterEqual(forward["diagnostics"]["duplicate_events"], 2)

        conflict = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record("event_msg", {"type": "task_complete", "duration_ms": 10}, 3),
                record("event_msg", {"type": "turn_aborted", "duration_ms": 11}, 4),
            ]
        )
        self.assertEqual(conflict["turns"][0]["state"], "conflicted")
        self.assertEqual(conflict["summary"]["conflicted"], 1)
        self.assertGreaterEqual(conflict["diagnostics"]["conflicting_terminal_states"], 1)

    def test_conflicting_timing_makes_state_and_timing_unknown(self) -> None:
        lifecycle = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record("event_msg", {"type": "task_complete", "duration_ms": 10}, 3),
                record("event_msg", {"type": "task_complete", "duration_ms": 11}, 4),
            ]
        )
        row = lifecycle["turns"][0]
        self.assertEqual(row["state"], "conflicted")
        self.assertIsNone(row["duration_ms"])
        self.assertIsNone(row["duration_source"])
        self.assertIsNone(row["ended_at"])
        self.assertGreaterEqual(lifecycle["diagnostics"]["conflicting_terminal_values"], 1)

    def test_future_invalid_events_do_not_change_bounded_diagnostics(self) -> None:
        lifecycle = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record(
                    "event_msg",
                    {"type": "task_complete", "turn_id": None, "duration_ms": 10**400},
                    9,
                ),
            ],
            since=BASE + 1,
            until=BASE + 5,
        )
        self.assertEqual(lifecycle["turns"][0]["state"], "no_terminal_observed")
        self.assertEqual(lifecycle["diagnostics"]["invalid_turn_id"], 0)
        self.assertEqual(lifecycle["diagnostics"]["invalid_duration"], 0)

    def test_later_turn_requires_strict_timestamps_and_ambiguous_next_is_unknown(self) -> None:
        lifecycle = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 2),
                record("event_msg", {"type": "turn_aborted"}, 3),
                record("turn_context", {"turn_id": "later-a", "model": "gpt-5.6-sol"}, 4),
                record("event_msg", {"type": "task_started"}, 5),
                record("turn_context", {"turn_id": "later-b", "model": "gpt-5.6-sol"}, 4),
                record("event_msg", {"type": "task_started"}, 5),
            ]
        )
        first = next(row for row in lifecycle["turns"] if row["turn_hash"] == stable_hash("turn"))
        self.assertTrue(first["later_turn_observed"])
        self.assertIsNone(first["next_turn_hash"])
        self.assertEqual(lifecycle["diagnostics"]["ambiguous_later_turn"], 1)

    def test_shared_session_parent_child_and_invalid_ids_are_isolated(self) -> None:
        records = [
            *context(thread="parent", turn="parent-turn"),
            record("event_msg", {"type": "task_started"}, 2),
            record(
                "session_meta",
                {
                    "id": "child",
                    "parent_thread_id": "parent",
                    "session_id": "shared-session",
                },
                3,
            ),
            record("turn_context", {"turn_id": "child-turn", "model": "gpt-5.6-luna"}, 4),
            record("event_msg", {"type": "task_started"}, 5),
            record("event_msg", {"type": "task_complete"}, 6),
            record("session_meta", {"id": "invalid-boundary", "session_id": "shared-session"}, 7),
            record("turn_context", {"turn_id": "invalid-turn", "model": "gpt-5.6-sol"}, 8),
            record("event_msg", {"type": "task_started", "turn_id": None}, 9),
        ]
        lifecycle = self.audit(records)
        self.assertEqual(len(lifecycle["turns"]), 2)
        self.assertEqual({row["role"] for row in lifecycle["turns"]}, {"parent", "subagent"})
        self.assertGreaterEqual(lifecycle["diagnostics"]["invalid_turn_id"], 1)
        self.assertNotIn(
            stable_hash("shared-session"), {row["thread_hash"] for row in lifecycle["turns"]}
        )

    def test_compactions_deduplicate_window_ids_and_report_missing_context(self) -> None:
        records = context() + [
            record("compacted", {"window_id": "window-1"}, 2),
            record("compacted", {"window_id": "window-1"}, 3),
            record("compacted", {"window_id": "window-2"}, 4),
            record("compacted", {"window_id": "window-3"}, 5),
        ]
        page = write_page(self.root, "compact.jsonl", records)
        missing = write_page(
            self.root,
            "missing.jsonl",
            [record("compacted", {"window_id": "window-4"}, 1)],
        )
        forward = audit_transcripts([page, missing])["lifecycle"]
        reverse = audit_transcripts([missing, page])["lifecycle"]
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["summary"]["compactions"], 4)
        self.assertEqual(forward["summary"]["unattributed_compactions"], 1)
        row = forward["turns"][0]
        self.assertEqual(row["compactions"], 3)
        self.assertEqual(forward["diagnostics"]["duplicate_compactions"], 1)

    def test_pure_interface_discards_unknown_text_and_rejects_unknown_ids(self) -> None:
        report = aggregate_lifecycle(
            [
                {
                    "kind": "task_complete",
                    "thread_hash": None,
                    "turn_hash": None,
                    "in_scope": True,
                    "message": "secret message",
                    "reason": "secret reason",
                }
            ]
        )
        self.assertEqual(report["turns"], [])
        self.assertGreaterEqual(report["diagnostics"]["unattributed_lifecycle_events"], 1)
        self.assertNotIn("secret", json.dumps(report))

    def test_conflicting_lifecycle_and_context_models_stay_unknown(self) -> None:
        report = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started", "model": "gpt-5.6-luna"}, 2),
                record("event_msg", {"type": "task_complete", "model": "gpt-5.6-luna"}, 3),
            ]
        )
        self.assertEqual(report["turns"][0]["model"], "unknown")
        self.assertEqual(report["diagnostics"]["conflicting_model"], 1)

    def test_replayed_start_inside_window_keeps_original_start_evidence(self) -> None:
        report = self.audit(
            context()
            + [
                record("event_msg", {"type": "task_started"}, 0),
                record("event_msg", {"type": "task_started"}, 2),
                record("event_msg", {"type": "task_complete"}, 3),
            ],
            since=BASE + 1,
            until=BASE + 5,
        )
        row = report["turns"][0]
        self.assertTrue(row["start_observed"])
        self.assertTrue(row["started_before_window"])
        self.assertEqual(row["started_at"], BASE)
        self.assertEqual(row["duration_ms"], 3000)


if __name__ == "__main__":
    unittest.main()
