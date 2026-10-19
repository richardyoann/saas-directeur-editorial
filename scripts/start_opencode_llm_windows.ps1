# Lance le LLM de developpement sur Windows et conserve ses diagnostics.
# Ne modifie pas le Qwen editorial ni sd.cpp (8082).
# Exemple: .\start_opencode_llm_windows.ps1 -LlamaServerExe "C:\IA\llama.cpp\llama-server.exe" -HostIp "172.31.48.1"
param(
  [string]$LlamaServerExe = "C:\IA\llama.cpp\llama-server.exe",
  [string]$HostIp = "",
  [int]$Port = 8083,
  [int]$GpuLayers = 99,
  [int]$Context = 8192
)
$ErrorActionPreference = "Stop"
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port non autorise" }
if ($GpuLayers -lt 0 -or $Context -lt 512) { throw "Parametres GPU/contexte invalides" }
if (-not (Test-Path -LiteralPath $LlamaServerExe -PathType Leaf)) {
  $binary = Get-Command $LlamaServerExe -ErrorAction SilentlyContinue
  if (-not $binary) { throw "llama-server.exe introuvable ; indiquer -LlamaServerExe." }
  $LlamaServerExe = $binary.Source
}
$LlamaServerExe = (Resolve-Path -LiteralPath $LlamaServerExe).Path
if (-not $HostIp) {
  $HostIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -like "*WSL*" -and $_.IPAddress -like "172.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
}
if (-not $HostIp) { throw "Adresse Windows WSL introuvable ; fournir -HostIp." }
$parsed = $null
if (-not [System.Net.IPAddress]::TryParse($HostIp, [ref]$parsed) -or
    -not ($HostIp -match '^(127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)')) {
  throw "Adresse d'ecoute privee requise."
}
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) { throw "Le port $Port est deja utilise." }
$logDir = Split-Path -Parent $LlamaServerExe
$stdout = Join-Path $logDir "arvor-coder-$Port.stdout.log"
$stderr = Join-Path $logDir "arvor-coder-$Port.stderr.log"
$argsList = @(
  "-hf", "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M",
  "--alias", "arvor-coder-local",
  "--jinja", "--reasoning", "off",
  "--ctx-size", "$Context", "--n-gpu-layers", "$GpuLayers",
  "--host", "$HostIp", "--port", "$Port"
)
Write-Host ("Lancement llama.cpp sur {0}:{1} (GPU layers: {2})" -f $HostIp, $Port, $GpuLayers)
Write-Host "Modele : Qwen3-4B-Instruct-2507 Q4_K_M"
Write-Host "Journaux : $stdout et $stderr"
# Start-Process evite que PowerShell interrompe au premier message stderr.
$process = Start-Process -FilePath $LlamaServerExe -ArgumentList $argsList -WorkingDirectory $logDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$process.Refresh()
Write-Host "PID : $($process.Id)"
if ($process.HasExited) {
  Write-Warning ("llama-server termine : code {0}" -f $process.ExitCode)
  Get-Content -LiteralPath $stderr -Tail 40 -ErrorAction SilentlyContinue
  throw "Le serveur n'a pas demarre ; lire le journal stderr."
}
Write-Host ("Verifier : curl.exe --noproxy * http://{0}:{1}/v1/models" -f $HostIp, $Port)
Write-Host ("En cas d'echec : Get-Content '{0}' -Tail 60" -f $stderr)
