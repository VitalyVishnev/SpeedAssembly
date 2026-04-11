[CmdletBinding()]
param(
    [switch]$Package,
    [switch]$Clean,
    [switch]$OpenOutput,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'

function Get-VenvExecutable([string]$RepoRoot) {
    $pythonExe = Join-Path $RepoRoot '.venv310\Scripts\python.exe'
    if (-not (Test-Path $pythonExe)) {
        throw "Missing virtual environment python: $pythonExe`nRun 'py -3.10 -m venv .venv310' first."
    }
    return $pythonExe
}

function Write-BuildInfo(
    [string]$DistPath,
    [string]$ExePath,
    [string]$PythonExe,
    [string]$RepoRoot,
    [string]$BuildMode
) {
    $buildInfoPath = Join-Path $DistPath 'build_info.json'
    $payload = [ordered]@{
        built_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
        build_mode = $BuildMode
        exe_path = $ExePath
        python_exe = $PythonExe
        repo_root = $RepoRoot
    }
    $payload | ConvertTo-Json | Set-Content -Path $buildInfoPath -Encoding UTF8
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$launcherScript = Join-Path $repoRoot 'scripts\launch_qt_gui.py'
$workerLauncherScript = Join-Path $repoRoot 'scripts\launch_fbx_worker.py'
$distPath = Join-Path $repoRoot 'dist-next'
$buildPath = Join-Path $repoRoot 'build-next'
$exePath = Join-Path $distPath 'XMLtoUSDAConverterNext.exe'
$workerExePath = Join-Path $distPath 'XMLtoUSDAWorker\XMLtoUSDAWorker.exe'

Push-Location $repoRoot
try {
    $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
    if (-not $SkipBootstrap) {
        & $pythonExe -c "import PySide6, PyInstaller" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing UI-next build dependencies into .venv310 ...'
            & $pythonExe -m pip install -e '.[dev,ui-next]'
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to install ui-next dependencies for beta shell build.'
            }
        }
    }

    if ($Clean -and (Test-Path $distPath)) {
        Remove-Item -Recurse -Force $distPath
    }
    if ($Clean -and (Test-Path $buildPath)) {
        Remove-Item -Recurse -Force $buildPath
    }

    if ($Package) {
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
            '--name', 'XMLtoUSDAConverterNext',
            '--paths', (Join-Path $repoRoot 'src'),
            '--collect-data', 'xml_to_usda.qt_ui',
            '--distpath', $distPath,
            '--workpath', $buildPath,
            $launcherScript
        )

        Write-Host "Building PySide6 beta shell with $pythonExe ..."
        & $pythonExe @pyInstallerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'PyInstaller beta-shell build failed.'
        }

        $workerPyInstallerArgs = @(
            '-m', 'PyInstaller',
            '--noconfirm',
            '--clean',
            '--console',
            '--name', 'XMLtoUSDAWorker',
            '--paths', (Join-Path $repoRoot 'src'),
            '--distpath', $distPath,
            '--workpath', (Join-Path $buildPath 'worker'),
            $workerLauncherScript
        )

        Write-Host "Building FBX worker sidecar with $pythonExe ..."
        & $pythonExe @workerPyInstallerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'PyInstaller worker build failed for beta shell.'
        }

        if (-not (Test-Path $exePath)) {
            throw "Expected beta exe was not created: $exePath"
        }
        if (-not (Test-Path $workerExePath)) {
            throw "Expected worker exe was not created: $workerExePath"
        }

        Write-BuildInfo -DistPath $distPath -ExePath $exePath -PythonExe $pythonExe -RepoRoot $repoRoot -BuildMode 'package-next'
        Write-Host "Built: $exePath"
        Write-Host "Built worker: $workerExePath"
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
    }
}
finally {
    Pop-Location
}
