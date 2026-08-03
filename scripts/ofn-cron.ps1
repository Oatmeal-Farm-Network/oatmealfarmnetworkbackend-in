param(
    [Parameter(Mandatory=$true)] [string] $Url,
    [string] $LogDir = "$env:TEMP\ofn-cron"
)

# Generic OFN cron runner.
# - POSTs to $Url
# - Logs response (or failure) to $LogDir\{job}-{yyyyMMdd}.log
# - Exits 0 on HTTP 2xx, 1 otherwise (so Task Scheduler shows failures)

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$job  = ($Url -replace '.*/', '')
$log  = Join-Path $LogDir ("{0}-{1}.log" -f $job, (Get-Date -Format 'yyyyMMdd'))
$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

try {
    $resp = Invoke-RestMethod -Uri $Url -Method POST -TimeoutSec 120 -ErrorAction Stop
    $body = $resp | ConvertTo-Json -Compress -Depth 5
    Add-Content -Path $log -Value "[$ts] OK $Url -> $body"
    exit 0
} catch {
    Add-Content -Path $log -Value "[$ts] FAIL $Url -> $($_.Exception.Message)"
    exit 1
}
