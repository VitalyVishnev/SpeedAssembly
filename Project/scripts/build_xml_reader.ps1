# Compatibility entrypoint for source setups that only need XML opening.
param([string]$ToolchainBin = '')
& (Join-Path $PSScriptRoot 'build_rust_extensions.ps1') -ToolchainBin $ToolchainBin -Modules xml_reader
