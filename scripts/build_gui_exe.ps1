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

    $pythonExe = Convert-ToWinPath $cfg['executable']
    if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path $pythonExe)) {
        throw "Could not resolve base python executable from $cfgPath"
    }

    return $pythonExe
}

$repoRoot = Convert-ToWinPath ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')))
$launcherScript = Join-Path $repoRoot 'scripts\launch_gui.py'
$venvScripts = Join-Path $repoRoot '.venv\Scripts'
$launcherExe = Join-Path $venvScripts 'xml-to-usda-gui.exe'
$distPath = Join-Path $repoRoot 'dist'
$buildPath = Join-Path $repoRoot 'build'
$exePath = Join-Path $distPath 'XMLtoUSDAConverter.exe'

Push-Location $repoRoot
try {
    if (-not (Test-Path $launcherExe)) {
        throw "Missing fast-build launcher: $launcherExe`nRun 'python -m pip install -e .[dev]' inside .venv first."
    }

    if ($Package) {
        $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
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

