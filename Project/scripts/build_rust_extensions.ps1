param(
    [string]$ToolchainBin = '',
    [ValidateSet('xml_reader', 'usda_numbers')]
    [string[]]$Modules = @('xml_reader', 'usda_numbers')
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$env:PYO3_PYTHON = Join-Path $repo '.venv310/Scripts/python.exe'
$env:RUSTUP_TOOLCHAIN = '1.85.1'
if (-not $ToolchainBin) {
    $localBin = Join-Path $repo 'Project/tmp/rust-conversion/tools/rustup/toolchains/1.85.1-x86_64-pc-windows-msvc/bin'
    if (Test-Path (Join-Path $localBin 'cargo.exe')) { $ToolchainBin = $localBin }
}
if ($ToolchainBin) {
    $env:PATH = "$ToolchainBin;$env:PATH"
    $cargo = Join-Path $ToolchainBin 'cargo.exe'
    $env:CARGO_HOME = Join-Path $repo 'Project/tmp/rust-conversion/tools/cargo'
} else { $cargo = 'cargo' }
$env:TMP = Join-Path $repo 'Project/tmp/rust-extensions/compiler-temp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
foreach ($module in $Modules) {
    $extension = @{ xml_reader = '_xml_reader'; usda_numbers = '_usda_numbers' }[$module]
    & $cargo build --release --locked --manifest-path (Join-Path $repo "Project/native/$module/Cargo.toml")
    if ($LASTEXITCODE -ne 0) { throw "Rust $module build failed." }
    Copy-Item -LiteralPath (Join-Path $repo "Project/native/$module/target/release/$extension.dll") -Destination (Join-Path $repo "Project/src/xml_to_usda/$extension.pyd")
}
