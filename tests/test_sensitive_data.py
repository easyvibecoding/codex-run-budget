from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_sensitive_data import (  # noqa: E402
    ScanError,
    main,
    scan_bytes,
    scan_history,
    scan_index,
    scan_worktree,
)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, env=env)


class SensitiveDataTest(unittest.TestCase):
    def test_provider_secret_assignment_is_redacted(self) -> None:
        # Build the high-signal value in pieces so this test source is safe to
        # commit and does not become its own scanner fixture.
        prefix = "sk" + "-"
        value = (prefix + ("a" * 28)).encode()
        key = b"api" + b"_key"
        findings = scan_bytes(
            key
            + b' = "placeholder"; '
            + key
            + b' = "'
            + value
            + b'"  # example.invalid\n',
            "fixture.py",
        )
        self.assertEqual(len(findings), 2)
        self.assertEqual(
            {item.rule for item in findings}, {"provider-token", "credential-assignment"}
        )
        for item in findings:
            self.assertNotIn(value.decode(), item.fingerprint)
            self.assertEqual(item.path, "fixture.py")
            self.assertEqual(item.line, 1)
            self.assertEqual(item.category, "secret")

    def test_key_and_placeholder_values_are_not_overreported(self) -> None:
        text = b"token_count = 123\ntask_hash = '" + (b"a" * 64) + b"'\n"
        text += b'api_key = "example.invalid-placeholder"\n'
        text += b'authors = [{"name": "EasyVibeCoding"}]\n'
        self.assertEqual(scan_bytes(text, "README.md"), [])

    def test_private_path_task_id_and_artifact_content(self) -> None:
        task_id = b"11111111-1111-7111-8111-111111111111"
        private_path = b"/" + b"Users/" + b"private-owner/Documents/project"
        second_path = b"/" + b"home/" + b"private-owner/worktree"
        data = (
            b'{"task_id":"'
            + task_id
            + b'","prompt":"This is a private workflow sample that must not be committed",'
            b'"path":"'
            + private_path
            + b'","other":"'
            + second_path
            + b'"}\n'
        )
        findings = scan_bytes(data, "outputs/actual-report.json")
        rules = {item.rule for item in findings}
        self.assertIn("private-artifact-file", rules)
        self.assertIn("task-identifier", rules)
        self.assertIn("task-content-artifact", rules)
        self.assertIn("private-absolute-path", rules)
        self.assertNotIn(private_path.decode(), json.dumps([item.__dict__ for item in findings]))
        self.assertNotIn(task_id.decode(), json.dumps([item.__dict__ for item in findings]))

    def test_private_email_phone_and_network_are_detected_in_artifact(self) -> None:
        data = (
            b'{"contact":"someone@corp.test","phone":"0912-345-678",'
            b'"host":"10.22.3.9","service":"db.internal"}\n'
        )
        findings = scan_bytes(data, "outputs/session-export.json")
        self.assertEqual(
            {item.rule for item in findings},
            {
                "private-artifact-file",
                "private-email-artifact",
                "private-phone-artifact",
                "private-network-address",
                "private-hostname",
            },
        )

    def test_examples_and_public_author_metadata_are_allowed(self) -> None:
        data = (
            b'contact: owner@example.com\n'
            b'api_key: "example.invalid"\n'
            b'homepage: https://example.com/project\n'
            b'copyright: EasyVibeCoding\n'
        )
        self.assertEqual(scan_bytes(data, "NOTICE.md"), [])

    def test_zip_members_are_scanned_without_leaking_member_content(self) -> None:
        prefix = b"gh" + b"p_"
        token = prefix + (b"b" * 28)
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr(
                "reports/actual.json", b'{"api' + b'_key":"' + token + b'"}\n'
            )
        findings = scan_bytes(archive.getvalue(), "runtime/hook.pyz")
        self.assertTrue(findings)
        self.assertTrue(any("!reports/actual.json" in item.path for item in findings))
        serialized = json.dumps([item.__dict__ for item in findings])
        self.assertNotIn(token.decode(), serialized)
        self.assertTrue(all(item.fingerprint.startswith("sha256:") for item in findings))

    def test_html_and_markdown_generated_reports_are_artifacts(self) -> None:
        body = b"A generated report may contain private task metadata."
        for path in ("outputs/codex-turn-preview.html", "outputs/usage-summary.md"):
            with self.subTest(path=path):
                findings = scan_bytes(body, path)
                self.assertIn("private-artifact-file", {item.rule for item in findings})

    def test_zip_limits_and_read_errors_fail_closed(self) -> None:
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("safe.txt", "safe")
        with mock.patch("check_sensitive_data.MAX_ZIP_DEPTH", 0):
            findings = scan_bytes(archive.getvalue(), "runtime.pyz")
        self.assertIn("oversized-zip-depth", {item.rule for item in findings})
        with mock.patch("check_sensitive_data.MAX_ZIP_TOTAL_BYTES", 0):
            findings = scan_bytes(archive.getvalue(), "runtime.pyz")
        self.assertIn("oversized-zip-total", {item.rule for item in findings})
        with mock.patch(
            "check_sensitive_data.zipfile.ZipFile.read", side_effect=RuntimeError("redacted")
        ), self.assertRaises(ScanError):
            scan_bytes(archive.getvalue(), "runtime.pyz")
        with mock.patch(
            "check_sensitive_data.zipfile.ZipFile.read", side_effect=zlib.error("corrupt")
        ), self.assertRaises(ScanError):
            scan_bytes(archive.getvalue(), "runtime.pyz")
        with self.assertRaises(ScanError):
            scan_bytes(b"PK\x03\x04not-a-valid-archive", "runtime.pyz")
        empty = BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        findings = scan_bytes(empty.getvalue(), "runtime.pyz")
        self.assertIn("empty-zip-artifact", {item.rule for item in findings})
        with mock.patch(
            "check_sensitive_data.zipfile.ZipFile.infolist", side_effect=RuntimeError("redacted")
        ), self.assertRaises(ScanError):
            scan_bytes(archive.getvalue(), "runtime.pyz")

    def test_git_read_errors_are_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            with mock.patch("check_sensitive_data._git", side_effect=ScanError("unavailable")):
                with self.assertRaises(ScanError):
                    scan_index(repo)
                with self.assertRaises(ScanError):
                    scan_history(repo)

    def test_control_characters_in_paths_are_escaped(self) -> None:
        prefix = "sk" + "-"
        value = (prefix + ("e" * 28)).encode()
        findings = scan_bytes(b'api' + b'_key="' + value + b'"', "unsafe\nname.txt")
        self.assertTrue(findings)
        self.assertNotIn("\n", findings[0].path)
        self.assertIn("\\x0a", findings[0].path)

    def test_sensitive_path_names_are_fingerprinted(self) -> None:
        private_path = "/" + "Users/" + "private-owner/secret.txt"
        findings = scan_bytes(b"safe", private_path)
        self.assertEqual({item.rule for item in findings}, {"sensitive-path-name"})
        self.assertTrue(findings[0].path.startswith("<redacted-path-"))
        self.assertNotIn("private-owner", findings[0].path)

    def test_credential_like_path_names_are_fingerprinted(self) -> None:
        key = "api" + "_key"
        value = "z" * 28
        path = key + "=" + value + ".txt"
        findings = scan_bytes(b"sk" + b"-" + (b"g" * 28), path)
        self.assertTrue(findings)
        self.assertTrue(findings[0].path.startswith("<redacted-path-"))
        self.assertNotIn(value, findings[0].path)

    def test_index_scans_staged_content_not_worktree_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.name", "Scanner Test")
            _git(repo, "config", "user.email", "scanner@example.invalid")
            target = repo / "config.txt"
            secret = "sk" + "-" + ("c" * 28)
            key = "api" + "_key"
            target.write_text(key + ' = "' + secret + '"\n', encoding="utf-8")
            _git(repo, "add", "config.txt")
            target.write_text("safe\n", encoding="utf-8")
            staged = scan_index(repo)
            worktree = scan_worktree(repo)
            self.assertTrue(any(item.rule == "provider-token" for item in staged))
            self.assertTrue(any(item.rule == "credential-assignment" for item in staged))
            self.assertEqual(worktree, [])

    def test_worktree_audit_sees_ignored_local_private_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
            secret = "sk" + "-" + ("f" * 28)
            key = "api" + "_key"
            (repo / ".env").write_text(key + "=" + secret + "\n", encoding="utf-8")
            findings = scan_worktree(repo)
            self.assertTrue(any(item.rule == "local-private-file" for item in findings))
            self.assertTrue(any(item.rule == "provider-token" for item in findings))
            self.assertTrue(all("sk-" not in item.fingerprint for item in findings))

    def test_reachable_history_includes_removed_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Scanner Test",
                "GIT_AUTHOR_EMAIL": "scanner@example.invalid",
                "GIT_COMMITTER_NAME": "Scanner Test",
                "GIT_COMMITTER_EMAIL": "scanner@example.invalid",
            }
            target = repo / "removed.txt"
            secret = "sk" + "-" + ("d" * 28)
            key = "api" + "_key"
            target.write_text(key + ' = "' + secret + '"\n', encoding="utf-8")
            _git(repo, "add", "removed.txt")
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True, env=env
            )
            target.unlink()
            _git(repo, "add", "-u")
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "remove"], check=True, env=env
            )
            findings = scan_history(repo)
            self.assertTrue(any(item.path.startswith("history/") for item in findings))
            self.assertTrue(any(item.rule == "provider-token" for item in findings))
            self.assertTrue(all(secret not in item.fingerprint for item in findings))

    def test_cli_json_is_redacted_and_history_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            (repo / "safe.txt").write_text("token_count=1\n", encoding="utf-8")
            _git(repo, "add", "safe.txt")
            output = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_sensitive_data.py"),
                    "--index",
                    "--json",
                    "--repo",
                    str(repo),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(output.stdout), [])
            self.assertEqual(main(["--history", "--repo", str(repo)]), 0)
            failed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_sensitive_data.py"),
                    "--index",
                    "--json",
                    "--repo",
                    str(repo / "not-a-repository"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 2)
            error = json.loads(failed.stdout)["error"]
            self.assertEqual(error["rule"], "scan-source-unavailable")
            self.assertNotIn("not-a-repository", json.dumps(error))


if __name__ == "__main__":
    unittest.main()
