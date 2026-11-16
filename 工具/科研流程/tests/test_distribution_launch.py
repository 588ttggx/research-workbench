"""Released launchers delegate services and keep caches inside their workspace."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'distribution/Launch.ps1'
POWERSHELL = os.environ.get('WORKBENCH_TEST_POWERSHELL', 'powershell.exe')


@unittest.skipUnless(os.name == 'nt', 'Windows launcher')
class ReleaseLauncher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='launch-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / '中文 工作区'
        distribution = self.root / '工具/科研流程/distribution'
        distribution.mkdir(parents=True)
        self.script = distribution / 'Launch.ps1'
        if SOURCE.is_file():
            shutil.copyfile(SOURCE, self.script)
        (self.root / '.research-workbench-release.json').write_text(
            json.dumps({'schema_version': 1, 'release_id': 'test'}), encoding='utf-8')
        (self.root / '工具/工具版本.json').write_text(
            json.dumps({'open_notebook': {'runtime': '工具/OpenNotebook/open-notebook-test'}}), encoding='utf-8')
        manager = self.root / '工具/OpenNotebook/管理服务.ps1'
        manager.parent.mkdir(parents=True)
        manager.write_text(
            "param([string]$Action)\n"
            "$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent\n"
            "@{action=$Action;path=$env:PATH;mpl=$env:MPLCONFIGDIR;dvc=$env:DVC_SITE_CACHE_DIR;"
            "spc=$env:SPC_CACHE_DIR;uv=$env:UV_CACHE_DIR} | ConvertTo-Json | "
            "Set-Content -LiteralPath (Join-Path $root 'called.json') -Encoding UTF8\n",
            encoding='utf-8-sig')
        self.manager = manager
        (self.root / '打开科研区.cmd').write_text('@echo off\r\n', encoding='ascii')

    def call(self, *args, env=None):
        return subprocess.run(
            [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(self.script), *args],
            capture_output=True, encoding='utf-8', errors='replace', timeout=30, env=env)

    def test_managed_service_delegation_and_relocated_cache_paths(self):
        for action in ('start', 'status', 'stop'):
            with self.subTest(action=action):
                result = self.call('-Action', action, '-NoBrowser')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                called = json.loads((self.root / 'called.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(called['action'], action)
                # PowerShell expands Windows 8.3 aliases used by tempfile.
                self.assertEqual(Path(called['mpl']).resolve(), (self.root / 'runtime/cache/matplotlib').resolve())
                self.assertEqual(Path(called['dvc']).resolve(), (self.root / 'runtime/cache/dvc').resolve())
                self.assertEqual(Path(called['spc']).resolve(), (self.root / 'runtime/cache/scholarly').resolve())
                self.assertEqual(Path(called['uv']).resolve(), (self.root / 'runtime/cache/uv').resolve())
                self.assertEqual(Path(called['path'].split(';')[0]).resolve(), (self.root / 'runtime/node').resolve())

    def test_missing_release_marker_prevents_manager_invocation(self):
        (self.root / '.research-workbench-release.json').unlink()
        result = self.call('-Action', 'start', '-NoBrowser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('INVALID_RELEASE', result.stdout + result.stderr)
        self.assertFalse((self.root / 'called.json').exists())

    def test_manager_failure_propagates(self):
        self.manager.write_text("throw 'PORT_OWNERSHIP_REFUSED'\n", encoding='utf-8-sig')
        result = self.call('-Action', 'start', '-NoBrowser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PORT_OWNERSHIP_REFUSED', result.stdout + result.stderr)

    def test_launcher_does_not_change_legacy_manager_strict_mode(self):
        self.manager.write_text("$legacy = @{}\nif ($null -eq $legacy.missing) { Write-Output 'COMPATIBLE' }\n", encoding='utf-8-sig')
        result = self.call('-Action', 'status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('COMPATIBLE', result.stdout)

    def test_shortcut_creation_is_repeatable_and_does_not_start_services(self):
        desktop = self.root / 'test-desktop'
        desktop.mkdir()
        for _ in range(2):
            result = self.call('-Action', 'none', '-CreateShortcut', '-ShortcutDirectory', str(desktop))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((desktop / 'Research Workbench.lnk').is_file())
        self.assertFalse((self.root / 'called.json').exists())

    def test_shortcut_for_another_workspace_is_preserved(self):
        desktop = self.root / 'test-desktop'
        desktop.mkdir()
        shortcut = desktop / 'Research Workbench.lnk'
        other = self.root / 'other-workspace.cmd'
        other.write_text('@echo off\r\n', encoding='ascii')
        env = dict(os.environ, TEST_SHORTCUT=str(shortcut), TEST_TARGET=str(other))
        creation = subprocess.run(
            [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command',
             "$shell=New-Object -ComObject WScript.Shell; $s=$shell.CreateShortcut($env:TEST_SHORTCUT); $s.TargetPath=$env:TEST_TARGET; $s.Save()"],
            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(creation.returncode, 0, creation.stderr)
        before = shortcut.read_bytes()
        result = self.call('-Action', 'none', '-CreateShortcut', '-ShortcutDirectory', str(desktop))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHORTCUT_EXISTS', result.stdout + result.stderr)
        self.assertEqual(shortcut.read_bytes(), before)
        self.assertFalse((self.root / 'called.json').exists())


if __name__ == '__main__':
    unittest.main()
