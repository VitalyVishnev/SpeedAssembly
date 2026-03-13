[CmdletBinding()]
param(
    [int]$PollMilliseconds = 1200,
    [switch]$Clean,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildScript = Join-Path $PSScriptRoot 'build_gui_exe.ps1'
$watchRoots = @(
    (Join-Path $repoRoot 'src')
)
$watchFiles = @(
    (Join-Path $repoRoot 'pyproject.toml')
)

function Get-WatchSignature {
    $entries = New-Object System.Collections.Generic.List[string]

    foreach ($root in $watchRoots) {
        if (-not (Test-Path $root)) {
            continue
        }
        Get-ChildItem -Path $root -File -Recurse |
            Sort-Object FullName |
            ForEach-Object {
                $entries.Add("$($_.FullName)|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)")
            }
    }

    foreach ($file in $watchFiles) {
        if (-not (Test-Path $file)) {
            continue
        }
        $item = Get-Item $file
        $entries.Add("$($item.FullName)|$($item.Length)|$($item.LastWriteTimeUtc.Ticks)")
    }

    return [string]::Join("`n", $entries)
}

$buildArgs = @{}
if ($Clean) {
    $buildArgs.Clean = $true
}
if ($SkipBootstrap) {
    $buildArgs.SkipBootstrap = $true
}

Write-Host 'Starting GUI exe watch mode. Press Ctrl+C to stop.'
& $buildScript @buildArgs
$lastSignature = Get-WatchSignature

while ($true) {
    Start-Sleep -Milliseconds $PollMilliseconds
    $currentSignature = Get-WatchSignature
    if ($currentSignature -eq $lastSignature) {
        continue
    }

    Write-Host ''
    Write-Host 'Change detected. Rebuilding GUI exe...'
    & $buildScript @buildArgs
    $lastSignature = Get-WatchSignature
}
