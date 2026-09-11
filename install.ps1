# Castra installer for Windows.
# The work happens in install.py so that every platform runs the same logic;
# this wrapper only picks an interpreter. macOS and Linux users run install.sh.
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    # The py launcher ships with the python.org installer and is the most
    # reliable entry point on Windows; python.exe may be a Store alias stub.
    foreach ($candidate in @("py", "python", "python3")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        $args = if ($candidate -eq "py") { @("-3", "-c", "import sys; print(sys.executable)") }
                else { @("-c", "import sys; print(sys.executable)") }
        $resolved = & $found.Source @args 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) { return $resolved.Trim() }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Error "No Python found. Install Python 3 from python.org, then run this again."
    exit 1
}

Write-Host "using python: $python"
& $python (Join-Path $here "install.py") @args
exit $LASTEXITCODE
