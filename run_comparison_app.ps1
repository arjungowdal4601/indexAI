param(
    [string]$CondaEnv = "compute",
    [string]$HostAddress = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 8501,
    [switch]$SkipDependencyInstall,
    [switch]$Help
)

if ($Help) {
    Write-Host @"
Run the document comparison backend and Streamlit frontend.

Usage:
  .\run_comparison_app.ps1
  .\run_comparison_app.ps1 -CondaEnv compute -BackendPort 8000 -FrontendPort 8501

Options:
  -CondaEnv      Conda environment name. Default: "compute"
  -HostAddress   Host address for both services. Default: "127.0.0.1"
  -BackendPort   FastAPI backend port. Default: 8000
  -FrontendPort  Streamlit frontend port. Default: 8501
  -SkipDependencyInstall
                 Skip the requirements.txt install fallback.
  -Help          Show this help message.
"@
    exit 0
}

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcPath = Join-Path $Root "src"
$BackendUrl = "http://${HostAddress}:$BackendPort"
$FrontendUrl = "http://${HostAddress}:$FrontendPort"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "conda was not found on PATH. Open an Anaconda/Miniconda PowerShell prompt and rerun this script."
}

if (-not $SkipDependencyInstall) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $dependencyCheck = & conda run -n $CondaEnv python -c "import fastapi, uvicorn, streamlit, multipart" 2>&1
        $dependencyExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($dependencyExitCode -ne 0) {
        Write-Host "Installing missing Python dependencies into Conda env '$CondaEnv'..."
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & conda run -n $CondaEnv python -m pip install -r (Join-Path $Root "requirements.txt")
            $installExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($installExitCode -ne 0) {
            throw "Dependency installation failed in Conda env '$CondaEnv'."
        }
    }
}

$env:PYTHONPATH = $SrcPath
$env:DOC_COMPARING_API_BASE_URL = $BackendUrl

Write-Host "Starting document comparison app"
Write-Host "Repo:      $Root"
Write-Host "Conda env: $CondaEnv"
Write-Host "Backend:   $BackendUrl"
Write-Host "Frontend:  $FrontendUrl"
Write-Host ""
Write-Host "Press Ctrl+C to stop both services."
Write-Host ""

$jobs = @()

try {
    $backendJob = Start-Job -Name "doc-comparing-backend" -ScriptBlock {
        param($Root, $CondaEnv, $HostAddress, $BackendPort, $SrcPath)
        Set-Location $Root
        $env:PYTHONPATH = $SrcPath
        conda run -n $CondaEnv python -m uvicorn backend.app:app --host $HostAddress --port $BackendPort 2>&1
    } -ArgumentList $Root, $CondaEnv, $HostAddress, $BackendPort, $SrcPath
    $jobs += $backendJob

    Start-Sleep -Seconds 2

    $frontendJob = Start-Job -Name "doc-comparing-frontend" -ScriptBlock {
        param($Root, $CondaEnv, $HostAddress, $FrontendPort, $SrcPath, $BackendUrl)
        Set-Location $Root
        $env:PYTHONPATH = $SrcPath
        $env:DOC_COMPARING_API_BASE_URL = $BackendUrl
        conda run -n $CondaEnv python -m streamlit run frontend/streamlit_app.py --server.address $HostAddress --server.port $FrontendPort --browser.gatherUsageStats false 2>&1
    } -ArgumentList $Root, $CondaEnv, $HostAddress, $FrontendPort, $SrcPath, $BackendUrl
    $jobs += $frontendJob

    while ($true) {
        foreach ($job in $jobs) {
            Receive-Job -Job $job -ErrorAction Continue
        }

        $failed = $jobs | Where-Object { $_.State -in @("Failed", "Stopped", "Completed") }
        if ($failed) {
            foreach ($job in $failed) {
                Receive-Job -Job $job -ErrorAction SilentlyContinue
                Write-Host "Service stopped: $($job.Name) [$($job.State)]"
            }
            break
        }

        Start-Sleep -Seconds 1
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping services..."
    foreach ($job in $jobs) {
        if ($job.State -eq "Running") {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
        }
        Receive-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped backend and frontend."
}
