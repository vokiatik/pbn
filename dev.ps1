Param(
    [string]$ComposeFile = "docker-compose.yml",
    [string]$ProjectName = "pbn",
    [int]$HealthTimeoutSeconds = 120,
    [string]$BackendHealthUrl = "http://localhost:8080/healthz",
    [switch]$EnableServiceLogTailing = $true
)

$ErrorActionPreference = "Stop"
$script:TranscriptStarted = $false
$script:TranscriptPath = Join-Path (Get-Location) ("dev_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$script:LogFiles = @{}

function Stop-DevTranscript {
    if ($script:TranscriptStarted) {
        try {
            Stop-Transcript | Out-Null
        }
        catch {
            # Ignore transcript shutdown errors.
        }
        $script:TranscriptStarted = $false
    }
}

try {
    Start-Transcript -Path $script:TranscriptPath -Append | Out-Null
    $script:TranscriptStarted = $true
}
catch {
    Write-Host "[warn] Could not start transcript logging: $($_.Exception.Message)" -ForegroundColor Yellow
}

function Write-Step {
    Param([string]$Message)
    Write-Host "[step] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    Param([string]$Message)
    Write-Host "[ok] $Message" -ForegroundColor Green
}

function Write-Warn {
    Param([string]$Message)
    Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Fail {
    Param([string]$Message)
    Write-Host "[error] $Message" -ForegroundColor Red
    Stop-DevTranscript
    exit 1
}

if (-not (Test-Path -Path $ComposeFile)) {
    Fail "$ComposeFile not found in current directory"
}

function Invoke-Compose {
    Param([string[]]$ComposeArgs)
    & docker compose -p $ProjectName -f $ComposeFile @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "docker compose command failed: $($ComposeArgs -join ' ')"
    }
}

function Start-ServiceLogTail {
    Param([string]$Service)

    if (-not $EnableServiceLogTailing) {
        return
    }

    $logPath = Join-Path (Get-Location) ("{0}_{1}.log" -f $Service, (Get-Date -Format "yyyyMMdd_HHmmss"))
    $script:LogFiles[$Service] = $logPath

    "[{0}] Starting log tail for service '{1}'" -f (Get-Date -Format "s"), $Service | Out-File -FilePath $logPath -Encoding utf8 -Append

    $jobName = "{0}-logs-{1}" -f $ProjectName, $Service
    $existingJob = Get-Job -Name $jobName -ErrorAction SilentlyContinue
    if ($null -ne $existingJob) {
        Stop-Job -Id $existingJob.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $existingJob.Id -Force -ErrorAction SilentlyContinue
    }

    Start-Job -Name $jobName -ScriptBlock {
        Param($ProjectNameValue, $ComposeFileValue, $ServiceValue, $LogPathValue)

        & docker compose -p $ProjectNameValue -f $ComposeFileValue logs -f --no-color --tail 0 $ServiceValue 2>&1 |
            Tee-Object -FilePath $LogPathValue -Append | Out-Host
    } -ArgumentList $ProjectName, $ComposeFile, $Service, $logPath | Out-Null

    Write-Ok "$Service logs are streaming to $logPath"
}

function Get-ServiceContainerId {
    Param([string]$Service)
    $id = (& docker compose -p $ProjectName -f $ComposeFile ps -q $Service).Trim()
    if ([string]::IsNullOrWhiteSpace($id)) {
        Fail "Could not find container id for service: $Service"
    }
    return $id
}

function Wait-ServiceHealthy {
    Param([string]$Service)

    $containerId = Get-ServiceContainerId -Service $Service
    Write-Host "[wait] Waiting for $Service to become healthy..."

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $health = & docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}" $containerId 2>$null

        if ($health -eq "healthy") {
            Write-Ok "$Service is healthy"
            return
        }

        if ($health -eq "no-healthcheck") {
            Write-Warn "$Service has no healthcheck; continuing"
            return
        }

        Start-Sleep -Seconds 2
    }

    Write-Host "[error] Timed out waiting for $Service health" -ForegroundColor Red
    & docker compose -p $ProjectName -f $ComposeFile logs $Service
    exit 1
}

function Wait-BackendHttp {
    Write-Host "[wait] Waiting for backend health endpoint..."
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -UseBasicParsing -Uri $BackendHealthUrl -Method GET -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                Write-Ok "backend health endpoint is reachable"
                return
            }
        }
        catch {
            # Retry until timeout
        }

        Start-Sleep -Seconds 2
    }

    Write-Host "[error] Timed out waiting for backend health endpoint" -ForegroundColor Red
    & docker compose -p $ProjectName -f $ComposeFile logs backend
    exit 1
}

Write-Step "Stopping and removing existing containers"
Invoke-Compose -ComposeArgs @("down", "--remove-orphans")

Write-Step "Starting infrastructure (postgres, redis)"
Invoke-Compose -ComposeArgs @("up", "-d", "--build", "--force-recreate", "postgres", "redis")
Wait-ServiceHealthy -Service "postgres"
Wait-ServiceHealthy -Service "redis"

Write-Step "Starting backend"
Invoke-Compose -ComposeArgs @("up", "-d", "--build", "--force-recreate", "backend")
Wait-BackendHttp

Write-Step "Starting worker and frontend"
Invoke-Compose -ComposeArgs @("up", "-d", "--build", "--force-recreate", "worker", "frontend")
Start-ServiceLogTail -Service "backend"
Start-ServiceLogTail -Service "worker"

Write-Step "Final service status"
Invoke-Compose -ComposeArgs @("ps")

Write-Ok "Fresh stack is up."
Write-Host "       Frontend: http://localhost:5173"
Write-Host "       Backend:  http://localhost:8080"

if ($script:TranscriptStarted) {
    Write-Host "[ok] Logs written to $script:TranscriptPath" -ForegroundColor Green
}

if ($EnableServiceLogTailing -and $script:LogFiles.Count -gt 0) {
    Write-Host "[ok] Service logs:" -ForegroundColor Green
    foreach ($serviceName in $script:LogFiles.Keys) {
        Write-Host "       $serviceName => $($script:LogFiles[$serviceName])"
    }
    Write-Host "       To stop background log jobs: Get-Job -Name '$ProjectName-logs-*' | Stop-Job; Get-Job -Name '$ProjectName-logs-*' | Remove-Job"
}

Stop-DevTranscript
