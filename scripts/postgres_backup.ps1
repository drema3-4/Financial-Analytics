param([Parameter(Mandatory = $true)][string]$Output)

$ErrorActionPreference = "Stop"
if (-not $env:DATABASE_URL) { throw "DATABASE_URL is required" }
if (Test-Path -LiteralPath $Output) { throw "Refusing to overwrite an existing backup" }
$postgresUrl = $env:DATABASE_URL.Replace("postgresql+psycopg:", "postgresql:")
& pg_dump "--dbname=$postgresUrl" --format=custom --compress=9 --no-owner --no-acl "--file=$Output"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
& pg_restore --list $Output | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup archive catalog validation failed" }
Write-Output "backup created and archive catalog verified"
