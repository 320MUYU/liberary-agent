param(
    [string]$MySqlDump = 'C:/Program Files/MySQL/MySQL Server 8.0/bin/mysqldump.exe',
    [string]$RestoreFrom = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$backendRoot = (Resolve-Path "$projectRoot/backend").Path
$pythonPath = "$backendRoot/.venv/Scripts/python.exe"
if ($RestoreFrom) {
    & $pythonPath "$PSScriptRoot/migrate.py" restore $RestoreFrom
    if ($LASTEXITCODE -ne 0) { throw 'Restore failed; source and snapshot remain available' }
    exit 0
}
if (-not (Test-Path -LiteralPath $MySqlDump)) { throw 'mysqldump executable not found' }
& "$PSScriptRoot/compose.ps1" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration' }
$runtimeRoot = "$backendRoot/data/docker-backups"
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

# Match the exact workspace interpreter and known services; never stop editor tools.
$sourceProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(python|chroma|uvicorn)\.exe$' -and
    $_.CommandLine -and $_.CommandLine.IndexOf($backendRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $_.CommandLine -match '(uvicorn app\.(main|mcp\.library):app|knowledge_worker\.py|chroma\.exe.*run.*--path)'
})
$sourceProcesses | Select-Object ProcessId,ParentProcessId,Name,CommandLine |
    ConvertTo-Json -Depth 3 | Set-Content -LiteralPath "$runtimeRoot/source-processes.json" -Encoding utf8
$writers = @($sourceProcesses | Where-Object { $_.CommandLine -notmatch 'chroma\.exe.*run.*--path' })
foreach ($sourceProcess in $writers) {
    Stop-Process -Id $sourceProcess.ProcessId -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
foreach ($sourceProcess in ($sourceProcesses | Where-Object { $_.CommandLine -match 'chroma\.exe.*run.*--path' })) {
    Stop-Process -Id $sourceProcess.ProcessId -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
$remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $sourceProcesses.ProcessId })
if ($remaining.Count -gt 0) { throw 'Source services are still running; backup aborted' }
Write-Host 'Source API, MCP, worker and Chroma paused. Original MySQL and files are retained.'
& $pythonPath "$PSScriptRoot/migrate.py" snapshot --mysqldump $MySqlDump
if ($LASTEXITCODE -ne 0) { throw 'Backup failed; source remains paused. See docs/docker-guide.md for recovery.' }
$backup = Get-ChildItem -LiteralPath $runtimeRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
if (-not $backup -or -not (Test-Path -LiteralPath "$($backup.FullName)/manifest.json")) { throw 'Complete snapshot not found' }
& $pythonPath "$PSScriptRoot/migrate.py" restore $backup.FullName
if ($LASTEXITCODE -ne 0) { throw "Restore failed; source and snapshot retained at $($backup.FullName)" }
Write-Host "Migration complete. Snapshot: $($backup.FullName)"
