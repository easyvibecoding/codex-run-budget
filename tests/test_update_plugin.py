from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_plugin import main, preserve_install, prewarm_runtime  # noqa: E402


class UpdateTest(unittest.TestCase):
    @staticmethod
    def make_version(cache: Path, version: str = "0.1.1") -> Path:
        plugin = cache / version
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin/plugin.json").write_text(
            json.dumps({"name": "codex-run-budget"})
        )
        (plugin / "hook.py").write_text("original policy")
        return plugin

    def test_retains_old_version_after_success_or_failure(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "cache"
                old = cache / "0.1.1"
                (old / ".codex-plugin").mkdir(parents=True)
                (old / ".codex-plugin/plugin.json").write_text(
                    json.dumps({"name": "codex-run-budget"})
                )
                (old / "hook.py").write_text("original policy")

                def install():
                    shutil.rmtree(old)
                    (cache / "0.2.1").mkdir()
                    return code

                self.assertEqual(preserve_install(cache, install), code)
                self.assertEqual((old / "hook.py").read_text(), "original policy")
                self.assertTrue((cache / "0.2.1").is_dir())

    def test_rejects_symlink_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            (cache / "linked").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                preserve_install(cache, lambda: self.fail("installer must not run"))

    def test_retains_old_version_when_installer_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            old = cache / "0.2.0"
            (old / ".codex-plugin").mkdir(parents=True)
            (old / ".codex-plugin/plugin.json").write_text(json.dumps({"name": "codex-run-budget"}))

            def install():
                shutil.rmtree(old)
                raise OSError("failed install")

            with self.assertRaises(OSError):
                preserve_install(cache, install)
            self.assertTrue((old / ".codex-plugin/plugin.json").is_file())

    def test_quarantines_replaced_version_symlink_and_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            old = self.make_version(cache)
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "marker"
            marker.write_text("MALICIOUS")

            def install():
                shutil.rmtree(old)
                old.symlink_to(outside, target_is_directory=True)
                return 0

            with self.assertRaises(ValueError):
                preserve_install(cache, install, backup_root=root / "backups")
            self.assertTrue(old.is_dir())
            self.assertFalse(old.is_symlink())
            self.assertEqual((old / "hook.py").read_text(), "original policy")
            self.assertEqual(marker.read_text(), "MALICIOUS")
            self.assertTrue(
                any(path.is_symlink() for path in (root / "backups").rglob("*"))
            )

    def test_quarantines_replaced_cache_symlink_without_touching_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            old = self.make_version(cache)
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "marker"
            marker.write_text("MALICIOUS")

            def install():
                shutil.rmtree(cache)
                cache.symlink_to(outside, target_is_directory=True)
                return 0

            with self.assertRaises(ValueError):
                preserve_install(cache, install, backup_root=root / "backups")
            self.assertTrue(cache.is_dir())
            self.assertFalse(cache.is_symlink())
            self.assertEqual((cache / old.name / "hook.py").read_text(), "original policy")
            self.assertEqual(marker.read_text(), "MALICIOUS")

    def test_changed_same_version_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            old = self.make_version(cache)

            def install():
                (old / "hook.py").write_text("MALICIOUS")
                return 0

            with self.assertRaises(ValueError):
                preserve_install(cache, install, backup_root=root / "backups")
            self.assertEqual((old / "hook.py").read_text(), "original policy")

    def test_data_root_symlink_is_rejected_before_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            data_root = root / "data-link"
            outside = root / "outside"
            outside.mkdir()
            data_root.symlink_to(outside, target_is_directory=True)
            with mock.patch.dict(
                os.environ,
                {"CODEX_RUN_BUDGET_HOME": str(data_root)},
                clear=False,
            ), mock.patch.object(
                sys, "argv", ["update_plugin.py", "--codex-home", str(codex_home)]
            ), mock.patch("update_plugin.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    main()
            run.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])

    def test_dangling_runtime_archive_is_not_treated_as_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            (plugin / "runtime").mkdir(parents=True)
            missing = root / "missing-runtime.pyz"
            (plugin / "runtime/hook.pyz").symlink_to(missing)
            with self.assertRaises(ValueError):
                prewarm_runtime(plugin, root / "data")

    def test_packaged_runtime_prewarms_with_standalone_reminder(self):
        plugin = Path(__file__).resolve().parents[1] / "plugins/codex-run-budget"
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            with mock.patch("update_plugin.subprocess.run") as run:
                self.assertTrue(prewarm_runtime(plugin, data))
            run.assert_not_called()
            runtime = (plugin / "runtime/hook.pyz").read_bytes()
            digest = hashlib.sha256(runtime).hexdigest()
            self.assertEqual((data / "runtimes" / (digest + ".pyz")).read_bytes(), runtime)

    def test_reminder_must_match_exact_source_event_and_count(self):
        source = Path(__file__).resolve().parents[1] / "plugins/codex-run-budget"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            for relative in ("runtime/hook.pyz", "scripts/bootstrap.py", "hooks/hooks.json",
                             "lib/codex_run_budget/update_notice.py"):
                target = plugin / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, target)
            config = plugin / "hooks/hooks.json"
            original = config.read_text()
            for invalid in ("arguments", "event", "duplicate", "no_runtime"):
                with self.subTest(invalid=invalid):
                    hooks = json.loads(original)
                    handlers = hooks["hooks"]["UserPromptSubmit"][0]["hooks"]
                    if invalid == "arguments":
                        handlers[1]["command"] += " extra"
                    elif invalid == "event":
                        hooks["hooks"]["Stop"][0]["hooks"].append(handlers.pop())
                    elif invalid == "duplicate":
                        handlers.append(handlers[1])
                    else:
                        hooks["hooks"] = {"UserPromptSubmit": [{"hooks": [handlers[1]]}]}
                    config.write_text(json.dumps(hooks))
                    with self.assertRaises(ValueError):
                        prewarm_runtime(plugin, root / "data")
                    self.assertFalse((root / "data").exists())
