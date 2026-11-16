[CmdletBinding()]
param(
    [string]$ManifestPath = (Join-Path $PSScriptRoot 'manifest.json'),
    [string]$AssetDirectory,
    [string]$InstallDir,
    [string[]]$Components = @(),
    [switch]$Offline,
    [switch]$VerifyOnly,
    [switch]$NoLaunch,
    [switch]$NoShortcut
)

# Windows PowerShell 5.1 / .NET Framework; no Python or Node prerequisite.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.Net.Http

function Assert-NoLinks([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if ([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) {
            if (([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'PATH_LINK: symbolic links and directory junctions are not accepted.'
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Get-SafeRelative([string]$Path, [switch]$AllowRoot) {
    if ($AllowRoot -and $Path -eq '.') { return '' }
    if ([string]::IsNullOrWhiteSpace($Path) -or [IO.Path]::IsPathRooted($Path) -or $Path -match '[\x00-\x1f:<>"|?*]') {
        throw 'UNSAFE_PATH: absolute, empty, or invalid Windows path.'
    }
    $normalized = $Path.Replace('\', '/').TrimEnd('/')
    foreach ($segment in $normalized.Split('/')) {
        if ($segment -eq '' -or $segment -eq '.' -or $segment -eq '..' -or $segment.EndsWith('.') -or $segment.EndsWith(' ') -or
            $segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw 'UNSAFE_PATH: ambiguous or reserved Windows path.'
        }
    }
    return $normalized
}

function Get-ChildPath([string]$Root, [string]$Relative) {
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    if ($Relative -eq '') { return $base }
    $result = [IO.Path]::GetFullPath((Join-Path $base $Relative.Replace('/', '\')))
    if (-not $result.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'UNSAFE_PATH: destination escaped installation directory.'
    }
    return $result
}

function Assert-ReleaseUrl([string]$Url, [string]$Expected) {
    if ($Url -cne $Expected) { throw 'INVALID_RELEASE_URL: component URL must match the declared GitHub release.' }
}

function Get-ArchiveHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}

function Save-ReleaseAsset([string]$Url, [string]$Destination, [long]$ExpectedSize) {
    # GitHub assets redirect to its dedicated asset host. Never follow arbitrary redirects.
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('ResearchWorkbench-Installer/1.0')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        $current = [Uri]$Url
        for ($redirect = 0; $redirect -le 5; $redirect++) {
            if ($current.Scheme -ne 'https' -or $current.Port -ne 443 -or $current.UserInfo -ne '' -or
                $current.Host -notin @('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')) {
                throw 'INVALID_REDIRECT: download left the GitHub release asset hosts.'
            }
            $response = $client.GetAsync($current, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            try {
                $status = [int]$response.StatusCode
                if ($status -in @(301, 302, 303, 307, 308)) {
                    if ($null -eq $response.Headers.Location) { throw 'DOWNLOAD_FAILED: redirect has no location.' }
                    $current = New-Object Uri($current, $response.Headers.Location)
                    continue
                }
                if ($status -ne 200) { throw "DOWNLOAD_FAILED: GitHub returned HTTP $status." }
                if ($null -ne $response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -ne $ExpectedSize) {
                    throw 'SIZE_MISMATCH: download content length differs from manifest.'
                }
                $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $buffer = New-Object byte[] 1048576
                    [long]$received = 0
                    while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $received += $count
                        if ($received -gt $ExpectedSize) { throw 'SIZE_MISMATCH: download exceeded manifest size.' }
                        $outputStream.Write($buffer, 0, $count)
                    }
                } finally { $outputStream.Dispose(); $inputStream.Dispose() }
                if ($received -ne $ExpectedSize) { throw 'SIZE_MISMATCH: incomplete download.' }
                return
            } finally { $response.Dispose() }
        }
        throw 'DOWNLOAD_FAILED: too many redirects.'
    } finally { $client.Dispose(); $handler.Dispose() }
}

function Expand-SafeArchive([string]$Archive, [string]$Root, [string]$ExtractTo, $Destinations) {
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        [long]$expanded = 0
        if ($zip.Entries.Count -gt 250000) { throw 'ZIP_LIMIT: too many entries.' }
        # Validate the entire archive before extracting its first file.
        $plan = New-Object 'Collections.Generic.List[object]'
        foreach ($entry in $zip.Entries) {
            $relative = Get-SafeRelative $entry.FullName
            $unixType = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            if ($unixType -notin @(0, 0x8000, 0x4000) -or (($entry.ExternalAttributes -band 0x400) -ne 0)) {
                throw 'ZIP_LINK: links and special files are not allowed.'
            }
            $directory = $entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')
            if ($directory -and $entry.Length -ne 0) { throw 'ZIP_COLLISION: directory entry contains data.' }
            $combined = $relative
            if ($ExtractTo -ne '') { $combined = $ExtractTo + '/' + $relative }
            $destination = Get-ChildPath $Root $combined
            if ($Destinations.ContainsKey($destination)) {
                if (-not ($directory -and $Destinations[$destination] -eq 'directory')) { throw 'ZIP_COLLISION: duplicate destination.' }
            } else { $Destinations.Add($destination, $(if ($directory) {'directory'} else {'file'})) }
            $ancestor = [IO.Directory]::GetParent($destination)
            while ($null -ne $ancestor -and $ancestor.FullName.Length -gt $Root.Length) {
                if ($Destinations.ContainsKey($ancestor.FullName) -and $Destinations[$ancestor.FullName] -eq 'file') {
                    throw 'ZIP_COLLISION: file shadows an ancestor directory.'
                }
                if (-not $Destinations.ContainsKey($ancestor.FullName)) { $Destinations.Add($ancestor.FullName, 'directory') }
                $ancestor = $ancestor.Parent
            }
            $expanded += $entry.Length
            if ($expanded -gt 34359738368) { throw 'ZIP_LIMIT: component exceeds 32 GiB expanded size.' }
            $plan.Add(@{ Entry = $entry; Destination = $destination; Directory = $directory })
        }
        foreach ($item in $plan) {
            if ($item.Directory) { [IO.Directory]::CreateDirectory($item.Destination) | Out-Null; continue }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($item.Destination)) | Out-Null
            $inputStream = $item.Entry.Open()
            $outputStream = [IO.File]::Open($item.Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose(); $inputStream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Remove-OwnedStaging([string]$Path, [string]$Parent, [string]$Token) {
    if (-not $Path -or -not [IO.Directory]::Exists($Path)) { return }
    $expected = [IO.Path]::GetFullPath((Join-Path $Parent ('.research-install-' + $Token)))
    if ([IO.Path]::GetFullPath($Path) -cne $expected) { throw 'CLEANUP_REFUSED: unexpected staging path.' }
    Assert-NoLinks $Path
    $queue = New-Object 'Collections.Generic.Queue[string]'
    $queue.Enqueue($Path)
    while ($queue.Count -gt 0) {
        foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($queue.Dequeue())) {
            $attributes = [IO.File]::GetAttributes($entry)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'CLEANUP_REFUSED: staging contains a link.' }
            if (($attributes -band [IO.FileAttributes]::Directory) -ne 0) { $queue.Enqueue($entry) }
        }
    }
    Remove-Item -LiteralPath $expected -Recurse -Force
}

$staging = $null
$lock = $null
$lockPath = $null
$installed = $false
$exitCode = 1
try {
    $manifestFull = [IO.Path]::GetFullPath($ManifestPath)
    Assert-NoLinks $manifestFull
    if (-not [IO.File]::Exists($manifestFull) -or (Get-Item -LiteralPath $manifestFull).Length -gt 1048576) {
        throw 'INVALID_MANIFEST: missing manifest or manifest exceeds 1 MiB.'
    }
    $manifest = Get-Content -LiteralPath $manifestFull -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' -or
        $manifest.release_id -notmatch '^[A-Za-z0-9_.-]+$') { throw 'INVALID_MANIFEST: unsupported schema or repository identity.' }
    $pythonRelative = Get-SafeRelative ([string]$manifest.installation.python)
    $initializerRelative = Get-SafeRelative ([string]$manifest.installation.initializer)
    if (-not $pythonRelative.EndsWith('/python.exe') -or -not $initializerRelative.EndsWith('.py')) {
        throw 'INVALID_MANIFEST: unexpected initializer entry point.'
    }
    $selected = New-Object 'Collections.Generic.List[object]'
    $requested = @($Components | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    $ids = @{}
    $selectors = @{}
    $archives = @{}
    $manifestDirectory = [IO.Path]::GetDirectoryName($manifestFull)
    if ([string]::IsNullOrWhiteSpace($AssetDirectory)) { $AssetDirectory = $manifestDirectory }
    $assetRoot = [IO.Path]::GetFullPath($AssetDirectory)
    Assert-NoLinks $assetRoot
    foreach ($component in @($manifest.components)) {
        if ($component.id -notmatch '^[a-z0-9][a-z0-9-]*$' -or $ids.ContainsKey($component.id)) { throw 'INVALID_MANIFEST: invalid or duplicate component id.' }
        $ids[$component.id] = $true
        $selectors[$component.id] = $true
        $group = ''
        if ($component.PSObject.Properties.Name -contains 'group') {
            $group = [string]$component.group
            if ($group -notmatch '^[a-z0-9][a-z0-9-]*$') { throw 'INVALID_MANIFEST: invalid component group.' }
            $selectors[$group] = $true
        }
        if ($component.archive -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*\.zip$' -or $archives.ContainsKey($component.archive)) { throw 'INVALID_ARCHIVE: use unique ZIP basenames.' }
        $archives[$component.archive] = $true
        if ($component.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $component.size_bytes -isnot [ValueType] -or
            [long]$component.size_bytes -le 0 -or [long]$component.size_bytes -ge 2147483648 -or $component.required -isnot [bool]) {
            throw 'INVALID_MANIFEST: invalid hash, size, or required flag.'
        }
        $extractTo = Get-SafeRelative ([string]$component.extract_to) -AllowRoot
        $expectedUrl = 'https://github.com/' + $manifest.repository + '/releases/download/' + $manifest.release_id + '/' + $component.archive
        Assert-ReleaseUrl ([string]$component.url) $expectedUrl
        if ($component.required -or $requested -contains $component.id -or ($group -and $requested -contains $group)) {
            $selected.Add(@{ Data = $component; ExtractTo = $extractTo })
        }
    }
    foreach ($id in $requested) { if (-not $selectors.ContainsKey($id)) { throw 'UNKNOWN_COMPONENT: selected component or group is not in the manifest.' } }
    if ($selected.Count -eq 0) { throw 'INVALID_MANIFEST: no components selected.' }
    if ([string]::IsNullOrWhiteSpace($InstallDir)) {
        $defaultDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ResearchWorkbench'
        $chosen = Read-Host ('Install directory (press Enter for ' + $defaultDirectory + ')')
        $InstallDir = $(if ([string]::IsNullOrWhiteSpace($chosen)) { $defaultDirectory } else { $chosen.Trim('"') })
    }
    $target = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\', '/')
    if ($target -notmatch '^[A-Za-z]:\\.+') { throw 'INVALID_TARGET: choose a local, non-root Windows directory.' }
    Assert-NoLinks $target
    if ([IO.File]::Exists($target) -or ([IO.Directory]::Exists($target) -and @([IO.Directory]::EnumerateFileSystemEntries($target)).Count -ne 0)) {
        throw 'TARGET_NOT_EMPTY: choose a new empty directory; existing files are never overwritten.'
    }
    $parentDirectory = [IO.Path]::GetDirectoryName($target)
    [IO.Directory]::CreateDirectory($parentDirectory) | Out-Null
    $token = [Guid]::NewGuid().ToString('N')
    $staging = Join-Path $parentDirectory ('.research-install-' + $token)
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    $workspace = Join-Path $staging 'workspace'
    $downloadDirectory = Join-Path $staging 'archives'
    [IO.Directory]::CreateDirectory($workspace) | Out-Null
    [IO.Directory]::CreateDirectory($downloadDirectory) | Out-Null
    $destinations = New-Object 'Collections.Generic.Dictionary[string,string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($item in $selected) {
        $component = $item.Data
        Write-Host ('Verifying ' + $component.archive)
        $archivePath = Join-Path $assetRoot $component.archive
        Assert-NoLinks $archivePath
        if (-not [IO.File]::Exists($archivePath)) {
            if ($Offline) { throw ('OFFLINE_COMPONENT_MISSING: ' + $component.archive) }
            $archivePath = Join-Path $downloadDirectory $component.archive
            Save-ReleaseAsset $component.url $archivePath ([long]$component.size_bytes)
        }
        if ((Get-Item -LiteralPath $archivePath).Length -ne [long]$component.size_bytes) { throw ('SIZE_MISMATCH: ' + $component.archive) }
        $actualHash = Get-ArchiveHash $archivePath
        if ($actualHash -ine $component.sha256) { throw ('HASH_MISMATCH: ' + $component.archive) }
        Expand-SafeArchive $archivePath $workspace $item.ExtractTo $destinations
    }
    if ($VerifyOnly) {
        Write-Host ('VERIFIED: ' + $selected.Count + ' components. No installation was performed.')
        $exitCode = 0
    } else {
        $python = Get-ChildPath $workspace $pythonRelative
        $initializer = Get-ChildPath $workspace $initializerRelative
        if (-not [IO.File]::Exists($python) -or -not [IO.File]::Exists($initializer)) { throw 'MISSING_INITIALIZER: payload entry point is missing.' }
        # CreateNew makes competing installations fail before either can claim the target.
        $lockPath = $target + '.install-lock'
        Assert-NoLinks $lockPath
        $lock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        Assert-NoLinks $target
        if ([IO.Directory]::Exists($target)) {
            if (@([IO.Directory]::EnumerateFileSystemEntries($target)).Count -ne 0) { throw 'TARGET_NOT_EMPTY: target changed during verification.' }
            [IO.Directory]::Delete($target, $false)
        }
        [IO.Directory]::Move($workspace, $target)
        $installed = $true
        [IO.File]::Copy($manifestFull, (Join-Path $target 'installation-manifest.json'), $false)
        $python = Get-ChildPath $target $pythonRelative
        $initializer = Get-ChildPath $target $initializerRelative
        $initializeArgs = @('--workspace-root', $target)
        if ($NoLaunch) { $initializeArgs += '--no-launch' }
        if ($NoShortcut) { $initializeArgs += '--no-shortcut' }
        & $python '-E' '-s' $initializer @initializeArgs
        if ($LASTEXITCODE -ne 0) { throw ('INITIALIZATION_FAILED: initialization exited with code ' + $LASTEXITCODE + '. Files were retained for diagnosis.') }
        @{ schema_version = 1; release_id = $manifest.release_id; installed_at = [DateTime]::UtcNow.ToString('o'); status = 'complete' } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'installation-status.json') -Encoding UTF8
        Write-Host ('INSTALLED: ' + $target)
        $exitCode = 0
    }
} catch {
    $message = $_.Exception.Message
    if ($installed) {
        try {
            @{ status = 'failed'; error = $message; recorded_at = [DateTime]::UtcNow.ToString('o') } |
                ConvertTo-Json | Set-Content -LiteralPath (Join-Path $target 'install-failed.json') -Encoding UTF8
        } catch { Write-Warning 'Unable to write installation failure status.' }
    }
    [Console]::Error.WriteLine($message)
} finally {
    if ($null -ne $lock) { $lock.Dispose(); Remove-Item -LiteralPath $lockPath -Force }
    if ($staging) {
        try { Remove-OwnedStaging $staging $parentDirectory $token }
        catch { Write-Warning ('Staging retained: ' + $staging + ' (' + $_.Exception.Message + ')') }
    }
}
exit $exitCode
