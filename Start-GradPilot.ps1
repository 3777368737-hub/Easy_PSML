param(
    [ValidateSet("Menu", "Stop", "Status")]
    [string]$Action = "Menu"
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$runtimeFile = Join-Path $projectRoot ".gradpilot-runtime.json"
$backendUrl = "http://127.0.0.1:8000"
$frontendUrl = "http://localhost:3000"
$backendOutLog = Join-Path $projectRoot "backend-server.out.log"
$backendErrLog = Join-Path $projectRoot "backend-server.err.log"
$frontendOutLog = Join-Path $projectRoot "frontend-dev.out.log"
$frontendErrLog = Join-Path $projectRoot "frontend-dev.err.log"

$Host.UI.RawUI.WindowTitle = "GradPilot Control"

function Test-PortListening {
    param([int]$Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(400)) {
            return $false
        }
        $client.EndConnect($result)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-BackendReady {
    try {
        $response = Invoke-RestMethod -Uri "$backendUrl/health" -TimeoutSec 2
        return $response.ok -eq $true -and $response.version -eq "1.1.0"
    }
    catch {
        return $false
    }
}

function Test-FrontendReady {
    try {
        $response = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content -match "GradPilot"
    }
    catch {
        return $false
    }
}

function Test-ApiKeyConfigured {
    $envFile = Join-Path $backendDir ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $false
    }

    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*DEEPSEEK_API_KEY\s*=\s*(.+?)\s*$') {
            $value = $matches[1].Trim().Trim('"').Trim("'")
            return $value.Length -gt 0 -and $value -notmatch '^your_'
        }
    }

    return $false
}

function Test-QwenApiKeyConfigured {
    $envFile = Join-Path $backendDir ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $false
    }

    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*(QWEN_API_KEY|DASHSCOPE_API_KEY)\s*=\s*(.+?)\s*$') {
            $value = $matches[2].Trim().Trim('"').Trim("'")
            if ($value.Length -gt 0 -and $value -notmatch '^your_') {
                return $true
            }
        }
    }

    return $false
}

function Get-ListenerProcess {
    param([int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        return @()
    }

    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    $processes = @()
    foreach ($processId in $processIds) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if ($process) {
            $processes += $process
        }
    }
    return $processes
}

function Assert-PortAvailableForGradPilot {
    param(
        [int]$Port,
        [scriptblock]$ReadyCheck,
        [string]$ServiceName
    )

    if (-not (Test-PortListening -Port $Port)) {
        return
    }
    if (& $ReadyCheck) {
        return
    }

    throw "Port $Port is occupied by another program. GradPilot $ServiceName was not started."
}

function Ensure-BackendEnvironment {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $systemPython) {
            throw "Python was not found."
        }
        Write-Host "Creating the backend virtual environment..." -ForegroundColor Cyan
        & $systemPython.Source -m venv (Join-Path $backendDir ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the backend virtual environment."
        }
    }

    & $backendPython -c "import fastapi, uvicorn, httpx, docx, pypdf, reportlab, multipart" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
        & $backendPython -m pip install -r (Join-Path $backendDir "requirements.txt") --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install backend dependencies."
        }
    }
}

function Ensure-FrontendEnvironment {
    $nextCommand = Join-Path $frontendDir "node_modules\.bin\next.cmd"
    if (Test-Path -LiteralPath $nextCommand) {
        return
    }

    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        throw "Node.js/npm was not found."
    }

    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location $frontendDir
    try {
        & $npmCommand.Source ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install frontend dependencies."
        }
    }
    finally {
        Pop-Location
    }
}

function Start-HiddenService {
    param(
        [string]$WorkingDirectory,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$OutLog,
        [string]$ErrLog
    )

    return Start-Process `
        -FilePath $Executable `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru
}

function Start-GradPilotServices {
    Assert-PortAvailableForGradPilot -Port 8000 -ReadyCheck { Test-BackendReady } -ServiceName "backend"
    Assert-PortAvailableForGradPilot -Port 3000 -ReadyCheck { Test-FrontendReady } -ServiceName "frontend"

    Ensure-BackendEnvironment
    Ensure-FrontendEnvironment

    if (-not (Test-PortListening -Port 8000)) {
        $null = Start-HiddenService `
            -WorkingDirectory $backendDir `
            -Executable $backendPython `
            -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
            -OutLog $backendOutLog `
            -ErrLog $backendErrLog
    }

    if (-not (Test-PortListening -Port 3000)) {
        $npmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source
        $null = Start-HiddenService `
            -WorkingDirectory $frontendDir `
            -Executable $npmCommand `
            -Arguments @("run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000") `
            -OutLog $frontendOutLog `
            -ErrLog $frontendErrLog
    }

    Write-Host "Waiting for GradPilot services..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $backendReady = Test-BackendReady
        $frontendReady = Test-FrontendReady
        if ($backendReady -and $frontendReady) {
            break
        }
        Start-Sleep -Milliseconds 800
    } while ((Get-Date) -lt $deadline)

    if (-not $backendReady) {
        throw "The backend did not become ready within 90 seconds. Select L to inspect the logs."
    }
    if (-not $frontendReady) {
        throw "The frontend did not become ready within 90 seconds. Select L to inspect the logs."
    }

    $backendListener = Get-ListenerProcess -Port 8000 | Select-Object -First 1
    $frontendListener = Get-ListenerProcess -Port 3000 | Select-Object -First 1
    @{
        backend_pid = if ($backendListener) { [int]$backendListener.ProcessId } else { $null }
        frontend_pid = if ($frontendListener) { [int]$frontendListener.ProcessId } else { $null }
        started_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding ASCII

    Write-Host "GradPilot is running." -ForegroundColor Green
    Start-Process $frontendUrl
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    if (-not $ProcessId) {
        return
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {
        return
    }

    & taskkill.exe /PID $ProcessId /T /F *> $null
}

function Stop-GradPilotServices {
    $trackedIds = @()
    if (Test-Path -LiteralPath $runtimeFile) {
        try {
            $runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
            if ($runtime.backend_pid) {
                $trackedIds += [int]$runtime.backend_pid
            }
            if ($runtime.frontend_pid) {
                $trackedIds += [int]$runtime.frontend_pid
            }
        }
        catch {
            Write-Host "The saved process file could not be read. Port checks will still be used." -ForegroundColor Yellow
        }
    }

    foreach ($processId in ($trackedIds | Select-Object -Unique)) {
        Stop-ProcessTree -ProcessId $processId
    }

    foreach ($port in @(8000, 3000)) {
        foreach ($process in (Get-ListenerProcess -Port $port)) {
            $commandLine = [string]$process.CommandLine
            if ($commandLine -like "*$projectRoot*") {
                Stop-ProcessTree -ProcessId ([int]$process.ProcessId)
            }
            else {
                Write-Host "Port $port belongs to another program and was left untouched." -ForegroundColor Yellow
            }
        }
    }

    if (Test-Path -LiteralPath $runtimeFile) {
        Remove-Item -LiteralPath $runtimeFile -Force
    }

    $deadline = (Get-Date).AddSeconds(15)
    do {
        $portsReleased = -not (Test-PortListening -Port 8000) -and -not (Test-PortListening -Port 3000)
        if ($portsReleased) {
            break
        }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)

    if ($portsReleased) {
        Write-Host "GradPilot services have stopped." -ForegroundColor Green
    }
    else {
        Write-Host "Some GradPilot processes may still be running. Check ports 3000 and 8000." -ForegroundColor Yellow
    }
}

function Show-ServiceLogs {
    Clear-Host
    Write-Host "==================== Backend log ====================" -ForegroundColor Cyan
    if ((Test-Path -LiteralPath $backendErrLog) -and (Get-Item -LiteralPath $backendErrLog).Length -gt 0) {
        Get-Content -LiteralPath $backendErrLog -Tail 30
    }
    elseif ((Test-Path -LiteralPath $backendOutLog) -and (Get-Item -LiteralPath $backendOutLog).Length -gt 0) {
        Get-Content -LiteralPath $backendOutLog -Tail 30
    }
    else {
        Write-Host "(no backend log output)" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "=================== Frontend log ====================" -ForegroundColor Cyan
    if ((Test-Path -LiteralPath $frontendOutLog) -and (Get-Item -LiteralPath $frontendOutLog).Length -gt 0) {
        Get-Content -LiteralPath $frontendOutLog -Tail 30
    }
    elseif ((Test-Path -LiteralPath $frontendErrLog) -and (Get-Item -LiteralPath $frontendErrLog).Length -gt 0) {
        Get-Content -LiteralPath $frontendErrLog -Tail 30
    }
    else {
        Write-Host "(no frontend log output)" -ForegroundColor DarkGray
    }

    Write-Host ""
    [void](Read-Host "Press Enter to return to the control center")
}

function Write-ControlStatus {
    Clear-Host
    $backendReady = Test-BackendReady
    $frontendReady = Test-FrontendReady
    $backendPortUsed = Test-PortListening -Port 8000
    $frontendPortUsed = Test-PortListening -Port 3000

    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " GradPilot Control" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan

    if ($backendReady) {
        Write-Host " Backend : RUNNING  $backendUrl" -ForegroundColor Green
    }
    elseif ($backendPortUsed) {
        Write-Host " Backend : PORT 8000 CONFLICT" -ForegroundColor Red
    }
    else {
        Write-Host " Backend : STOPPED" -ForegroundColor Yellow
    }

    if ($frontendReady) {
        Write-Host " Frontend: RUNNING  $frontendUrl" -ForegroundColor Green
    }
    elseif ($frontendPortUsed) {
        Write-Host " Frontend: PORT 3000 CONFLICT" -ForegroundColor Red
    }
    else {
        Write-Host " Frontend: STOPPED" -ForegroundColor Yellow
    }

    if (-not (Test-ApiKeyConfigured)) {
        Write-Host ""
        Write-Host " WARNING: DEEPSEEK_API_KEY is not configured." -ForegroundColor Yellow
        Write-Host " Configure it in: $backendDir\.env" -ForegroundColor Yellow
    }
    if (-not (Test-QwenApiKeyConfigured)) {
        Write-Host ""
        Write-Host " WARNING: QWEN_API_KEY or DASHSCOPE_API_KEY is not configured." -ForegroundColor Yellow
        Write-Host " Voice input will remain unavailable until it is configured." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host " [S] Start or check services"
    Write-Host " [T] Stop services"
    Write-Host " [R] Restart services"
    Write-Host " [B] Open GradPilot in the browser"
    Write-Host " [L] Show the latest backend and frontend logs"
    Write-Host " [Q] Stop services and quit"
    Write-Host "============================================================" -ForegroundColor DarkCyan
}

try {
    switch ($Action) {
        "Stop" {
            Stop-GradPilotServices
        }
        "Status" {
            Write-ControlStatus
        }
        default {
            try {
                Start-GradPilotServices
            }
            catch {
                Write-Host "Startup error: $($_.Exception.Message)" -ForegroundColor Red
                Write-Host "The control center remains open so you can inspect and retry." -ForegroundColor Yellow
                [void](Read-Host "Press Enter to continue")
            }

            while ($true) {
                Write-ControlStatus
                $choice = (Read-Host "Select an action").Trim().ToUpperInvariant()

                switch ($choice) {
                    "S" {
                        try {
                            Start-GradPilotServices
                        }
                        catch {
                            Write-Host "Startup error: $($_.Exception.Message)" -ForegroundColor Red
                            [void](Read-Host "Press Enter to continue")
                        }
                    }
                    "T" {
                        Stop-GradPilotServices
                        [void](Read-Host "Press Enter to continue")
                    }
                    "R" {
                        try {
                            Stop-GradPilotServices
                            Start-GradPilotServices
                        }
                        catch {
                            Write-Host "Restart error: $($_.Exception.Message)" -ForegroundColor Red
                            [void](Read-Host "Press Enter to continue")
                        }
                    }
                    "B" {
                        Start-Process $frontendUrl
                    }
                    "L" {
                        Show-ServiceLogs
                    }
                    "Q" {
                        Stop-GradPilotServices
                        break
                    }
                    default {
                        Write-Host "Unknown action: $choice" -ForegroundColor Yellow
                        Start-Sleep -Seconds 1
                    }
                }

                if ($choice -eq "Q") {
                    break
                }
            }
        }
    }
}
finally {
    if ($Action -eq "Menu") {
        Stop-GradPilotServices
        Write-Host ""
        Write-Host "GradPilot control center closed." -ForegroundColor DarkGray
    }
}
