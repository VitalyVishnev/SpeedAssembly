[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$OpenOutput,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'

function Get-VenvExecutable([string]$RepoRoot) {
    $cfgPath = Join-Path $RepoRoot '.venv\pyvenv.cfg'
    if (-not (Test-Path $cfgPath)) {
        throw "Missing virtual environment config: $cfgPath`nRun 'python -m venv .venv' first."
    }

    $cfg = @{}
    foreach ($line in Get-Content $cfgPath) {
        if ($line -notmatch '=') {
            continue
        }
        $parts = $line.Split('=', 2)
        $cfg[$parts[0].Trim()] = $parts[1].Trim()
    }

    $pythonExe = $cfg['executable']
    if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path $pythonExe)) {
        throw "Could not resolve base python executable from $cfgPath"
    }

    return $pythonExe
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
$sitePackages = Join-Path $repoRoot '.venv\Lib\site-packages'
$launcherScript = Join-Path $repoRoot 'scripts\launch_gui.py'
$distPath = Join-Path $repoRoot 'dist'
$buildPath = Join-Path $repoRoot 'build'
$exePath = Join-Path $distPath 'XMLtoUSDAConverter.exe'
$originalPythonPath = $env:PYTHONPATH
$resolvedPythonPath = @(
    $sitePackages,
    (Join-Path $repoRoot 'src')
)
if ($originalPythonPath) {
    $resolvedPythonPath += $originalPythonPath
}
$env:PYTHONPATH = ($resolvedPythonPath -join ';')

Push-Location $repoRoot
try {
    if (-not $SkipBootstrap) {
        & $pythonExe -c "import PyInstaller" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'PyInstaller is missing in .venv. Installing dev dependencies...'
            & $pythonExe -m pip --python (Join-Path $repoRoot '.venv') install -e '.[dev]'
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to install dev dependencies for exe build.'
            }
        }
    }

    if ($Clean) {
        if (Test-Path $buildPath) {
            Remove-Item -Recurse -Force $buildPath
        }
        if (Test-Path $distPath) {
            Remove-Item -Recurse -Force $distPath
        }
    }

    $pyInstallerArgs = @(
        '-m', 'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onefile',
        '--windowed',
        '--name', 'XMLtoUSDAConverter',
        '--paths', (Join-Path $repoRoot 'src'),
        '--distpath', $distPath,
        '--workpath', $buildPath,
        $launcherScript
    )

    Write-Host "Building GUI exe with $pythonExe ..."
    & $pythonExe @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed.'
    }

    if (-not (Test-Path $exePath)) {
        throw "Expected exe was not created: $exePath"
    }

    Write-Host "Built: $exePath"
    if ($OpenOutput) {
        Invoke-Item $distPath
    }
}
finally {
    $env:PYTHONPATH = $originalPythonPath
    Pop-Location
}
