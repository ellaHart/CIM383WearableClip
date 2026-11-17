# Copies device/ onto the CIRCUITPY drive. Never deletes anything on the board.
# Usage (from the repo folder):  .\tools\deploy.ps1          (or -Drive E: if the letter changes)
param([string]$Drive = "D:")

$source = Join-Path $PSScriptRoot "..\device"
$target = "$Drive\"

if (-not (Test-Path (Join-Path $target "boot_out.txt"))) {
    Write-Error "$Drive doesn't look like CIRCUITPY (no boot_out.txt). Is the board plugged in?"
    exit 1
}

robocopy $source $target /E /XF .gitkeep /NJH /NJS /NDL /NP
if ($LASTEXITCODE -ge 8) {
    Write-Error "Copy failed (robocopy exit code $LASTEXITCODE). If CIRCUITPY is read-only, reset without holding IO14."
    exit 1
}
Write-Host "Deployed device/ to $Drive - the board restarts code.py automatically."
exit 0
