[CmdletBinding()]
param(
    [switch]$SkipGpuContainer
)

$ErrorActionPreference = "Continue"
$expectedNode = "24.21.0"
$expectedPnpm = "12.12.1"
$expectedPython = "3.12.12"
$expectedPoetry = "2.5.1"
$cudaImage = "nvidia/cuda:12.8.1-base-ubuntu24.04@sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2"
$failures = 0
$warnings = 0
$dockerReady = $false

function Write-Pass {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    $script:failures++
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-WarningResult {
    param([string]$Message)
    $script:warnings++
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Get-CommandOutput {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        return $null
    }

    $output = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    return (($output | Out-String).Trim())
}

Write-Host "Financial Analytics preflight"
Write-Host "Core failures exit non-zero; local-LLM/GPU checks are warnings only."
Write-Host ""

$runtime = [System.Runtime.InteropServices.RuntimeInformation]
Write-Host "OS: $($runtime::OSDescription)"
Write-Host "Architecture: $($runtime::OSArchitecture)"

try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $totalGiB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $freeGiB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    Write-Host "RAM: ${totalGiB} GiB total, ${freeGiB} GiB available"
} catch {
    Write-WarningResult "Could not read RAM through CIM."
}

try {
    $driveName = (Split-Path -Qualifier (Get-Location).Path).TrimEnd(":")
    if ($driveName) {
        $drive = Get-PSDrive -Name $driveName -ErrorAction Stop
        $freeGiB = [math]::Round($drive.Free / 1GB, 2)
        Write-Host "Workspace volume free: ${freeGiB} GiB"
    }
} catch {
    Write-WarningResult "Could not read free space for the workspace volume."
}

if ($IsWindows -or $env:OS -eq "Windows_NT") {
    if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
        $wslStatus = (& wsl.exe --status 2>&1 | Out-String)
        $statusExit = $LASTEXITCODE
        $wslList = (& wsl.exe --list --verbose 2>&1 | Out-String)
        $listExit = $LASTEXITCODE
        $wslList = $wslList -replace "`0", ""
        if ($statusExit -eq 0 -and $listExit -eq 0 -and $wslList -match "(?m)\s2\s*$") {
            Write-Pass "WSL2 is installed and a version 2 distribution is registered."
        } else {
            Write-Fail "WSL2 is required on Windows and no version 2 distribution was confirmed."
        }
    } else {
        Write-Fail "WSL2 is required on Windows but wsl.exe was not found."
    }
}

$gitVersion = Get-CommandOutput -Command "git" -Arguments @("--version")
if ($gitVersion) {
    Write-Pass $gitVersion
} else {
    Write-Fail "Git is missing or unusable."
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerVersion = Get-CommandOutput -Command "docker" -Arguments @("version", "--format", "{{.Server.Version}}")
    if ($dockerVersion) {
        $dockerOs = Get-CommandOutput -Command "docker" -Arguments @("info", "--format", "{{.OSType}}")
        if ($dockerOs -eq "linux") {
            $dockerReady = $true
            Write-Pass "Docker Engine $dockerVersion is reachable in Linux container mode."
        } else {
            Write-Fail "Docker Engine $dockerVersion is reachable, but Linux container mode is required."
        }
    } else {
        Write-Fail "Docker CLI exists, but the Linux Docker Engine is not reachable."
    }

    $composeVersion = Get-CommandOutput -Command "docker" -Arguments @("compose", "version", "--short")
    if ($composeVersion -and $composeVersion -match "^2\.") {
        Write-Pass "Docker Compose $composeVersion is available."
    } else {
        Write-Fail "Docker Compose v2 is missing or unusable."
    }
} else {
    Write-Fail "Docker CLI is missing."
    Write-Fail "Docker Compose v2 is unavailable because Docker is missing."
}

$nodeVersion = Get-CommandOutput -Command "node" -Arguments @("--version")
if ($nodeVersion -eq "v$expectedNode") {
    Write-Pass "Node.js $expectedNode matches the baseline."
} elseif ($nodeVersion) {
    Write-Fail "Node.js $nodeVersion is installed; expected v$expectedNode."
} else {
    Write-Fail "Node.js $expectedNode is missing."
}

$corepackVersion = Get-CommandOutput -Command "corepack" -Arguments @("--version")
if ($corepackVersion) {
    Write-Pass "Corepack $corepackVersion is available."
} else {
    Write-Fail "Corepack is missing or unusable."
}

$pnpmVersion = Get-CommandOutput -Command "pnpm" -Arguments @("--version")
if ($pnpmVersion -eq $expectedPnpm) {
    Write-Pass "pnpm $expectedPnpm matches the baseline."
} elseif ($pnpmVersion) {
    Write-Fail "pnpm $pnpmVersion is installed; expected $expectedPnpm."
} else {
    Write-Fail "pnpm $expectedPnpm is missing."
}

$pythonVersion = $null
$pythonInvocation = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidate = & py -3.12 -c "import platform; print(platform.python_version())" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $pythonVersion = ($candidate | Out-String).Trim()
        $pythonInvocation = "py -3.12"
    }
}

if (-not $pythonVersion) {
    foreach ($candidateCommand in @("python3", "python")) {
        $candidate = Get-CommandOutput -Command $candidateCommand -Arguments @("-c", "import platform; print(platform.python_version())")
        if ($candidate) {
            $pythonVersion = $candidate
            $pythonInvocation = $candidateCommand
            break
        }
    }
}

if ($pythonVersion -eq $expectedPython) {
    Write-Pass "Python $expectedPython matches the baseline ($pythonInvocation)."
} elseif ($pythonVersion) {
    Write-Fail "Python $pythonVersion is available through $pythonInvocation; expected $expectedPython."
} else {
    Write-Fail "Python $expectedPython is missing."
}

$poetryOutput = Get-CommandOutput -Command "poetry" -Arguments @("--version")
if ($poetryOutput -match "Poetry \(version ([0-9.]+)\)") {
    $poetryVersion = $Matches[1]
    if ($poetryVersion -eq $expectedPoetry) {
        Write-Pass "Poetry $expectedPoetry matches the baseline."
    } else {
        Write-Fail "Poetry $poetryVersion is installed; expected $expectedPoetry."
    }
} else {
    Write-Fail "Poetry $expectedPoetry is missing or unusable."
}

$nvidiaSmi = Get-CommandOutput -Command "nvidia-smi" -Arguments @("--query-gpu=name,driver_version,memory.total", "--format=csv,noheader")
if ($nvidiaSmi) {
    Write-Pass "Optional NVIDIA host GPU: $nvidiaSmi"
} else {
    Write-WarningResult "Optional NVIDIA GPU/driver was not detected; core remains usable."
}

if ($SkipGpuContainer) {
    Write-WarningResult "Optional GPU container check was skipped by request."
} elseif ($dockerReady -and $nvidiaSmi) {
    $gpuOutput = & docker run --rm --gpus all $cudaImage nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "Optional GPU passthrough works: $(($gpuOutput | Out-String).Trim())"
    } else {
        Write-WarningResult "Optional GPU passthrough check failed; core remains usable."
    }
} else {
    Write-WarningResult "Optional GPU passthrough check was not run because Docker or NVIDIA GPU is unavailable."
}

Write-Host ""
Write-Host "Summary: $failures core failure(s), $warnings warning(s)."
if ($failures -gt 0) {
    exit 1
}

exit 0
