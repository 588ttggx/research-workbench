"""Exercise the actual frontend command AST without running any managed service."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SERVICE = Path(__file__).resolve().parents[2] / 'OpenNotebook/管理服务.ps1'
POWERSHELL = os.environ.get('WORKBENCH_TEST_POWERSHELL', 'powershell.exe')


@unittest.skipUnless(os.name == 'nt', 'Windows managed-service launcher')
class DistributionServiceTests(unittest.TestCase):
    def command(self, standalone=False, directory=False):
        with tempfile.TemporaryDirectory(prefix='frontend-service-test-') as temporary:
            app = Path(temporary) / '应用 空格'
            frontend = app / 'frontend'
            frontend.mkdir(parents=True)
            if standalone:
                (frontend / 'server.js').write_text('// isolated fixture, never executed\n', encoding='utf-8')
            if directory:
                (frontend / 'server.js').mkdir()
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = '\n'.join([
                "$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null",
                "$ast=[System.Management.Automation.Language.Parser]::ParseFile("+quote(SERVICE)+",[ref]$tokens,[ref]$errors)",
                "if ($errors.Count) { throw 'Service manager syntax is invalid.' }",
                "$definition=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-FrontendArguments'},$true)",
                "if ($definition) { . ([scriptblock]::Create($definition.Extent.Text)) }",
                "$appRoot="+quote(app)+"; $nodePath='node.exe'",
                "$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -in @('$env:PORT','$env:HOSTNAME','$env:NEXT_TELEMETRY_DISABLED')},$true) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }",
                "function Start-OwnedProcess([string]$Name,[string]$Executable,[string[]]$Arguments,[string]$WorkingDirectory,[int]$Port=0) {",
                "  @{name=$Name; executable=$Executable; arguments=@($Arguments); cwd=$WorkingDirectory; port=$Port; environment=@{PORT=$env:PORT;HOSTNAME=$env:HOSTNAME;NEXT_TELEMETRY_DISABLED=$env:NEXT_TELEMETRY_DISABLED}} | ConvertTo-Json -Depth 4 -Compress",
                "}",
                "$command=$ast.Find({param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Start-OwnedProcess' -and $node.CommandElements.Count -gt 1 -and $node.CommandElements[1].Value -eq 'frontend'},$true)",
                "if (-not $command) { throw 'Managed frontend start command is missing.' }",
                ". ([scriptblock]::Create($command.Extent.Text))",
            ])
            result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            value = json.loads(result.stdout.decode('utf-8-sig', errors='replace'))
            self.assertEqual(value['name'], 'frontend')
            self.assertEqual(value['executable'], 'node.exe')
            self.assertEqual(Path(value['cwd']), frontend)
            self.assertEqual(value['port'], 8502)
            self.assertEqual(value['environment'], {'PORT': '8502', 'HOSTNAME': '127.0.0.1', 'NEXT_TELEMETRY_DISABLED': '1'})
            return value['arguments']

    def test_standalone_frontend_uses_server_script(self):
        self.assertEqual(self.command(standalone=True), ['server.js'])

    def test_existing_frontend_keeps_exact_next_start_arguments(self):
        self.assertEqual(self.command(), ['node_modules\\next\\dist\\bin\\next', 'start',
                                         '--hostname', '127.0.0.1', '--port', '8502'])

    def test_directory_named_server_is_not_a_standalone_entrypoint(self):
        self.assertEqual(self.command(directory=True), ['node_modules\\next\\dist\\bin\\next', 'start',
                                                       '--hostname', '127.0.0.1', '--port', '8502'])


if __name__ == '__main__':
    unittest.main()
