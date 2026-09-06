from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_plugin import preserve_install  # noqa: E402


class UpdateTest(unittest.TestCase):
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
