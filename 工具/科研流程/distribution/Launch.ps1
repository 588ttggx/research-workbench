[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'status', 'none')][string]$Action = 'start',
    [switch]$CreateShortcut,
    [string]$ShortcutDirectory,
    [switch]$NoBrowser
)

# Services and process identity remain owned by the existing service manager.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

function Assert-PlainPath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if ([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) {
            if (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'PATH_LINK: release paths cannot traverse links or junctions.'
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Get-ReleasePath([string]$Relative) {
    if (-not $Relative -or [IO.Path]::IsPathRooted($Relative) -or $Relative -match '[\x00-\x1f:<>"|?*]') {
        throw 'INVALID_RELEASE_PATH: expected an installation-relative path.'
    }
    foreach ($part in $Relative.Replace('\', '/').Split('/')) {
        if ($part -in @('', '.', '..') -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw 'INVALID_RELEASE_PATH: ambiguous or reserved path component.'
        }
    }
    $path = [IO.Path]::GetFullPath((Join-Path $releaseRoot $Relative))
    if (-not $path.StartsWith($releaseRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'INVALID_RELEASE_PATH: path escaped release root.' }
    Assert-PlainPath $path
    return $path
}

try {
    $releaseRoot = [IO.Directory]::GetParent($PSScriptRoot).Parent.Parent.FullName.TrimEnd('\')
    Assert-PlainPath $releaseRoot
    $marker = Get-ReleasePath '.research-workbench-release.json'
    if (-not [IO.File]::Exists($marker)) { throw 'INVALID_RELEASE: release marker is missing.' }
    $release = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($release.schema_version -ne 1 -or -not $release.release_id) { throw 'INVALID_RELEASE: unsupported release marker.' }
    $versionsFile = Get-ReleasePath '工具/工具版本.json'
    if (-not [IO.File]::Exists($versionsFile)) { throw 'INITIALIZATION_REQUIRED: installation settings are missing.' }
    $versions = Get-Content -LiteralPath $versionsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $notebookRelative = [string]$versions.open_notebook.runtime
    if (-not $notebookRelative.StartsWith('工具/OpenNotebook/', [StringComparison]::Ordinal)) { throw 'INVALID_RELEASE_PATH: unexpected Open Notebook location.' }
    $notebookPath = Get-ReleasePath $notebookRelative
    $workflowPath = Get-ReleasePath '工具/科研流程'
    $nodePath = Get-ReleasePath 'runtime/node'
    $env:PATH = $nodePath + ';' + (Join-Path $workflowPath '.venv/Scripts') + ';' + (Join-Path $notebookPath '.venv/Scripts') + ';' + $env:PATH
    foreach ($name in @('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $caches = @{ MPLCONFIGDIR = 'matplotlib'; DVC_SITE_CACHE_DIR = 'dvc'; SPC_CACHE_DIR = 'scholarly'; UV_CACHE_DIR = 'uv' }
    foreach ($name in $caches.Keys) {
        $path = Get-ReleasePath ('runtime/cache/' + $caches[$name])
        [IO.Directory]::CreateDirectory($path) | Out-Null
        [Environment]::SetEnvironmentVariable($name, $path, 'Process')
    }

    if ($CreateShortcut) {
        $entry = Get-ReleasePath '打开科研区.cmd'
        if (-not [IO.File]::Exists($entry)) { throw 'MISSING_LAUNCHER: root launch command is missing.' }
        if ([string]::IsNullOrWhiteSpace($ShortcutDirectory)) { $ShortcutDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
        if ([string]::IsNullOrWhiteSpace($ShortcutDirectory)) { throw 'SHORTCUT_DIRECTORY_MISSING: no desktop directory is available.' }
        $shortcutFolder = [IO.Path]::GetFullPath($ShortcutDirectory)
        Assert-PlainPath $shortcutFolder
        [IO.Directory]::CreateDirectory($shortcutFolder) | Out-Null
        $shortcutPath = Join-Path $shortcutFolder 'Research Workbench.lnk'
        Assert-PlainPath $shortcutPath
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        try {
            if ([IO.File]::Exists($shortcutPath)) {
                if ($shortcut.TargetPath -ine $entry) { throw 'SHORTCUT_EXISTS: another workspace owns this shortcut; it was preserved.' }
            } else {
                $shortcut.TargetPath = $entry
                $shortcut.WorkingDirectory = $releaseRoot
                $shortcut.Description = 'Research Workbench'
                $shortcut.WindowStyle = 7
                $shortcut.Save()
            }
            Write-Output ('SHORTCUT_READY: ' + $shortcutPath)
        } finally {
            [Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) | Out-Null
            [Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
        }
    }

    if ($Action -ne 'none') {
        $manager = Get-ReleasePath '工具/OpenNotebook/管理服务.ps1'
        if (-not [IO.File]::Exists($manager)) { throw 'MISSING_MANAGER: managed service entry point is missing.' }
        $global:LASTEXITCODE = 0
        & {
            param($ManagerPath, $ManagerAction)
            # Preserve the existing manager's PowerShell semantics.
            Set-StrictMode -Off
            & $ManagerPath -Action $ManagerAction
        } $manager $Action
        if ($LASTEXITCODE -ne 0) { throw ('SERVICE_ACTION_FAILED: manager returned ' + $LASTEXITCODE) }
        if ($Action -eq 'start' -and -not $NoBrowser) { Start-Process 'http://127.0.0.1:8503' }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
