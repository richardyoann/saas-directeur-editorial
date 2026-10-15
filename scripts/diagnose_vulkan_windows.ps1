# Diagnostic Vulkan / SD.cpp — lecture seule (Windows PowerShell)

$ErrorActionPreference = 'Continue'
Write-Host "=== GPU Windows et pilote ==="
Get-CimInstance Win32_VideoController |
  Select-Object Name, DriverVersion, AdapterRAM |
  Format-Table -AutoSize

Write-Host "=== Outil Vulkan (ne garantit pas le bon GPU) ==="
$vulkan = Get-Command vulkaninfo -ErrorAction SilentlyContinue
if ($null -eq $vulkan) {
  Write-Host "vulkaninfo absent du PATH ; SDK/outils Vulkan non détectés."
} else {
  & $vulkan.Source --summary 2>&1 |
    Select-String 'deviceName|deviceType|driverName|Vulkan Instance Version|apiVersion' |
    Select-Object -First 18
}

Write-Host "=== Service d'images LOCAL (test réseau uniquement) ==="
try {
  $tcp = [System.Net.Sockets.TcpClient]::new()
  $result = $tcp.BeginConnect('127.0.0.1', 8082, $null, $null)
  $connected = $result.AsyncWaitHandle.WaitOne(1500, $false)
  if ($connected) {
    try { $tcp.EndConnect($result) | Out-Null } catch { $connected = $false }
  }
  Write-Host "Port 8082 local accessible : $connected"
  $tcp.Close()
} catch {
  Write-Host "Port 8082 local inaccessible"
}

Write-Host "Lecture seule terminée : aucune installation ni modification."
