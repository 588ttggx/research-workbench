"""Exercise RSpace registration paths without running WSL or Docker."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1]
SERVICE = MODULE.parent / 'OpenNotebook/管理服务.ps1'
sys.path.insert(0, str(MODULE))


@unittest.skipUnless(os.name == 'nt', 'Windows RSpace runtime registration')
class RSpaceRuntimeRegistration(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='rspace-registration-'))
        self.root = Path(temporary).resolve() / '迁入 工作台'
        self.runtime = self.root / 'runtime/RSpace'
        self.runtime.mkdir(parents=True)
        (self.runtime / 'compose.yaml').write_text('services: {}\n', encoding='utf-8')

    @staticmethod
    def powershell_path(root, registered):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        script = '\n'.join([
            "$ErrorActionPreference = 'Stop'",
            '$tokens = $null; $errors = $null',
            '$ast = [System.Management.Automation.Language.Parser]::ParseFile('
            + quote(SERVICE) + ', [ref]$tokens, [ref]$errors)',
            "if ($errors.Count) { throw 'Service manager syntax is invalid.' }",
            '$definition = $ast.Find({ param($node) $node -is '
            '[System.Management.Automation.Language.FunctionDefinitionAst] '
            "-and $node.Name -eq 'Resolve-RSpaceRuntime' }, $true)",
            ". ([scriptblock]::Create($definition.Extent.Text))",
            '$resolved = Resolve-RSpaceRuntime ' + quote(registered) + ' ' + quote(root),
            'if ($resolved -cne ' + quote(root / 'runtime/RSpace') + ") { throw 'Wrong runtime directory.' }",
        ])
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                              capture_output=True, timeout=30)

    def test_registered_relative_runtime_moves_with_workspace(self):
        import rspace_runtime

        with patch.object(rspace_runtime.w, 'ROOT', self.root):
            self.assertEqual(rspace_runtime.runtime_path('runtime/RSpace'), self.runtime)
        result = self.powershell_path(self.root, 'runtime/RSpace')
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_arbitrary_relative_path_cannot_register_a_compose_file(self):
        import rspace_runtime

        with patch.object(rspace_runtime.w, 'ROOT', self.root):
            with self.assertRaises(ValueError):
                rspace_runtime.runtime_path('runtime/../runtime/RSpace')
        self.assertNotEqual(self.powershell_path(self.root, 'runtime/../runtime/RSpace').returncode, 0)

    def test_directory_named_compose_file_is_rejected(self):
        import rspace_runtime

        compose = self.runtime / 'compose.yaml'
        compose.unlink()
        compose.mkdir()
        with patch.object(rspace_runtime.w, 'ROOT', self.root):
            for registered in ('runtime/RSpace', str(self.runtime)):
                with self.subTest(registered=registered):
                    with self.assertRaises(ValueError):
                        rspace_runtime.runtime_path(registered)
                    self.assertNotEqual(self.powershell_path(self.root, registered).returncode, 0)

    def test_portable_registration_cannot_follow_a_directory_junction(self):
        import rspace_runtime

        outside = self.root.parent / '另一个部署'
        self.runtime.rename(outside)
        script = "New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null".format(
            str(self.runtime).replace("'", "''"), str(outside).replace("'", "''"))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                 base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue(self.runtime.is_junction())
        with patch.object(rspace_runtime.w, 'ROOT', self.root):
            with self.assertRaises(ValueError):
                rspace_runtime.runtime_path('runtime/RSpace')
        self.assertNotEqual(self.powershell_path(self.root, 'runtime/RSpace').returncode, 0)


if __name__ == '__main__':
    unittest.main()
