# Examples: ./infra/docker/compose.ps1 up -d --wait; ./infra/docker/compose.ps1 ps
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
& docker compose --project-directory $projectRoot --env-file "$PSScriptRoot/.env" -f "$projectRoot/compose.yaml" @args
if ($LASTEXITCODE -ne 0) { throw "Compose failed (exit $LASTEXITCODE)" }
