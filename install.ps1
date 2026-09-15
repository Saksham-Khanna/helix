# Helix Installer for Windows (like opencode install.ps1)
# Usage:
#   irm https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install.ps1 | iex
#   irm https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install.ps1 | iex; Install-Helix -Version 0.1.0

param(
    [string]$Version = $env:VERSION,
    [switch]$NoModifyPath,
    [switch]$Help
)

$Repo = "Saksham-Khanna/terminal-assistant"
$App = "helix"

function Write-Info($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Warn($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host $msg -ForegroundColor Red }

if ($Help) {
    @"
Helix Installer (Windows)

Usage: install.ps1 [options]

Options:
  -Version <version>   Install specific version (e.g., 0.1.0)
  -NoModifyPath        Don't modify PATH
  -Help                Show this help

Examples:
  irm https://raw.githubusercontent.com/$Repo/main/install.ps1 | iex
  Install-Helix -Version 0.1.0

Other methods:
  pip install git+https://github.com/$Repo.git
  pipx install git+https://github.com/$Repo.git
"@
    exit 0
}

# --- detect python ---
$Python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $check = & $cmd -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>&1
            if ($LASTEXITCODE -eq 0) {
                $Python = $cmd
                Write-Info "Found Python at $cmd : $ver"
                break
            }
        }
    } catch {}
}

if (-not $Python) {
    Write-Err "Python 3.10+ is required but not found. Install from https://python.org"
    exit 1
}

# --- detect pip / pipx ---
$UsePipx = $false
try {
    $null = Get-Command pipx -ErrorAction Stop
    $UsePipx = $true
    Write-Info "Using pipx (isolated install)"
} catch {
    Write-Info "Using pip"
}

# --- build package spec ---
if ($Version) {
    $PkgSpec = "git+https://github.com/$Repo.git@v$Version"
    Write-Info "Installing $App v$Version from GitHub..."
} else {
    $PkgSpec = "git+https://github.com/$Repo.git"
    Write-Info "Installing $App latest from GitHub..."
}

# --- install ---
if ($UsePipx) {
    try {
        $list = pipx list 2>&1 | Out-String
        if ($list -match "package $App ") {
            Write-Info "Upgrading existing pipx install..."
            pipx upgrade $App --spec $PkgSpec 2>$null
            if ($LASTEXITCODE -ne 0) { pipx install $PkgSpec --force }
        } else {
            pipx install $PkgSpec --force
        }
    } catch {
        pipx install $PkgSpec --force
    }
} else {
    & $Python -m pip install --upgrade --user $PkgSpec
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed"
        exit 1
    }
}

# --- verify ---
try {
    $ver = agentic --version 2>&1 | Select-Object -First 1
    if ($LASTEXITCODE -eq 0) {
        Write-Info "agentic installed: $ver"
    }
} catch {
    Write-Warn "Installed but 'agentic' not in PATH. Add Python Scripts to PATH:"
    $UserBase = & $Python -m site --user-base 2>&1
    Write-Host "  $UserBase\Scripts" -ForegroundColor Yellow
    Write-Host '  Run: $env:PATH += $UserBase\Scripts' -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done! Next steps:" -ForegroundColor Green
Write-Host '  1. agentic setup          # Gemini/Groq API key wizard' -ForegroundColor Yellow
Write-Host '  2. agentic index          # index your project' -ForegroundColor Yellow
Write-Host '  3. agentic chat           # start coding' -ForegroundColor Yellow
Write-Host ""
Write-Host "Docs: https://github.com/$Repo#readme" -ForegroundColor DarkGray
