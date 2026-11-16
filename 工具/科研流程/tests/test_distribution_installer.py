"""Exercise the Windows installer using isolated, deliberately hostile payloads."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "distribution" / "Install.ps1"
POWERSHELL = os.environ.get("WORKBENCH_TEST_POWERSHELL", "powershell.exe")


@unittest.skipUnless(os.name == "nt", "The distribution installer targets Windows")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="installer-test-")
        self.root = Path(self.temp.name)
        self.payload = self.root / "发行 文件"
        self.payload.mkdir()
        self.target = self.root / "安装 中文 空格"
        self.archive = self.payload / "core.zip"
        self.manifest = {
            "schema_version": 1,
            "repository": "example/research-workbench",
            "release_id": "v0.1.0-test",
            "installation": {
                "python": "runtime/python313/python.exe",
                "initializer": "工具/科研流程/distribution/initialize.py",
            },
            "components": [],
        }
        self.write_zip({"说明/测试.txt": "safe fixture"})

    def tearDown(self):
        self.temp.cleanup()

    def write_zip(self, entries):
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as output:
            for name, content in entries.items():
                output.writestr(name, content)
        self.update_component()

    def update_component(self):
        self.manifest["components"] = [{
            "id": "core", "archive": "core.zip", "required": True,
            "extract_to": ".", "size_bytes": self.archive.stat().st_size,
            "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            "url": "https://github.com/example/research-workbench/releases/download/v0.1.0-test/core.zip",
        }]

    def run_installer(self, *args):
        path = self.payload / "manifest.json"
        path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
             "-ManifestPath", str(path), "-InstallDir", str(self.target),
             "-Offline", "-NoLaunch", "-NoShortcut", *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        )

    def assert_rejected(self, result, reason):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stdout + result.stderr)

    def test_verifies_offline_payload_in_unicode_directory_without_installing(self):
        result = self.run_installer("-VerifyOnly")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VERIFIED", result.stdout)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".research-install-*")), [])

    def test_refuses_existing_user_data_before_installation(self):
        self.target.mkdir()
        original = self.target / "original.txt"
        original.write_text("keep", encoding="utf-8")
        result = self.run_installer()
        self.assert_rejected(result, "TARGET_NOT_EMPTY")
        self.assertEqual(original.read_text(encoding="utf-8"), "keep")

    def test_rejects_hash_mismatch(self):
        self.manifest["components"][0]["sha256"] = "0" * 64
        self.assert_rejected(self.run_installer("-VerifyOnly"), "HASH_MISMATCH")

    def test_rejects_size_mismatch(self):
        self.manifest["components"][0]["size_bytes"] += 1
        self.assert_rejected(self.run_installer("-VerifyOnly"), "SIZE_MISMATCH")

    def test_refuses_missing_offline_component(self):
        self.archive.unlink()
        self.assert_rejected(self.run_installer("-VerifyOnly"), "OFFLINE_COMPONENT_MISSING")

    def test_rejects_zip_traversal_without_writing_outside_staging(self):
        self.write_zip({"../escaped.txt": "unsafe"})
        self.assert_rejected(self.run_installer("-VerifyOnly"), "UNSAFE_PATH")
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_rejects_windows_absolute_and_alternate_stream_paths(self):
        for path in ("C:" + "/escaped.txt", "/absolute.txt", "safe.txt:secret", "folder/CON.txt", "folder./file.txt"):
            with self.subTest(path=path):
                self.write_zip({path: "unsafe"})
                self.assert_rejected(self.run_installer("-VerifyOnly"), "UNSAFE_PATH")

    def test_rejects_symlink_zip_entry(self):
        info = zipfile.ZipInfo("shortcut")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as output:
            output.writestr(info, "../outside")
        self.update_component()
        self.assert_rejected(self.run_installer("-VerifyOnly"), "ZIP_LINK")

    def test_rejects_case_colliding_entries(self):
        self.write_zip({"Folder/File.txt": "first", "folder/file.txt": "second"})
        self.assert_rejected(self.run_installer("-VerifyOnly"), "ZIP_COLLISION")

    def test_rejects_archive_path_in_manifest(self):
        self.manifest["components"][0]["archive"] = "../core.zip"
        self.assert_rejected(self.run_installer("-VerifyOnly"), "INVALID_ARCHIVE")

    def test_rejects_unrelated_release_url_even_with_local_archive(self):
        self.manifest["components"][0]["url"] = "https://example.org/core.zip"
        self.assert_rejected(self.run_installer("-VerifyOnly"), "INVALID_RELEASE_URL")

    def test_optional_components_are_not_required_by_default(self):
        optional = dict(self.manifest["components"][0], id="optional", archive="optional.zip", required=False,
                        url="https://github.com/example/research-workbench/releases/download/v0.1.0-test/optional.zip")
        self.manifest["components"].append(optional)
        result = self.run_installer("-VerifyOnly")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_setup_can_use_verified_archives_beside_its_executable(self):
        assets = self.root / 'setup-assets'
        assets.mkdir()
        self.archive.rename(assets / self.archive.name)
        result = self.run_installer('-VerifyOnly', '-AssetDirectory', str(assets))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selecting_group_in_csv_installs_every_group_part(self):
        for component_id in ('qwen4b-part1', 'qwen4b-part2', 'ollama'):
            archive = self.payload / (component_id + '.zip')
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('optional/' + component_id + '.txt', 'fixture')
            self.manifest['components'].append({
                'id': component_id, 'archive': archive.name, 'group': 'qwen4b',
                'required': False, 'extract_to': '.', 'size_bytes': archive.stat().st_size,
                'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'url': 'https://github.com/example/research-workbench/releases/download/v0.1.0-test/' + archive.name,
            })
        result = self.run_installer('-VerifyOnly', '-Components', 'qwen4b,core')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('VERIFIED: 4 components', result.stdout)
        (self.payload / 'qwen4b-part2.zip').unlink()
        self.assert_rejected(self.run_installer('-VerifyOnly', '-Components', 'qwen4b'), 'OFFLINE_COMPONENT_MISSING')

    def test_unknown_optional_selection_fails(self):
        self.assert_rejected(self.run_installer("-VerifyOnly", "-Components", "unknown"), "UNKNOWN_COMPONENT")

    def test_rejects_target_under_directory_junction_without_touching_original(self):
        original = self.root / "original"
        original.mkdir()
        sentinel = original / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        junction = self.root / "junction"
        env = dict(os.environ, TEST_JUNCTION_PATH=str(junction), TEST_JUNCTION_TARGET=str(original))
        creation = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:TEST_JUNCTION_PATH -Target $env:TEST_JUNCTION_TARGET | Out-Null"],
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(creation.returncode, 0, creation.stderr)
        try:
            self.target = junction / "new-workspace"
            self.assert_rejected(self.run_installer("-VerifyOnly"), "PATH_LINK")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            self.assertFalse((original / "new-workspace").exists())
        finally:
            junction.rmdir()  # Remove this test-created junction itself, never its target.

    def add_minimal_python(self, initializer):
        """Bundle a real interpreter, isolated by _pth; no installed-Python fallback."""
        base = Path(sys._base_executable).parent
        version = f"python{sys.version_info.major}{sys.version_info.minor}"
        with zipfile.ZipFile(self.archive, "a", zipfile.ZIP_STORED) as output:
            for name in ("python.exe", f"{version}.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
                source = base / name
                if source.exists():
                    output.write(source, "runtime/python313/" + name)
            output.writestr(f"runtime/python313/{version}._pth", "Lib\n../../\n")
            for source in (base / "Lib" / "encodings").glob("*.py"):
                output.write(source, "runtime/python313/Lib/encodings/" + source.name)
            output.writestr("工具/科研流程/distribution/initialize.py", initializer)
        self.update_component()

    def test_installs_and_initializes_real_bundled_python_then_refuses_overwrite(self):
        self.add_minimal_python(
            "import sys\n"
            "root = sys.argv[sys.argv.index('--workspace-root') + 1]\n"
            "assert '--no-shortcut' in sys.argv and '--no-launch' in sys.argv\n"
            "with open(root + '/initialized.txt', 'w', encoding='utf-8') as f: f.write(root)\n"
        )
        self.target.mkdir()  # An explicitly empty destination is also supported.
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        initialized_root = Path((self.target / "initialized.txt").read_text(encoding="utf-8"))
        self.assertTrue(initialized_root.samefile(self.target))
        status = json.loads((self.target / "installation-status.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(status["status"], "complete")
        self.assertFalse(Path(str(self.target) + ".install-lock").exists())
        self.assert_rejected(self.run_installer(), "TARGET_NOT_EMPTY")
        self.assertTrue((self.target / "initialized.txt").exists())

    def test_initializer_failure_preserves_new_install_with_failure_status(self):
        self.add_minimal_python("raise SystemExit(9)\n")
        result = self.run_installer()
        self.assert_rejected(result, "INITIALIZATION_FAILED")
        self.assertTrue((self.target / "runtime/python313/python.exe").is_file())
        failure = json.loads((self.target / "install-failed.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(failure["status"], "failed")
        self.assertFalse((self.target / "installation-status.json").exists())
        self.assertFalse(Path(str(self.target) + ".install-lock").exists())


if __name__ == "__main__":
    unittest.main()
