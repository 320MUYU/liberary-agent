param([Parameter(Mandatory=$true)][string]$Snapshot)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$manifestPath = (Resolve-Path (Join-Path $Snapshot 'manifest.json')).Path
# stdin carries metadata, never credentials; Python preserves UTF-8 and exit codes.
& "$projectRoot/backend/.venv/Scripts/python.exe" -c @'
import subprocess, sys
from pathlib import Path
root, manifest = map(Path, sys.argv[1:])
command = ['docker', 'compose', '--project-directory', str(root), '--env-file', str(root/'infra/docker/.env'),
    '-f', str(root/'compose.yaml'), 'exec', '-T', 'api', 'python', '/opt/deploy/verify_migration.py']
with manifest.open('rb') as source:
    subprocess.run(command, stdin=source, check=True)
'@ $projectRoot $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Migration verification failed' }
