$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
& "$projectRoot/backend/.venv/Scripts/python.exe" "$PSScriptRoot/prepare.py"
if ($LASTEXITCODE -ne 0) { throw 'Docker settings preparation failed' }
& docker compose --project-directory $projectRoot --env-file "$PSScriptRoot/.env" -f "$projectRoot/compose.yaml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed' }
