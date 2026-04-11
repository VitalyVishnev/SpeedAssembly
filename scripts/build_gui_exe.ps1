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

function Get-GitBuildMetadata([string]$RepoRoot) {
    $metadata = @{
        git_branch = $null
        git_head = $null
        git_dirty = $null
        change_summary = $null
    }

    try {
        $branch = git -C $RepoRoot branch --show-current 2>$null
        if ($LASTEXITCODE -eq 0) {
            $metadata.git_branch = (($branch | Out-String).Trim())
        }
    }
    catch {
    }

    try {
        $head = git -C $RepoRoot rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            $metadata.git_head = (($head | Out-String).Trim())
        }
    }
    catch {
    }

    try {
        $statusLines = @(git -C $RepoRoot status --short 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $metadata.git_dirty = ($statusLines.Count -gt 0)
            $summaryItems = @($statusLines | Select-Object -First 3 | ForEach-Object { $_.Trim() })
            if ($statusLines.Count -gt 3) {
                $summaryItems += "(+$($statusLines.Count - 3) more)"
            }
            if ($summaryItems.Count -gt 0) {
                $metadata.change_summary = ($summaryItems -join '; ')
            }
        }
    }
    catch {
    }

    return $metadata
}

function Write-BuildInfo(
    [string]$DistPath,
    [string]$ExePath,
    [string]$PythonExe,
    [string]$RepoRoot,
    [string]$BuildMode
) {
    $buildInfoPath = Join-Path $DistPath 'build_info.json'
    $gitMetadata = Get-GitBuildMetadata -RepoRoot $RepoRoot
    $payload = [ordered]@{
        built_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
        build_mode = $BuildMode
        exe_path = $ExePath
        python_exe = $PythonExe
        repo_root = $RepoRoot
        git_branch = $gitMetadata.git_branch
        git_head = $gitMetadata.git_head
        git_dirty = $gitMetadata.git_dirty
        change_summary = $gitMetadata.change_summary
    }
    $payload | ConvertTo-Json | Set-Content -Path $buildInfoPath -Encoding UTF8
    Write-Host "Wrote build info: $buildInfoPath"
}

$repoRoot = Convert-ToWinPath ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')))
$launcherScript = Join-Path $repoRoot 'scripts\launch_gui.py'
$workerLauncherScript = Join-Path $repoRoot 'scripts\launch_fbx_worker.py'
$venvScripts = Join-Path $repoRoot '.venv310\Scripts'
$launcherExe = Join-Path $venvScripts 'xml-to-usda-gui.exe'
$distPath = Join-Path $repoRoot 'dist'
$buildPath = Join-Path $repoRoot 'build'
$exePath = Join-Path $distPath 'XMLtoUSDAConverter.exe'
$workerExePath = Join-Path $distPath 'XMLtoUSDAWorker\XMLtoUSDAWorker.exe'

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

        Write-Host "Building sidecar FBX worker exe with $pythonExe ..."
        & $pythonExe @workerPyInstallerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'PyInstaller worker build failed.'
        }

        if (-not (Test-Path $exePath)) {
            throw "Expected exe was not created: $exePath"
        }
        if (-not (Test-Path $workerExePath)) {
            throw "Expected worker exe was not created: $workerExePath"
        }

        Write-BuildInfo -DistPath $distPath -ExePath $exePath -PythonExe $pythonExe -RepoRoot $repoRoot -BuildMode 'package'

        Write-Host "Built: $exePath"
        Write-Host "Built worker: $workerExePath"
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

        $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
        Write-BuildInfo -DistPath $distPath -ExePath $exePath -PythonExe $pythonExe -RepoRoot $repoRoot -BuildMode 'launcher'

        Write-Host "Built: $exePath"
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
    }
}
finally {
    Pop-Location
}
