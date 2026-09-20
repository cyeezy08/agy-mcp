$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..
Write-Host '== agy-mcp CI ==' -ForegroundColor Cyan
uv sync --group dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run ruff check src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run ruff format --check src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (Test-Path tests) { uv run pytest -q --tb=short; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
Write-Host 'CI passed.' -ForegroundColor Green
