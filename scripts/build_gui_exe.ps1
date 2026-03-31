[CmdletBinding()]
param(
    [switch]$Package,
    [switch]$Clean,
    [switch]$OpenOutput,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'

function Convert-ToWinPath([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }
    if ($PathValue.StartsWith('\\?\')) {
        return $PathValue.Substring(4)
    }
    return $PathValue
}

function Get-VenvExecutable([string]$RepoRoot) {
    $pythonExe = Join-Path $RepoRoot '.venv310\Scripts\python.exe'
    if (-not (Test-Path $pythonExe)) {
        throw "Missing virtual environment python: $pythonExe`nRun 'py -3.10 -m venv .venv310' first."
    }

    return $pythonExe
}

$repoRoot = Convert-ToWinPath ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')))
$launcherScript = Join-Path $repoRoot 'scripts\launch_gui.py'
$venvScripts = Join-Path $repoRoot '.venv310\Scripts'
$launcherExe = Join-Path $venvScripts 'xml-to-usda-gui.exe'
$distPath = Join-Path $repoRoot 'dist'
$buildPath = Join-Path $repoRoot 'build'
$exePath = Join-Path $distPath 'XMLtoUSDAConverter.exe'

Push-Location $repoRoot
try {
    if (-not (Test-Path $launcherExe)) {
        throw "Missing fast-build launcher: $launcherExe`nRun 'python -m pip install -e .[dev]' inside .venv310 first."
    }

    if ($Package) {
        $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
        if (-not $SkipBootstrap) {
            & $pythonExe -c "import PyInstaller" 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Host 'PyInstaller is missing in .venv310. Installing dev dependencies...'
                & $pythonExe -m pip --python (Join-Path $repoRoot '.venv310') install -e '.[dev]'
                if ($LASTEXITCODE -ne 0) {
                    throw 'Failed to install dev dependencies for exe build.'
                }
            }
        }

        if (Test-Path $buildPath) {
            Remove-Item -Recurse -Force $buildPath
        }
        if (Test-Path $distPath) {
            Remove-Item -Recurse -Force $distPath
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

        Write-Host "Building standalone GUI exe with $pythonExe ..."
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
    else {
        if ($Clean -and (Test-Path $distPath)) {
            Remove-Item -Recurse -Force $distPath
        }
        if ($Clean -and (Test-Path $buildPath)) {
            Remove-Item -Recurse -Force $buildPath
        }

        Write-Host "Building fast launcher exe by copying $launcherExe ..."
        New-Item -ItemType Directory -Force -Path $distPath | Out-Null
        Copy-Item -Force $launcherExe $exePath

        if (-not (Test-Path $exePath)) {
            throw "Expected exe was not created: $exePath"
        }

        Write-Host "Built: $exePath"
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
    }
}
finally {
    Pop-Location
}





