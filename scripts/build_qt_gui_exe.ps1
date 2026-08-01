[CmdletBinding()]
param(
    [switch]$Package,
    [switch]$Quick,
    [switch]$Clean,
    [switch]$OpenOutput,
    [switch]$SkipBootstrap,
    [switch]$SkipSmoke
)

$ErrorActionPreference = 'Stop'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUSERBASE = Join-Path (Join-Path $PSScriptRoot '..') '.pyinstaller-userbase'

if ($Package -and $Quick) {
    throw 'Choose either -Quick or -Package, not both.'
}
if (-not $Package -and -not $Quick) {
    throw 'Choose -Quick for a source-backed UI preview or -Package for the full release gate.'
}
if ($SkipSmoke -and -not $Package) {
    throw '-SkipSmoke is valid only with -Package.'
}

function Get-VenvExecutable([string]$RepoRoot) {
    $pythonExe = Join-Path $RepoRoot '.venv310\Scripts\python.exe'
    if (-not (Test-Path $pythonExe)) {
        throw "Missing virtual environment python: $pythonExe`nRun 'py -3.10 -m venv .venv310' first."
    }
    return $pythonExe
}

function Quote-ProcessArgument([string]$Argument) {
    if ($null -eq $Argument) {
        return '""'
    }
    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }
    return '"' + $Argument.Replace('"', '\"') + '"'
}

function Join-ProcessArguments([string[]]$Arguments) {
    return (($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join ' ')
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
$distPath = Join-Path $repoRoot $(if ($Quick) { 'dist-preview' } else { 'dist-next' })
$buildPath = Join-Path $repoRoot 'build-next'
$qtUiSourceRoot = Join-Path $repoRoot 'src\xml_to_usda\qt_ui'
$qtUiStagingRoot = Join-Path $buildPath 'qt_ui_data'
$exePath = Join-Path $distPath 'SpeedAssembly.exe'
$previewLauncherPath = Join-Path $distPath 'SpeedAssembly_preview.cmd'
$distWorkerExePath = Join-Path $distPath 'XMLtoUSDAWorker.exe'
$iconPath = Join-Path $repoRoot 'src\xml_to_usda\qt_ui\assets\Icon.ico'
$hooksPath = Join-Path $repoRoot 'hooks'

Push-Location $repoRoot
try {
    $pythonExe = Get-VenvExecutable -RepoRoot $repoRoot
    if (-not $SkipBootstrap) {
        $bootstrapCheck = if ($Quick) { 'import PySide6' } else { 'import PySide6, PyInstaller' }
        & $pythonExe -s -c $bootstrapCheck 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing UI-next build dependencies into .venv310 ...'
            & $pythonExe -s -m pip install -e '.[dev,ui-next]'
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to install ui-next dependencies for PySide6 release build.'
            }
        }
    }

    if ($Clean -and (Test-Path $distPath)) {
        Remove-Item -Recurse -Force $distPath
    }
    if ($Clean -and $Package -and (Test-Path $buildPath)) {
        Remove-Item -Recurse -Force $buildPath
    }

    if ($Quick) {
        & $pythonExe -s -c "from xml_to_usda.qt_ui.entry import main" 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw 'Quick preview import check failed.'
        }
        New-Item -ItemType Directory -Force -Path $distPath | Out-Null
        @(
            '@echo off',
            'set "SPEEDASSEMBLY_PREVIEW_ROOT=%~dp0.."',
            'start "" "%SPEEDASSEMBLY_PREVIEW_ROOT%\.venv310\Scripts\pythonw.exe" "%SPEEDASSEMBLY_PREVIEW_ROOT%\scripts\launch_qt_gui.py"'
        ) | Set-Content -LiteralPath $previewLauncherPath -Encoding ASCII
        Write-Host "Quick preview ready: $previewLauncherPath"
        Write-Host 'This source-backed preview skips PyInstaller, packaged contracts, release ZIP, and smoke.'
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
        return
    }

    if ($Package) {
        Write-Host 'Running packaged contract tests ...'
        & $pythonExe -m pytest -q -m packaged
        if ($LASTEXITCODE -ne 0) {
            throw 'Packaged contract tests failed.'
        }
        if (-not (Test-Path $iconPath)) {
            throw "Missing application icon: $iconPath"
        }

        if (Test-Path $buildPath) {
            Remove-Item -Recurse -Force $buildPath
        }
        if (Test-Path $distPath) {
            Remove-Item -Recurse -Force $distPath
        }

        & $pythonExe -s -m xml_to_usda.qt_ui.release_build --source-ui-root $qtUiSourceRoot --staging-root $qtUiStagingRoot --jpeg-quality 85
        if ($LASTEXITCODE -ne 0) {
            throw 'Qt UI asset staging failed.'
        }

        $pyInstallerArgs = @(
            '-m', 'PyInstaller',
            '--noconfirm',
            '--clean',
            '--onefile',
            '--windowed',
            '--name', 'SpeedAssembly',
            '--icon', $iconPath,
            '--additional-hooks-dir', $hooksPath,
            '--paths', (Join-Path $repoRoot 'src'),
            '--add-data', "$qtUiStagingRoot;xml_to_usda/qt_ui",
            '--distpath', $distPath,
            '--workpath', $buildPath,
            '--specpath', $buildPath,
            $launcherScript
        )

        $qtExcludes = @(
            'PySide6.QtBluetooth',
            'PySide6.QtCharts',
            'PySide6.QtDataVisualization',
            'PySide6.QtDesigner',
            'PySide6.QtGraphs',
            'PySide6.QtGraphsWidgets',
            'PySide6.QtHelp',
            'PySide6.QtHttpServer',
            'PySide6.QtLocation',
            'PySide6.QtMultimedia',
            'PySide6.QtMultimediaWidgets',
            'PySide6.QtNfc',
            'PySide6.QtPdf',
            'PySide6.QtPdfWidgets',
            'PySide6.QtPositioning',
            'PySide6.QtPrintSupport',
            'PySide6.QtQml',
            'PySide6.QtQuick',
            'PySide6.QtQuick3D',
            'PySide6.QtQuickControls2',
            'PySide6.QtQuickWidgets',
            'PySide6.QtRemoteObjects',
            'PySide6.QtScxml',
            'PySide6.QtSensors',
            'PySide6.QtSerialBus',
            'PySide6.QtSerialPort',
            'PySide6.QtSql',
            'PySide6.QtStateMachine',
            'PySide6.QtSvg',
            'PySide6.QtSvgWidgets',
            'PySide6.QtTextToSpeech',
            'PySide6.QtUiTools',
            'PySide6.QtVirtualKeyboard',
            'PySide6.QtWebChannel',
            'PySide6.QtWebEngineCore',
            'PySide6.QtWebEngineQuick',
            'PySide6.QtWebEngineWidgets',
            'PySide6.QtWebSockets',
            'PySide6.QtNetwork',
            'PySide6.QtNetworkAuth'
        )
        foreach ($exclude in $qtExcludes) {
            $pyInstallerArgs += @('--exclude-module', $exclude)
        }

        Write-Host "Building PySide6 release shell with $pythonExe ..."
        & $pythonExe -s @pyInstallerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'PyInstaller PySide6 release build failed.'
        }

        if (-not (Test-Path $exePath)) {
            throw "Expected release exe was not created: $exePath"
        }

        if (Test-Path $distWorkerExePath) {
            throw "External worker exe must not be distributed: $distWorkerExePath"
        }

        Write-BuildInfo -DistPath $distPath -ExePath $exePath -PythonExe $pythonExe -RepoRoot $repoRoot -BuildMode 'release'
        $bundlePath = Join-Path $distPath 'SpeedAssembly_release.zip'
        & $pythonExe -s -m xml_to_usda.release_bundle --repo-root $repoRoot --dist-path $distPath --zip-path $bundlePath
        if ($LASTEXITCODE -ne 0) {
            throw 'Release zip assembly failed.'
        }
        Write-Host "Built: $exePath"
        Write-Host "Release zip: $bundlePath"
        if (-not $SkipSmoke) {
            $smokeDir = Join-Path $distPath 'smoke'
            $smokeReportPath = Join-Path $smokeDir 'smoke_report.json'
            $smokeStdoutPath = Join-Path $smokeDir 'smoke_stdout.txt'
            $smokeStderrPath = Join-Path $smokeDir 'smoke_stderr.txt'
            $smokeInputPath = Join-Path $repoRoot 'samples\speedtree\simple_tree\variants\SimpleTree_01.xml'
            $smokeOutputPath = Join-Path $smokeDir 'SimpleTree_01.usda'
            New-Item -ItemType Directory -Force -Path $smokeDir | Out-Null
            Write-Host "Running packaged Detailed Cuts stability smoke..."
            # smoke --scenario packaged-stability --repeat 2 --fail-on-retry
            Remove-Item -LiteralPath $smokeReportPath -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $smokeStdoutPath -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $smokeStderrPath -ErrorAction SilentlyContinue
            $smokeArguments = Join-ProcessArguments @(
                'smoke',
                '--scenario',
                'packaged-stability',
                '--input',
                $smokeInputPath,
                '--output',
                $smokeOutputPath,
                '--report',
                $smokeReportPath,
                '--timeout-ms',
                '180000',
                '--repeat',
                '2',
                '--fail-on-retry'
            )
            $smokeStartInfo = New-Object System.Diagnostics.ProcessStartInfo
            $smokeStartInfo.FileName = $exePath
            $smokeStartInfo.Arguments = $smokeArguments
            $smokeStartInfo.UseShellExecute = $false
            $smokeStartInfo.RedirectStandardOutput = $true
            $smokeStartInfo.RedirectStandardError = $true
            $smokeStartInfo.CreateNoWindow = $true
            $smokeProcess = New-Object System.Diagnostics.Process
            $smokeProcess.StartInfo = $smokeStartInfo
            if (-not $smokeProcess.Start()) {
                throw 'Packaged Detailed Cuts stability smoke did not start.'
            }
            $smokeStdout = $smokeProcess.StandardOutput.ReadToEnd()
            $smokeStderr = $smokeProcess.StandardError.ReadToEnd()
            $smokeProcess.WaitForExit()
            Set-Content -LiteralPath $smokeStdoutPath -Value $smokeStdout -Encoding UTF8
            Set-Content -LiteralPath $smokeStderrPath -Value $smokeStderr -Encoding UTF8
            if ($smokeProcess.ExitCode -ne 0) {
                if (-not [string]::IsNullOrWhiteSpace($smokeStderr)) {
                    Write-Host $smokeStderr.Trim()
                }
                if (Test-Path $smokeReportPath) {
                    $failedSmokeReport = Get-Content -LiteralPath $smokeReportPath -Raw | ConvertFrom-Json
                    foreach ($failedScenario in @($failedSmokeReport.scenarios | Where-Object { -not $_.passed })) {
                        Write-Host ("Smoke failure [{0}]: {1}" -f $failedScenario.name, $failedScenario.error)
                    }
                }
                throw "Packaged Detailed Cuts stability smoke failed. Report: $smokeReportPath"
            }
            if (-not (Test-Path $smokeReportPath)) {
                throw "Packaged Detailed Cuts stability smoke did not write report: $smokeReportPath"
            }
            $smokeReport = Get-Content -LiteralPath $smokeReportPath -Raw | ConvertFrom-Json
            if (-not $smokeReport.passed) {
                throw "Packaged Detailed Cuts stability smoke report failed: $smokeReportPath"
            }
            Write-Host "Packaged Detailed Cuts stability smoke passed: $smokeReportPath"

            $recoveryReportPath = Join-Path $smokeDir 'smoke_recovery_report.json'
            $recoveryArguments = Join-ProcessArguments @(
                'smoke',
                '--scenario',
                'fracture-preview-recovery',
                '--input',
                $smokeInputPath,
                '--output',
                $smokeOutputPath,
                '--report',
                $recoveryReportPath,
                '--timeout-ms',
                '180000'
            )
            $recoveryStartInfo = New-Object System.Diagnostics.ProcessStartInfo
            $recoveryStartInfo.FileName = $exePath
            $recoveryStartInfo.Arguments = $recoveryArguments
            $recoveryStartInfo.UseShellExecute = $false
            $recoveryStartInfo.CreateNoWindow = $true
            $recoveryProcess = New-Object System.Diagnostics.Process
            $recoveryProcess.StartInfo = $recoveryStartInfo
            if (-not $recoveryProcess.Start()) {
                throw 'Packaged Fracture worker recovery smoke did not start.'
            }
            $recoveryProcess.WaitForExit()
            if ($recoveryProcess.ExitCode -ne 0 -or -not (Test-Path $recoveryReportPath)) {
                throw "Packaged Fracture worker recovery smoke failed. Report: $recoveryReportPath"
            }
            $recoveryReport = Get-Content -LiteralPath $recoveryReportPath -Raw | ConvertFrom-Json
            if (-not $recoveryReport.passed) {
                throw "Packaged Fracture worker recovery smoke report failed: $recoveryReportPath"
            }
            Write-Host "Packaged Fracture worker recovery smoke passed: $recoveryReportPath"
        }
        else {
            Write-Host "Skipping packaged smoke because -SkipSmoke was supplied."
        }
        if ($OpenOutput) {
            Invoke-Item $distPath
        }
    }
}
finally {
    Pop-Location
}
