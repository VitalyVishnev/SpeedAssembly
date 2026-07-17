[CmdletBinding()]
param(
    [ValidateSet('Core', 'Integration', 'Full')]
    [string]$Layer = 'Full'
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $repoRoot '.venv310\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    throw "Missing virtual environment python: $pythonExe"
}

$marker = switch ($Layer) {
    'Core' { 'core and not stress' }
    'Integration' { 'integration and not stress' }
    default { 'not stress and not packaged' }
}

Push-Location $repoRoot
try {
    & $pythonExe -m pytest -q -m $marker
    if ($LASTEXITCODE -ne 0) {
        throw "$Layer test layer failed."
    }
}
finally {
    Pop-Location
}
