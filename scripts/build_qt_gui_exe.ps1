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

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$launcherScript = Join-Path $repoRoot 'scripts\launch_qt_gui.py'
$distPath = Join-Path $repoRoot 'dist-next'
$buildPath = Join-Path $repoRoot 'build-next'
$exePath = Join-Path $distPath 'XMLtoUSDAConverter.exe'
$iconPath = Join-Path $repoRoot 'src\xml_to_usda\qt_ui\assets\Icon.ico'

Push-Location $repoRoot
try {
    $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
    if (-not $SkipBootstrap) {
        & $pythonExe -c "import PySide6, PyInstaller" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing UI-next build dependencies into .venv310 ...'
            & $pythonExe -m pip install -e '.[dev,ui-next]'
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to install ui-next dependencies for PySide6 release build.'
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
        if (-not (Test-Path $iconPath)) {
            throw "Missing application icon: $iconPath"
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
            '--icon', $iconPath,
            '--paths', (Join-Path $repoRoot 'src'),
            '--collect-data', 'xml_to_usda.qt_ui',
            '--distpath', $distPath,
            '--workpath', $buildPath,
            '--specpath', $buildPath,
            $launcherScript
        )

        Write-Host "Building PySide6 release shell with $pythonExe ..."
        & $pythonExe @pyInstallerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'PyInstaller PySide6 release build failed.'
        }

        if (-not (Test-Path $exePath)) {
            throw "Expected release exe was not created: $exePath"
        }

        Write-BuildInfo -DistPath $distPath -ExePath $exePath -PythonExe $pythonExe -RepoRoot $repoRoot -BuildMode 'release'
        $bundlePath = Join-Path $distPath 'XMLtoUSDAConverter_release.zip'
        & $pythonExe -m xml_to_usda.release_bundle --repo-root $repoRoot --dist-path $distPath --zip-path $bundlePath
        if ($LASTEXITCODE -ne 0) {
            throw 'Release zip assembly failed.'
        }
        Write-Host "Built: $exePath"
        Write-Host "Release zip: $bundlePath"
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
    }
}
finally {
    Pop-Location
}
