param(
    [ValidateSet('start','stop','status','restart-workflow','recover-workflow','start-document-parser','stop-document-parser','status-document-parser')][string]$Action = 'start',
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
function Resolve-ServicePath([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    for ($hop=0; $hop -lt 32; $hop++) {
        $component=$resolved; $changed=$false
        while ($component) {
            if (Test-Path -LiteralPath $component) {
                $item=Get-Item -LiteralPath $component -Force
                if ($item.LinkType -in @('Junction','SymbolicLink')) {
                    $target=@($item.Target)[0]
                    if (-not $target) { throw 'Cannot resolve service path link.' }
                    # Junction targets surface as Global\..., \??\... or \\?\...;
                    # combine the plain path so GetFullPath stays valid.
                    if ($target.StartsWith('Global\')) { $target=$target.Substring(7) }
                    elseif ($target.StartsWith('\??\')) { $target=$target.Substring(4) }
                    elseif ($target.StartsWith('\\?\')) { $target=$target.Substring(4) }
                    if (-not [IO.Path]::IsPathRooted($target)) { $target=Join-Path $item.Parent.FullName $target }
                    $resolved=[IO.Path]::GetFullPath($target+$resolved.Substring($item.FullName.Length))
                    $changed=$true; break
                }
            }
            $parent=[IO.Path]::GetDirectoryName($component)
            if ($parent -eq $component) { break }; $component=$parent
        }
        if (-not $changed) { return $resolved }
    }
    throw 'Service path has too many links.'
}
$serviceRoot = Resolve-ServicePath $PSScriptRoot
$versionsPath = Join-Path (Split-Path $serviceRoot -Parent) '工具版本.json'
$appRoot = if (Test-Path -LiteralPath $versionsPath) {
    $researchVersions = Get-Content -LiteralPath $versionsPath -Encoding UTF8 -Raw | ConvertFrom-Json
    Join-Path (Split-Path (Split-Path $serviceRoot -Parent) -Parent) $researchVersions.open_notebook.runtime
} else { Join-Path $serviceRoot 'open-notebook-1.15.0' }
$logRoot = Join-Path (Split-Path $serviceRoot -Parent) '日志'
$statePath = Join-Path $serviceRoot '进程.json'
function Open-ProcessStateLock {
    $lockPath = Join-Path $serviceRoot '.process-state.lock'
    $deadline = [datetime]::UtcNow.AddSeconds(45)
    do {
        try { return [IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
        catch [IO.IOException] {
            if (($_.Exception.HResult -band 0xffff) -notin @(32,33) -or [datetime]::UtcNow -ge $deadline) { throw }
            Start-Sleep -Milliseconds 100
        }
    } while ($true)
}
function Save-ProcessState {
    $temporary = $statePath+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try {
        [IO.File]::WriteAllText($temporary,($tracked | ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
        if ([IO.File]::Exists($statePath)) { [IO.File]::Replace($temporary,$statePath,[NullString]::Value) }
        else { [IO.File]::Move($temporary,$statePath) }
    } finally {
        [IO.File]::Delete($temporary)
    }
}
$stateLock = if ($Action -notin @('status','status-document-parser')) { Open-ProcessStateLock }
try {
$tracked = @{}
if (Test-Path -LiteralPath $statePath) {
    $saved = Get-Content -LiteralPath $statePath -Encoding UTF8 -Raw | ConvertFrom-Json
    foreach ($entry in $saved.PSObject.Properties) { $tracked[$entry.Name] = $entry.Value }
}
function Invoke-ShortWsl {
    param([string[]]$Arguments,[ValidateRange(1,180)][int]$TimeoutSeconds=30)
    $capture = Join-Path $logRoot ('wsl-query-'+[guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($capture) | Out-Null
    $stdout = Join-Path $capture 'stdout'
    $stderr = Join-Path $capture 'stderr'
    $process = $null
    try {
        # Start-Process gives WSL its own hidden console when our caller has none.
        # Quote Windows argv explicitly; every caller below supplies known arguments.
        $nativeArguments = @($Arguments | ForEach-Object {
            if ($_ -and $_ -notmatch '[\s"]') { $_ }
            else { '"' + (($_ -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' }
        })
        $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\wsl.exe') -ArgumentList $nativeArguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        # Cache the handle before exit so Windows PowerShell retains ExitCode.
        $null = $process.Handle
        $watch = [Diagnostics.Stopwatch]::StartNew()
        while (-not $process.WaitForExit(50)) {
            foreach ($file in @($stdout,$stderr)) {
                if ([IO.File]::Exists($file) -and (Get-Item -LiteralPath $file).Length -gt 65536) { throw 'Short WSL query exceeded its capture limit.' }
            }
            if ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw 'Short WSL query timed out.' }
        }
        $process.WaitForExit() | Out-Null
        foreach ($file in @($stdout,$stderr)) {
            if ((Get-Item -LiteralPath $file).Length -gt 65536) { throw 'Short WSL query exceeded its capture limit.' }
        }
        $code = $process.ExitCode
        if ($null -eq $code) { throw 'Short WSL query did not provide an exit code.' }
        return [pscustomobject]@{exit_code=[int]$code;
            stdout=[IO.File]::ReadAllText($stdout,[Text.Encoding]::UTF8);
            stderr=[IO.File]::ReadAllText($stderr,[Text.Encoding]::UTF8)}
    } finally {
        try {
            if ($process -and -not $process.HasExited) { Stop-OwnedProcessTree $process }
        } finally {
            if ($process) { $process.Dispose() }
            foreach ($file in @($stdout,$stderr)) { [IO.File]::Delete($file) }
            [IO.Directory]::Delete($capture)
        }
    }
}
function Invoke-DocumentHost([string]$Operation,$Entry) {
    if (-not $Entry.linux_nonce -or -not $Entry.linux_host -or -not $Entry.linux_receipt) {
        throw 'Document inference ownership receipt is incomplete.'
    }
    $result = Invoke-ShortWsl -Arguments @('-d','Ubuntu-24.04','--exec','/usr/bin/python3','-B',$Entry.linux_host,$Operation,'--receipt',$Entry.linux_receipt,'--nonce',$Entry.linux_nonce) -TimeoutSeconds 45
    if ($result.exit_code -ne 0 -or [string]::IsNullOrWhiteSpace($result.stdout)) { throw 'Could not verify the owned Linux document process.' }
    return ($result.stdout | ConvertFrom-Json)
}
function Get-OwnedProcess([string]$Name) {
    if (-not $tracked.ContainsKey($Name)) { return $null }
    $entry = $tracked[$Name]
    $started = [datetime]::MinValue
    if (-not $entry.id) { return $null }
    if ($entry.started -is [datetime]) { $started = $entry.started }
    elseif (-not [datetime]::TryParse([string]$entry.started, [ref]$started)) { return $null }
    $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $started.ToUniversalTime().Ticks) {
        if ($Name -eq 'document-parser') {
            $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
            $expectedWsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
            if ($native.ExecutablePath -ne $expectedWsl -or $native.CommandLine -notmatch 'document_vlm_host\.py.*supervise') { return $null }
        }
        if ($Name -eq 'rspace-helper') {
            $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
            $expectedWsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
            $expectedCommand = '^\s*"?' + [regex]::Escape($expectedWsl) + '"?\s+-d\s+Ubuntu-24\.04\s+--exec\s+sleep\s+2147483647\s*$'
            if ($native.ExecutablePath -ne $expectedWsl -or $native.CommandLine -notmatch $expectedCommand) { return $null }
        }
        if ($Name -eq 'workflow') {
            try { $listener = Get-WorkflowListener } catch { return $null }
            if (-not $listener) {
                $starting = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
                if ($starting.ProcessId -eq $process.Id -and (Test-WorkflowIdentity $starting)) { return $process }
                return $null
            }
            if ($listener.Id -eq $process.Id) { return $listener }
            $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.Id)"
            $delta = ($listener.StartTime - $process.StartTime).TotalSeconds
            if ($native.ParentProcessId -eq $process.Id -and $delta -ge 0 -and $delta -lt 60) { return $listener }
            return $null
        }
        return $process
    }
    return $null
}
function Test-WorkflowIdentity($Native) {
    if (-not $Native) { return $false }
    $workflowRoot = Join-Path (Split-Path $serviceRoot -Parent) '科研流程'
    $expectedPython = Resolve-ServicePath (Join-Path $workflowRoot '.venv\Scripts\python.exe')
    $configPath = Join-Path $workflowRoot '.venv\pyvenv.cfg'
    # pyvenv.cfg is UTF-8; the Windows PowerShell default read would garble a
    # non-ASCII base install path and reject the workspace's own listener.
    $homeLine = Get-Content -LiteralPath $configPath -Encoding UTF8 | Where-Object { $_ -match '^home\s*=' } | Select-Object -First 1
    if (-not $homeLine) { $homeLine = Get-Content -LiteralPath $configPath | Where-Object { $_ -match '^home\s*=' } | Select-Object -First 1 }
    if (-not $homeLine) { return $false }
    $basePython = Resolve-ServicePath (Join-Path (($homeLine -split '=',2)[1].Trim()) 'python.exe')
    if ($Native.CommandLine -notmatch '^\s*(?:"([^"]+)"|(\S+))\s+(?:-u\s+)?(?:"([^"]+)"|(\S+))\s+serve\s*$') { return $false }
    $pythonArgument=if($matches[1]){$matches[1]}else{$matches[2]}
    $scriptArgument=if($matches[3]){$matches[3]}else{$matches[4]}
    try {
        if ((Resolve-ServicePath $pythonArgument) -ne $expectedPython) { return $false }
        if ($scriptArgument -ne 'workflow.py' -and (Resolve-ServicePath $scriptArgument) -ne (Resolve-ServicePath (Join-Path $workflowRoot 'workflow.py'))) { return $false }
        return (Resolve-ServicePath $Native.ExecutablePath) -in @($expectedPython,$basePython)
    } catch { return $false }
}
function Get-WorkflowListener {
    $listeners = @(Get-NetTCPConnection -LocalPort 8503 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($listeners.Count -eq 0) { return $null }
    if ($listeners.Count -ne 1) { throw 'Multiple workflow listeners; refusing process recovery.' }
    $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0])"
    if (-not (Test-WorkflowIdentity $native)) { throw 'Port 8503 does not match this workspace executable and workflow command; refusing process recovery.' }
    return Get-Process -Id $native.ProcessId -ErrorAction Stop
}
function Register-WorkflowListener {
    $listener = Get-WorkflowListener
    if (-not $listener) { throw 'No verified workflow listener to register.' }
    $previous = $tracked['workflow']
    $tracked['workflow'] = @{id=$listener.Id;started=$listener.StartTime.ToUniversalTime().ToString('o');executable=$listener.Path}
    if ($previous -and $previous.relay_id) {
        $tracked['workflow'].relay_id = $previous.relay_id
        $tracked['workflow'].relay_started = $previous.relay_started
        $tracked['workflow'].capture = $previous.capture
    }
    Save-ProcessState
}
function Stop-OwnedProcessTree([System.Diagnostics.Process]$Process) {
    if (-not $Process) { return }
    if ($Process.HasExited) { return }
    $current = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if (-not $current -or $current.StartTime.ToUniversalTime().Ticks -ne $Process.StartTime.ToUniversalTime().Ticks) { return }
    # Windows venv/console launchers can own the actual service as a descendant.
    # The root was verified by registration or returned by this invocation's Start-Process.
    $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    $stopOutput = & {
        # Windows PowerShell wraps native stderr in error records. A process can
        # exit while taskkill is reporting a failure, so verify the handle below.
        $ErrorActionPreference = 'Continue'
        & $taskkill /PID $current.Id /T /F 2>&1
    }
    $current.WaitForExit(10000) | Out-Null
    $current.Refresh()
    if (-not $current.HasExited) {
        $detail = ($stopOutput | ForEach-Object { $_.ToString() }) -join ' '
        throw "Could not stop the verified managed process tree. $detail"
    }
}
function Stop-OwnedService([string]$Name,[System.Diagnostics.Process]$Process) {
    $entry = $tracked[$Name]
    $linuxStopError = $null
    if ($Name -eq 'document-parser' -and $entry -and $entry.linux_nonce) {
        try { $null = Invoke-DocumentHost 'stop' $entry } catch { $linuxStopError=$_ }
    }
    if ($entry -and $entry.relay_id -and $entry.relay_started) {
        $started = [datetime]::MinValue
        $relay = Get-Process -Id $entry.relay_id -ErrorAction SilentlyContinue
        $validTime = if ($entry.relay_started -is [datetime]) { $started=$entry.relay_started; $true }
            else { [datetime]::TryParse([string]$entry.relay_started,[ref]$started) }
        if ($relay -and $validTime -and $relay.StartTime.ToUniversalTime().Ticks -eq $started.ToUniversalTime().Ticks) {
            $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($relay.Id)"
            $script = Join-Path (Split-Path $serviceRoot -Parent) '科研流程\runtime_logs.py'
            $command = '(?:^|\s)"?' + [regex]::Escape($script) + '"?\s+--relay-config\s+"?' +
                [regex]::Escape((Join-Path $logRoot "$Name.capture.json")) + '"?\s+--receipt\s+"?' +
                [regex]::Escape((Join-Path $logRoot "$Name.process.json")) + '"?(?:\s|$)'
            if ($native.CommandLine -match $command) {
                Stop-OwnedProcessTree $relay
                return
            }
        }
    }
    Stop-OwnedProcessTree $Process
    if ($linuxStopError) { throw $linuxStopError }
}
if ($Action -eq 'recover-workflow') {
    if (Get-WorkflowListener) { Register-WorkflowListener; Write-Output 'Verified workflow listener recovered into service registration.' }
    exit 0
}
if ($Action -eq 'restart-workflow') {
    $process = Get-OwnedProcess 'workflow'
    $verified = Get-WorkflowListener
    if ($process -and (-not $verified -or $verified.Id -ne $process.Id)) { throw 'Workflow identity changed before restart.' }
    if ($verified) {
        if (-not $process) { Register-WorkflowListener }
        Stop-OwnedService 'workflow' $verified
        $tracked.Remove('workflow')
        Save-ProcessState
    }
}
if ($Action -eq 'stop-document-parser') {
    if ($tracked.ContainsKey('document-parser')) {
        Stop-OwnedService 'document-parser' (Get-OwnedProcess 'document-parser')
    }
    exit 0
}
if ($Action -eq 'status-document-parser') {
    [pscustomobject]@{running=[bool](Get-OwnedProcess 'document-parser')} | ConvertTo-Json -Compress
    exit 0
}
if ($Action -eq 'stop') {
    foreach ($name in @('document-parser','automation','workflow','frontend','worker','api','database','model','rspace-helper')) {
        $process = Get-OwnedProcess $name
        if ($process -or ($name -eq 'document-parser' -and $tracked.ContainsKey($name))) { Stop-OwnedService $name $process; Write-Output "Stopped $name" }
    }
    exit 0
}
if ($Action -eq 'status') {
    foreach ($name in @('model','database','api','worker','frontend','workflow','automation')) {
        $process = Get-OwnedProcess $name
        [pscustomobject]@{Service=$name;Running=[bool]$process;ProcessId=if($process){$process.Id}else{$null}}
    }
    exit 0
}
foreach ($line in Get-Content -Encoding UTF8 -LiteralPath (Join-Path $appRoot '.env')) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
$env:SURREAL_PASS = $env:SURREAL_PASSWORD
$env:SURREAL_BIND = '127.0.0.1:8000'
$env:PORT = '8502'
$env:HOSTNAME = '127.0.0.1'
$env:NEXT_TELEMETRY_DISABLED = '1'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
function Get-FrontendArguments([string]$FrontendRoot) {
    if (Test-Path -LiteralPath (Join-Path $FrontendRoot 'server.js') -PathType Leaf) { return @('server.js') }
    return @('node_modules\next\dist\bin\next','start','--hostname','127.0.0.1','--port','8502')
}
function Start-OwnedProcess([string]$Name,[string]$Executable,[string[]]$Arguments,[string]$WorkingDirectory,[int]$Port=0) {
    if (Get-OwnedProcess $Name) { Write-Output "$Name already running"; return }
    if ($Port -and (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        if ($Name -eq 'workflow') {
            Register-WorkflowListener
            Write-Output 'Verified workflow already running; registration recovered.'
            return
        }
        throw "Port $Port is occupied by an untracked process; refusing to start $Name."
    }
    $workflowRoot = Join-Path (Split-Path $serviceRoot -Parent) '科研流程'
    $relayPython = Join-Path $workflowRoot '.venv\Scripts\python.exe'
    $relayScript = Join-Path $workflowRoot 'runtime_logs.py'
    $configurationPath = Join-Path $logRoot "$Name.capture.json"
    $receiptPath = Join-Path $logRoot "$Name.process.json"
    foreach ($candidate in @($logRoot,$configurationPath,$receiptPath)) {
        $component = [IO.Path]::GetFullPath($candidate)
        while ($component) {
            if (Test-Path -LiteralPath $component) {
                $item = Get-Item -LiteralPath $component -Force
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.LinkType -eq 'HardLink') {
                    throw 'Managed log paths cannot be directory, file or hard links.'
                }
            }
            $parent = [IO.Path]::GetDirectoryName($component)
            if ($parent -eq $component) { break }
            $component = $parent
        }
    }
    $nonce = [guid]::NewGuid().ToString('N')
    @{name=$Name;executable=$Executable;arguments=@($Arguments);working_directory=$WorkingDirectory;nonce=$nonce} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configurationPath -Encoding utf8
    $relay = Start-Process -FilePath $relayPython -ArgumentList @('-B',('"'+$relayScript+'"'),'--relay-config',('"'+$configurationPath+'"'),'--receipt',('"'+$receiptPath+'"'),'--log-root',('"'+$logRoot+'"')) -WorkingDirectory $workflowRoot -WindowStyle Hidden -PassThru
    try {
    $capture = $null
    $deadline = (Get-Date).AddSeconds(10)
    do {
        if (Test-Path -LiteralPath $receiptPath) {
            try {
                $candidate = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($candidate.nonce -eq $nonce -and $candidate.status -eq 'running') { $capture=$candidate; break }
            } catch { }
        }
        if ($relay.HasExited) { throw "Bounded capture could not start $Name; check log paths and limits." }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    if (-not $capture) { throw "Bounded capture startup timed out for $Name." }
    $process = Get-Process -Id $capture.child_pid -ErrorAction Stop
    $captureProcess = Get-Process -Id $capture.relay_pid -ErrorAction Stop
    $native = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    if ($native.ParentProcessId -ne $captureProcess.Id) { throw 'Managed capture child identity does not match its registered parent.' }
    $tracked[$Name] = @{id=$process.Id;started=$process.StartTime.ToUniversalTime().ToString('o');
        relay_id=$captureProcess.Id;relay_started=$captureProcess.StartTime.ToUniversalTime().ToString('o');
        capture='bounded-5MiB-x5-per-stream'}
    Save-ProcessState
    Write-Output "Started $Name ($($process.Id))"
    } catch {
        Stop-OwnedProcessTree $relay
        throw
    }
}
function Wait-Ready([string]$Url,[string]$Name,[int]$Seconds=40) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (-not (Get-OwnedProcess $Name)) { throw "$Name exited. Check $logRoot." }
        try { $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2; return } catch { Start-Sleep -Milliseconds 500 }
    } while ((Get-Date) -lt $deadline)
    throw "$Name did not become ready. Check $logRoot."
}
function Start-ResearchWorkflow {
    $workflowRoot = Join-Path (Split-Path $serviceRoot -Parent) '科研流程'
    $workflowPython = Join-Path $workflowRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $workflowPython)) { throw 'Research workflow interpreter is missing.' }
    Start-OwnedProcess 'workflow' $workflowPython @('-u','workflow.py','serve') $workflowRoot 8503
    Wait-Ready 'http://127.0.0.1:8503/health' 'workflow' 60
    Register-WorkflowListener
    Write-Output 'Research dashboard is ready: http://127.0.0.1:8503'
}
if ($Action -eq 'restart-workflow') {
    Start-ResearchWorkflow
    exit 0
}
function Resolve-DocumentWslPath([string]$Path,[string]$Label) {
    $result = Invoke-ShortWsl -Arguments @('-d','Ubuntu-24.04','--exec','wslpath','-a',$Path) -TimeoutSeconds 10
    if ($result.exit_code -ne 0 -or $result.stdout.Trim() -notmatch '^/[^\r\n]+$') {
        $diagnostic = [regex]::Match((($result.stderr+$result.stdout).Replace([string][char]0,'')), '(?:Wsl|WSL)/[A-Za-z0-9_/]+|0x[0-9a-fA-F]{8}').Value
        throw "Cannot resolve the document $Label path. WSL exit=$($result.exit_code) $diagnostic"
    }
    return $result.stdout.Trim()
}
if ($Action -eq 'start-document-parser') {
    $name = 'document-parser'
    $workspaceRoot = Split-Path (Split-Path $serviceRoot -Parent) -Parent
    $workflowRoot = Join-Path (Split-Path $serviceRoot -Parent) '科研流程'
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $process = Get-OwnedProcess $name
    try {
    if (-not $process) {
        # A dead Windows relay can leave a Linux process. Stop only the exact
        # registered Linux generation before creating another instance.
        if ($tracked.ContainsKey($name)) { Stop-OwnedService $name $null }
        $linuxHost = Resolve-DocumentWslPath (Join-Path $workflowRoot 'document_vlm_host.py') 'host'
        $linuxScript = Resolve-DocumentWslPath (Join-Path $workflowRoot 'start_document_vlm.sh') 'service'
        $linuxReceipt = Resolve-DocumentWslPath (Join-Path $logRoot 'document-parser.linux.json') 'receipt'
        $nonce = [guid]::NewGuid().ToString('N')
        if (Get-NetTCPConnection -LocalPort 8118 -State Listen -ErrorAction SilentlyContinue) { throw 'Document port is occupied by an unregistered listener.' }
        # WSL must be launched directly by PowerShell on this Windows host.
        # The Linux supervisor bounds both streams; no second Windows capture
        # process or unbounded redirected file is needed for this service.
        $arguments = @('-d','Ubuntu-24.04','--exec','/usr/bin/python3','-B',$linuxHost,'supervise','--script',$linuxScript,'--receipt',$linuxReceipt,'--nonce',$nonce) | ForEach-Object { if ($_ -match '\s') { '"' + $_.Replace('"','\"') + '"' } else { $_ } }
        $process = Start-Process -FilePath $wsl -ArgumentList $arguments -WorkingDirectory $workspaceRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot 'document-parser.host.stdout.log') -RedirectStandardError (Join-Path $logRoot 'document-parser.host.stderr.log')
        $tracked[$name] = @{id=$process.Id;started=$process.StartTime.ToUniversalTime().ToString('o');
            linux_host=$linuxHost;linux_receipt=$linuxReceipt;linux_nonce=$nonce;capture='bounded-5MiB-x5-linux'}
        Save-ProcessState
    }
        Wait-Ready 'http://127.0.0.1:8118/health' $name 300
        $receipt = Get-Content -LiteralPath (Join-Path $logRoot 'document-parser.linux.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($receipt.nonce -ne $tracked[$name].linux_nonce -or -not $receipt.server.start_ticks) { throw 'Document Linux ownership receipt changed.' }
        $linuxStatus = Invoke-DocumentHost 'status' $tracked[$name]
        if (-not $linuxStatus.running -or -not $linuxStatus.listening) { throw 'Document API port is not owned by the registered Linux process.' }
        $tracked[$name].ready = $true
        Save-ProcessState
        Write-Output 'Managed document parser ready on 127.0.0.1:8118.'
    } catch {
        Stop-OwnedService $name $process
        throw
    }
    exit 0
}
function Resolve-RSpaceRuntime([string]$Registered, [string]$WorkspaceRoot) {
    $invalid = 'Registered RSpace runtime is outside the provisioned location or has no compose file.'
    if ($Registered -ceq 'runtime/RSpace') {
        $runtime = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot 'runtime/RSpace'))
    } else {
        if ($Registered -notmatch '^[A-Za-z]:[\\/]') { throw $invalid }
        $runtime = [IO.Path]::GetFullPath($Registered)
        $allowed = [IO.Path]::GetFullPath((Join-Path $workspaceRoot 'runtime/RSpace'))
        if ($runtime -ne $allowed -and -not $runtime.StartsWith($allowed+'\',[StringComparison]::OrdinalIgnoreCase)) { throw $invalid }
    }
    $compose = Join-Path $runtime 'compose.yaml'
    if ($runtime -notmatch '^[A-Za-z]:[\\/]' -or -not (Test-Path -LiteralPath $compose -PathType Leaf)) { throw $invalid }
    for ($candidate = $compose; $candidate; $candidate = $parent.FullName) {
        if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw $invalid }
        $parent = [IO.Directory]::GetParent($candidate)
        if ($null -eq $parent) { break }
    }
    return $runtime
}

function Start-OwnedRSpace {
    $workspaceRoot = Split-Path (Split-Path $serviceRoot -Parent) -Parent
    $dataRoot = Join-Path $workspaceRoot '工具\科研流程\数据'
    $deploymentPath = Join-Path $dataRoot 'RSpace部署.json'
    if (-not (Test-Path -LiteralPath $deploymentPath)) { return }
    $deployment = Get-Content -LiteralPath $deploymentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $deployment.installed) { return }
    $runtime = Resolve-RSpaceRuntime ([string]$deployment.runtime) $workspaceRoot
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $helper = Get-OwnedProcess 'rspace-helper'
    if (-not $helper) {
        # This keepalive emits no service output. Launch WSL directly, as for
        # the document host; a Windows Python relay cannot start WSL here.
        $helper = Start-Process -FilePath $wsl -ArgumentList @('-d','Ubuntu-24.04','--exec','sleep','2147483647') -WorkingDirectory $workspaceRoot -WindowStyle Hidden -PassThru
        try {
            $tracked['rspace-helper'] = @{id=$helper.Id;started=$helper.StartTime.ToUniversalTime().ToString('o');capture='silent-wsl-keepalive'}
            Save-ProcessState
        } catch { Stop-OwnedProcessTree $helper; throw }
    }
    if ($helper) {
        @{pid=$helper.Id;stamp=$helper.StartTime.ToUniversalTime().ToFileTimeUtc().ToString();started=$helper.StartTime.ToUniversalTime().ToString('o');owner='service-manager'} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot 'rspace-process.json') -Encoding UTF8
    }
    $nativePreference = $ErrorActionPreference
    try {
        # Docker prints successful compose progress to stderr. Windows
        # PowerShell must judge these native commands by exit code.
        $ErrorActionPreference = 'Continue'
        $ready = $false
        for ($attempt=0; $attempt -lt 15; $attempt++) {
            $probe = Invoke-ShortWsl -Arguments @('-d','Ubuntu-24.04','-u','root','--exec','docker','info','--format','{{.ServerVersion}}') -TimeoutSeconds 10
            if ($probe.exit_code -eq 0 -and -not [string]::IsNullOrWhiteSpace($probe.stdout)) { $ready=$true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $ready) { throw 'RSpace container runtime readiness timed out.' }
        $linux = '/mnt/'+$runtime.Substring(0,1).ToLowerInvariant()+$runtime.Substring(2).Replace('\','/')+'/compose.yaml'
        $compose = Invoke-ShortWsl -Arguments @('-d','Ubuntu-24.04','-u','root','--exec','docker','compose','-p','yanxu-rspace','-f',$linux,'up','-d') -TimeoutSeconds 120
        if ($compose.exit_code -ne 0) { throw 'RSpace compose startup failed; data volumes retained.' }
    } finally { $ErrorActionPreference = $nativePreference }
    @{status='starting';owner='service-manager';time=(Get-Date).ToUniversalTime().ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot 'rspace-startup.json') -Encoding UTF8
}
Start-OwnedProcess 'database' (Join-Path $serviceRoot 'bin\surreal.exe') @('start','--log','warn','surrealkv:../data/surreal') $appRoot 8000
Wait-Ready 'http://127.0.0.1:8000/health' 'database'
$modelRoot = Join-Path (Split-Path $serviceRoot -Parent) '模型'
$ollamaPath = Join-Path $modelRoot 'Ollama\ollama.exe'
if (Test-Path -LiteralPath $ollamaPath) {
    $env:OLLAMA_MODELS = Join-Path $modelRoot 'weights'
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    $env:OLLAMA_NO_CLOUD = '1'
    Start-OwnedProcess 'model' $ollamaPath @('serve') $modelRoot 11434
    Wait-Ready 'http://127.0.0.1:11434/api/version' 'model'
}
$pythonPath = Join-Path $appRoot '.venv\Scripts\python.exe'
Start-OwnedProcess 'api' $pythonPath @('-m','uvicorn','api.main:app','--host','127.0.0.1','--port','5055') $appRoot 5055
Wait-Ready 'http://127.0.0.1:5055/health' 'api' 60
Start-OwnedProcess 'worker' (Join-Path $appRoot '.venv\Scripts\surreal-commands-worker.exe') @('--import-modules','commands','--max-tasks','1') $appRoot
$nodePath = (Get-Command node.exe).Source
Start-OwnedProcess 'frontend' $nodePath @(Get-FrontendArguments (Join-Path $appRoot 'frontend')) (Join-Path $appRoot 'frontend') 8502
Wait-Ready 'http://127.0.0.1:8502' 'frontend' 60
$workflowRoot = Join-Path (Split-Path $serviceRoot -Parent) '科研流程'
$workflowPython = Join-Path $workflowRoot '.venv\Scripts\python.exe'
try { Start-OwnedRSpace } catch {
    @{status='deferred';stage='native-runtime';message=$_.Exception.Message;time=(Get-Date).ToUniversalTime().ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $workflowRoot '数据\rspace-startup.json') -Encoding UTF8
    Write-Output 'RSpace is deferred; other workspace services continue.'
}
if (Test-Path -LiteralPath $workflowPython) {
    Start-ResearchWorkflow
}
Write-Output 'Open Notebook is ready: http://127.0.0.1:8502'
$automationRoot = Join-Path (Split-Path $serviceRoot -Parent) 'n8n'
if (Test-Path -LiteralPath (Join-Path $automationRoot '启动服务.ps1')) {
    . (Join-Path $automationRoot '服务环境.ps1')
    Start-OwnedProcess 'automation' $nodePath @($researchN8nEntry,'start') $automationRoot 5678
    Wait-Ready 'http://127.0.0.1:5678/healthz' 'automation' 60
    Write-Output 'Automation editor is ready: http://127.0.0.1:5678'
}
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8502' }
} finally {
    if ($stateLock) { $stateLock.Dispose() }
}
