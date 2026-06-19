[CmdletBinding()]
param(
    [string]$DistPath = "dist-next",
    [int]$Iterations = 0,
    [int]$WorkerIterations = 50,
    [int]$UiIterations = 10,
    [int]$TimeoutMs = 180000,
    [switch]$SkipUi,
    [switch]$SkipWorker,
    [switch]$AllowRetry,
    [switch]$NoCrashDumps
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv310\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    throw "Missing virtual environment python: $pythonExe"
}

$distFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $DistPath))
$reportPath = Join-Path $distFullPath 'stability\stability_report.json'
$spruceBigLow = 'D:\3D Personal\XMLtoUSD_miscFiles\SkeletyalAssemblyTest_Spruce_Big_low.xml'
$skeletal28Mil = 'D:\3D Personal\XMLtoUSD_miscFiles\SkeletalAssemblyTest_03_28mil.xml'

$argsList = @(
    '-m',
    'xml_to_usda.qt_ui.stability_gate',
    '--dist-path',
    $distFullPath,
    '--report',
    $reportPath,
    '--worker-iterations',
    [string]$WorkerIterations,
    '--ui-iterations',
    [string]$UiIterations,
    '--timeout-ms',
    [string]$TimeoutMs,
    '--sample-profile',
    'spruce_big_low',
    '--sample-profile',
    'skeletal_28mil'
)

if ($SkipUi) {
    $argsList += '--skip-ui'
}
if ($SkipWorker) {
    $argsList += '--skip-worker'
}
if ($AllowRetry) {
    $argsList += '--allow-retry'
}
if ($NoCrashDumps) {
    $argsList += '--no-crash-dumps'
}
if ($Iterations -gt 0) {
    $argsList += @('--iterations', [string]$Iterations)
}

Write-Host "Running strict packaged stability gate..."
Write-Host "  Dist: $distFullPath"
Write-Host "  Report: $reportPath"
if ($Iterations -gt 0) {
    Write-Host "  Short override iterations: $Iterations"
}
else {
    Write-Host "  Worker iterations: $WorkerIterations"
    Write-Host "  UI iterations: $UiIterations"
}
Write-Host "  Required samples:"
Write-Host "    $spruceBigLow"
Write-Host "    $skeletal28Mil"
& $pythonExe -s @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Strict packaged stability gate failed. Report: $reportPath"
}
Write-Host "Strict packaged stability gate passed: $reportPath"
