# Context Arbor one-line installer (Windows PowerShell).
#
#   irm https://raw.githubusercontent.com/renf0x/context-arbor/main/install.ps1 | iex
#
# Downloads the self-contained arbor.py and scaffolds memory and agent adapters.
#
# Target dir / agents can be overridden before piping to iex:
#   $env:ARBOR_TARGET = "C:\path\to\project"; $env:ARBOR_AGENTS = "generic,claude"
[CmdletBinding()]
param(
    [string]$Target = $(if ($env:ARBOR_TARGET) { $env:ARBOR_TARGET } else { "." }),
    [string]$Agents = $(if ($env:ARBOR_AGENTS) { $env:ARBOR_AGENTS } else { "all" })
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$raw = "https://raw.githubusercontent.com/renf0x/context-arbor/main/arbor.py"

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Error "Python 3.10+ is required but was not found on PATH."; exit 1 }

if (-not (Test-Path $Target)) { New-Item -ItemType Directory -Force -Path $Target | Out-Null }
$dest = Join-Path $Target "arbor.py"
Write-Host "Downloading arbor.py -> $dest"
Invoke-WebRequest -Uri $raw -OutFile $dest -UseBasicParsing

Write-Host "Scaffolding Context Arbor (agents: $Agents)"
Push-Location $Target
try { & $py arbor.py init --agents $Agents } finally { Pop-Location }

Write-Host ""
Write-Host "Done. Memory, Obsidian integration and session management are ready."
Write-Host "Search notes: python arbor.py memory query 'question'"
