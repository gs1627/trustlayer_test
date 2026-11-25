param(
    [switch]$SyncDependencies,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-NativeCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Arguments = @()
    )

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 1> $null 2> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Resolve-Python311 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Invoke-NativeCheck -Exe "py" -Arguments @("-3.11", "--version")) {
            return @{ Exe = "py"; PrefixArgs = @("-3.11") }
        }
    }

    $candidatePaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($candidate in $candidatePaths) {
        if ($candidate -and (Test-Path $candidate)) {
            if (Invoke-NativeCheck -Exe $candidate -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) {
                return @{ Exe = $candidate; PrefixArgs = @() }
            }
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Invoke-NativeCheck -Exe "python" -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) {
            return @{ Exe = "python"; PrefixArgs = @() }
        }
    }

    throw "Python 3.11+ was not found. Install Python 3.11 and ensure it is registered with py or installed under LocalAppData\Programs\Python\Python311."
}

$venvCreated = $false
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python virtual environment..."
    $pyCmd = Resolve-Python311
    & $pyCmd.Exe @($pyCmd.PrefixArgs + @("-m", "venv", ".venv"))
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
    $venvCreated = $true
}

$python = ".\.venv\Scripts\python.exe"

$needsInstall = $venvCreated -or $SyncDependencies.IsPresent
if (-not $needsInstall) {
    $packageCheckCode = "import importlib.metadata as m; [m.version(p) for p in ('fastapi','uvicorn','httpx','websockets','pydantic-settings','sqlalchemy','alembic','aiosqlite','asyncpg','python-multipart','pytest','pytest-asyncio')]"
    if (-not (Invoke-NativeCheck -Exe $python -Arguments @("-c", $packageCheckCode))) {
        $needsInstall = $true
    }
}

if ($needsInstall) {
    Write-Host "Installing backend dependencies from requirements.txt..."
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
} else {
    Write-Host "Using existing virtual environment dependencies (pass -SyncDependencies to reinstall)."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Add DETECTIF_API_KEY before testing provider endpoints."
}

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", "$Port")
if (-not $NoReload) {
    $uvicornArgs += "--reload"
}

Write-Host "Starting TRUSTLAYER backend at http://${BindHost}:${Port} ..."
& $python @uvicornArgs
