# Copies device/ onto the CIRCUITPY drive. Never deletes anything on the board.
# Usage (from the repo folder):  .\tools\deploy.ps1          (or -Drive E: if the letter changes)
param([string]$Drive = "D:")

$source = Join-Path $PSScriptRoot "..\device"
$target = "$Drive\"

if (-not (Test-Path (Join-Path $target "boot_out.txt"))) {
    Write-Error "$Drive doesn't look like CIRCUITPY (no boot_out.txt). Is the board plugged in?"
    exit 1
}

# /R:2 /W:1: give up on a file after 2 quick retries instead of robocopy's default of retrying for days.
robocopy $source $target /E /XF .gitkeep /XD __pycache__ /R:2 /W:1 /NJH /NJS /NDL /NP
if ($LASTEXITCODE -ge 8) {
    Write-Error "Copy failed (robocopy exit code $LASTEXITCODE). If CIRCUITPY is read-only, reset without holding IO14."
    exit 1
}
Write-Host "Deployed device/ to $Drive - the board restarts code.py automatically."
exit 0
