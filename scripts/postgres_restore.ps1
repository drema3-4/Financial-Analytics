param([Parameter(Mandatory = $true)][string]$Archive)

$ErrorActionPreference = "Stop"
if (-not $env:SOURCE_DATABASE_URL -or -not $env:RESTORE_DATABASE_URL) {
  throw "SOURCE_DATABASE_URL and RESTORE_DATABASE_URL are required"
}
$sourceUrl = $env:SOURCE_DATABASE_URL.Replace("postgresql+psycopg:", "postgresql:")
$restoreUrl = $env:RESTORE_DATABASE_URL.Replace("postgresql+psycopg:", "postgresql:")
$sourceName = (& psql $sourceUrl --tuples-only --no-align --command="SELECT current_database()").Trim()
$restoreName = (& psql $restoreUrl --tuples-only --no-align --command="SELECT current_database()").Trim()
if ($sourceName -eq $restoreName) { throw "Refusing to restore into the source database" }
$relationCount = (& psql $restoreUrl --tuples-only --no-align --command="SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','p')").Trim()
if ($relationCount -ne "0") { throw "Restore database must be empty" }
& pg_restore "--dbname=$restoreUrl" --exit-on-error --single-transaction --no-owner --no-acl $Archive
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
& psql $restoreUrl --set=ON_ERROR_STOP=1 --command="ANALYZE" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ANALYZE failed" }
Write-Output "restore completed in a separate empty database"
