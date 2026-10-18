# Démarrer un modèle de code local distinct du Qwen éditorial et de sd.cpp.
# Exemple PowerShell: .\scripts\start_opencode_llm_windows.ps1 -LlamaServerExe "C:\IA\llama.cpp\llama-server.exe"
param(
  [string]$LlamaServerExe = "llama-server.exe",
  [string]$HostIp = "",
  [int]$Port = 8083
)
$ErrorActionPreference = "Stop"
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port non autorisé" }
if (-not $HostIp) {
  $HostIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object { $_.InterfaceAlias -like "*WSL*" -and $_.IPAddress -like "172.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
}
if (-not $HostIp) {
  throw "IP Windows WSL introuvable; préciser -HostIp (Get-NetIPAddress)."
}
if (-not (Test-Path $LlamaServerExe)) {
  $binary = Get-Command $LlamaServerExe -ErrorAction SilentlyContinue
  if (-not $binary) { throw "llama-server.exe introuvable; fournir -LlamaServerExe." }
  $LlamaServerExe = $binary.Source
}
Write-Host ("Démarrage llama.cpp sur {0}:{1} (réseau WSL privé)." -f $HostIp,$Port)
Write-Host "Modèle HF: unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
Write-Host "Premier démarrage: téléchargement de plusieurs Go possible. Réseau public interdit."
& $LlamaServerExe -hf "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M" --alias "arvor-coder-local" --jinja --reasoning off --ctx-size 8192 --n-gpu-layers 99 --host $HostIp --port $Port
if ($LASTEXITCODE -ne 0) { throw "llama-server interrompu avec code $LASTEXITCODE" }
