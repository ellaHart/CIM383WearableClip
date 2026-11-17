# Shows the board's serial console (print output) in this window. Ctrl+C to stop.
# Usage (from the repo folder):  .\tools\serial.ps1          (or -Port COM5 if it's not COM7)
# Close any other serial monitor first (VS Code, Mu, PuTTY) - only one program can open the port.
param([string]$Port = "COM7")

$serial = New-Object System.IO.Ports.SerialPort $Port, 115200
$serial.DtrEnable = $true  # CircuitPython only sends output when DTR is on
try {
    $serial.Open()
} catch {
    Write-Error "Couldn't open $Port. Is the board plugged in, and is another serial monitor using it? Ports found: $([System.IO.Ports.SerialPort]::GetPortNames() -join ', ')"
    exit 1
}
Write-Host "Listening on $Port - press Ctrl+C to stop. Press the board's RST button to see startup messages."
try {
    while ($true) {
        $text = $serial.ReadExisting()
        if ($text) { Write-Host -NoNewline $text }
        Start-Sleep -Milliseconds 100
    }
} finally {
    $serial.Close()
}
