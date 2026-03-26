# =============================================================================
#  GridPaw / CoPaw  --  Install from local source (PowerShell)
#
#  Usage: Right-click this file -> "Run with PowerShell"
#         OR from a PowerShell terminal: .\scripts\install_local.ps1
#
#  No arguments needed. The source directory is automatically resolved
#  as the parent folder of this script (i.e. the project root).
# =============================================================================

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# 0. Paths
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$SourceDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$CopawHome = if ($env:COPAW_HOME) { $env:COPAW_HOME } else { Join-Path $HOME ".copaw" }
$CopawVenv = Join-Path $CopawHome "venv"
$CopawBin  = Join-Path $CopawHome "bin"
$VenvPython = Join-Path $CopawVenv "Scripts\python.exe"
$VenvCopaw  = Join-Path $CopawVenv "Scripts\copaw.exe"
$PythonVersion = "3.12"

Write-Host ""
Write-Host "[copaw] Installing CoPaw from local source"
Write-Host "[copaw] Source : $SourceDir"
Write-Host "[copaw] Target : $CopawHome"
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Validate source directory
# ---------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $SourceDir "pyproject.toml")) -and
    -not (Test-Path (Join-Path $SourceDir "setup.py"))) {
    Write-Error "pyproject.toml / setup.py not found in: $SourceDir"
    Write-Host "Make sure this script is inside the 'scripts' folder of the project."
    Read-Host "Press Enter to exit"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Ensure uv
# ---------------------------------------------------------------------------
function Find-Uv {
    # Already on PATH?
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) { return $uvCmd.Source }

    # Common install locations
    $candidates = @(
        "$HOME\.local\bin\uv.exe",
        "$HOME\.cargo\bin\uv.exe",
        "$env:LOCALAPPDATA\uv\uv.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

$uvExe = Find-Uv
if (-not $uvExe) {
    Write-Host "[copaw] uv not found. Installing via astral.sh..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Host "[copaw] astral.sh failed, trying GitHub Releases..."
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
        $url  = "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip"
        $zip  = Join-Path $env:TEMP "uv-install.zip"
        $dest = Join-Path $env:LOCALAPPDATA "uv"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Expand-Archive -Force -Path $zip -DestinationPath $dest
        Remove-Item $zip -Force
        $env:PATH = "$dest;$env:PATH"
    }
    $uvExe = Find-Uv
    if (-not $uvExe) {
        Write-Error "Failed to install uv. Please install manually: https://docs.astral.sh/uv/"
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host "[copaw] uv found: $uvExe"

# ---------------------------------------------------------------------------
# 3. Create / update virtual environment
# ---------------------------------------------------------------------------
if (Test-Path $CopawVenv) {
    Write-Host "[copaw] Existing environment found, upgrading..."
} else {
    Write-Host "[copaw] Creating Python $PythonVersion environment..."
}

& $uvExe venv $CopawVenv --python $PythonVersion --quiet --clear
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create virtual environment."
    Read-Host "Press Enter to exit"
    exit 1
}

$pyVer = & $VenvPython --version 2>&1
Write-Host "[copaw] Python environment ready ($pyVer)"

# ---------------------------------------------------------------------------
# 4. Build console frontend (optional)
# ---------------------------------------------------------------------------
$consoleDist = Join-Path $SourceDir "console\dist\index.html"
$consoleDest = Join-Path $SourceDir "src\copaw\console\index.html"
$consoleCopied = $false

if (-not (Test-Path $consoleDest)) {
    if (Test-Path $consoleDist) {
        Write-Host "[copaw] Copying console frontend assets..."
        $destDir = Split-Path $consoleDest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
        Copy-Item -Path (Join-Path $SourceDir "console\dist\*") -Destination $destDir -Recurse -Force
        $consoleCopied = $true
    } elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        $consoleDir = Join-Path $SourceDir "console"
        if (Test-Path (Join-Path $consoleDir "package.json")) {
            Write-Host "[copaw] Building console frontend (npm ci && npm run build)..."
            Push-Location $consoleDir
            npm ci
            if ($LASTEXITCODE -eq 0) { npm run build }
            Pop-Location
            if (Test-Path $consoleDist) {
                $destDir = Split-Path $consoleDest
                if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
                Copy-Item -Path (Join-Path $SourceDir "console\dist\*") -Destination $destDir -Recurse -Force
                $consoleCopied = $true
                Write-Host "[copaw] Console frontend built successfully."
            }
        }
    } else {
        Write-Host "[copaw] WARNING: npm not found - skipping console build."
        Write-Host "[copaw]          Install Node.js from https://nodejs.org/ to enable the web UI."
    }
}

# ---------------------------------------------------------------------------
# 5. Install CoPaw from local source
# ---------------------------------------------------------------------------
Write-Host "[copaw] Installing CoPaw from: $SourceDir"
& $uvExe pip install $SourceDir --python $VenvPython --prerelease=allow
$installErr = $LASTEXITCODE

# Cleanup copied console assets
if ($consoleCopied) {
    $destDir = Split-Path $consoleDest
    if (Test-Path $destDir) { Remove-Item $destDir -Recurse -Force -ErrorAction SilentlyContinue }
}

if ($installErr -ne 0) {
    Write-Error "Installation from source failed (exit code $installErr)."
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $VenvCopaw)) {
    Write-Error "Installation failed: copaw CLI not found at $VenvCopaw"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[copaw] CoPaw installed successfully."

# ---------------------------------------------------------------------------
# 6. Merge source_init templates into user data dirs
#
#     source_init\.copaw        -> $CopawHome (default ~/.copaw)
#     source_init\.copaw.secret -> ${CopawHome}.secret (matches CoPaw SECRET_DIR
#                                 when COPAW_SECRET_DIR is unset: WORKING_DIR + ".secret")
#
#     Skips installer-managed top-level names: venv, bin
# ---------------------------------------------------------------------------
function Copy-MergeFsItem {
    param(
        [Parameter(Mandatory = $true)]$Item,
        [Parameter(Mandatory = $true)][string]$DestPath
    )
    # Recursive merge: avoids Copy-Item "dir -> existing dir" nesting quirks.
    if ($Item.PSIsContainer) {
        if (-not (Test-Path -LiteralPath $DestPath)) {
            New-Item -ItemType Directory -Path $DestPath -Force | Out-Null
        }
        Get-ChildItem -LiteralPath $Item.FullName -Force | ForEach-Object {
            Copy-MergeFsItem -Item $_ -DestPath (Join-Path $DestPath $_.Name)
        }
    } else {
        $parent = Split-Path -Parent $DestPath
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $Item.FullName -Destination $DestPath -Force
    }
}

function Copy-SourceInitOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$FromDir,
        [Parameter(Mandatory = $true)][string]$ToDir,
        [string[]]$SkipTopLevel = @()
    )
    if (-not (Test-Path -LiteralPath $FromDir)) { return $false }
    if (-not (Test-Path -LiteralPath $ToDir)) {
        New-Item -ItemType Directory -Path $ToDir -Force | Out-Null
    }
    Get-ChildItem -LiteralPath $FromDir -Force | ForEach-Object {
        if ($SkipTopLevel -contains $_.Name) {
            Write-Host "[copaw]   skip (installer): $($_.Name)"
            return
        }
        $target = Join-Path $ToDir $_.Name
        Copy-MergeFsItem -Item $_ -DestPath $target
    }
    return $true
}

$SourceInitRoot = Join-Path $SourceDir "source_init"
$InitCopaw = Join-Path $SourceInitRoot ".copaw"
$InitSecret = Join-Path $SourceInitRoot ".copaw.secret"
$CopawSecretHome = "${CopawHome}.secret"

if (Test-Path -LiteralPath $InitCopaw) {
    Write-Host "[copaw] Merging source_init\.copaw -> $CopawHome ..."
    [void](Copy-SourceInitOverlay -FromDir $InitCopaw -ToDir $CopawHome -SkipTopLevel @("venv", "bin"))
    Write-Host "[copaw] Done (existing venv/bin left unchanged)."
} else {
    Write-Host "[copaw] No source_init\.copaw found, skip template merge."
}

if (Test-Path -LiteralPath $InitSecret) {
    Write-Host "[copaw] Merging source_init\.copaw.secret -> $CopawSecretHome ..."
    [void](Copy-SourceInitOverlay -FromDir $InitSecret -ToDir $CopawSecretHome)
    Write-Host "[copaw] Done."
} else {
    Write-Host "[copaw] No source_init\.copaw.secret found, skip secret template merge."
}

# ---------------------------------------------------------------------------
# 7. Create wrapper scripts in $CopawBin
# ---------------------------------------------------------------------------
if (-not (Test-Path $CopawBin)) { New-Item -ItemType Directory -Path $CopawBin | Out-Null }

# PowerShell wrapper
$ps1 = Join-Path $CopawBin "copaw.ps1"
@"
`$ErrorActionPreference = 'Stop'
`$CopawHome = if (`$env:COPAW_HOME) { `$env:COPAW_HOME } else { Join-Path `$HOME '.copaw' }
`$RealBin   = Join-Path `$CopawHome 'venv\Scripts\copaw.exe'
if (-not (Test-Path `$RealBin)) { Write-Error "CoPaw not found at `$CopawHome"; exit 1 }
& `$RealBin @args
"@ | Set-Content -Path $ps1 -Encoding UTF8
Write-Host "[copaw] Wrapper: $ps1"

# CMD wrapper
$cmd = Join-Path $CopawBin "copaw.cmd"
@"
@echo off
set "COPAW_HOME=%COPAW_HOME%"
if "%COPAW_HOME%"=="" set "COPAW_HOME=%USERPROFILE%\.copaw"
set "REAL_BIN=%COPAW_HOME%\venv\Scripts\copaw.exe"
if not exist "%REAL_BIN%" ( echo CoPaw not found & exit /b 1 )
"%REAL_BIN%" %*
"@ | Set-Content -Path $cmd -Encoding ASCII
Write-Host "[copaw] Wrapper: $cmd"

# ---------------------------------------------------------------------------
# 8. Add $CopawBin to user PATH
# ---------------------------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$CopawBin*") {
    $newPath = if ($userPath) { "$CopawBin;$userPath" } else { $CopawBin }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:PATH = "$CopawBin;$env:PATH"
    Write-Host "[copaw] Added $CopawBin to PATH."
} else {
    Write-Host "[copaw] $CopawBin already in PATH."
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================"
Write-Host " CoPaw installed successfully!"
Write-Host "============================================"
Write-Host " Install location : $CopawHome"
Write-Host " Python           : $pyVer"
Write-Host ""
Write-Host "Open a NEW terminal and run:"
Write-Host "  copaw init    # first-time setup"
Write-Host "  copaw app     # start CoPaw"
Write-Host ""

Read-Host "Press Enter to close"
