#!/usr/bin/env bash
# Installer OpenCode V2 pour Arvor dans WSL, sans modifier le SaaS.
set -euo pipefail
# Une commande exécutée dans bash ne peut pas changer le PATH du shell parent.
# Retrouver le binaire des installations précédentes avant de télécharger.
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$HOME/bin:$PATH"
REPO="${ARVOR_REPO:-$HOME/saas-directeur-editorial-github}"
PORT="${ARVOR_OPENCODE_PORT:-8083}"
HOST_IP="${ARVOR_WINDOWS_HOST_IP:-$(ip -4 route show default | awk '{print $3; exit}')}"
URL="${ARVOR_OPENCODE_URL:-http://$HOST_IP:$PORT/v1}"
command -v curl >/dev/null || { echo 'Installer curl au préalable'; exit 1; }
command -v python3 >/dev/null || { echo 'Python3 introuvable'; exit 1; }
if ! command -v opencode >/dev/null 2>&1; then
  echo 'Installation CLI OpenCode V2 depuis le script officiel (à auditer avant exécution).'
  installer="$(mktemp)"
  trap 'rm -f "$installer"' EXIT
  curl --proto '=https' --tlsv1.2 -fsSL https://opencode.ai/v2/install -o "$installer"
  bash "$installer"
fi
command -v opencode >/dev/null || { echo 'Binaire installé non détecté, vérifier PATH'; exit 1; }
version="$(opencode --version)"
echo "$version"
if [[ ! "$version" =~ 2\.[0-9]+ ]]; then
  echo "OpenCode V2 requis. Installer ou mettre à niveau la version 2." >&2
  exit 1
fi
echo "Modèle local attendu: Qwen3-4B-Instruct-2507 sur Windows, à $URL"
if ! python3 - "$URL" <<'PY'
import ipaddress, json, sys, urllib.request
# L'URL WSL privée ne doit pas passer par les proxies HTTP_PROXY/HTTPS_PROXY.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
from urllib.parse import urlsplit
url = sys.argv[1].rstrip('/')
parts = urlsplit(url)
try:
    address = ipaddress.ip_address(parts.hostname)
    assert parts.scheme == 'http' and (address.is_private or address.is_loopback)
except (ValueError, AssertionError, TypeError):
    sys.exit('Refus: URL de modèle hors réseau privé')
try:
    with opener.open(url + '/models', timeout=8) as reply:
        models = json.load(reply)['data']
    if not any(m.get('id') == 'arvor-coder-local' for m in models):
        raise RuntimeError('Le serveur ne publie pas arvor-coder-local')
    payload = {
      'model': 'arvor-coder-local',
      'messages': [{'role':'user','content':"Utilise le calculateur pour 2+2. N'écris pas la réponse toi-même."}],
      'tools': [{'type':'function','function': {'name':'calculateur','description':'Calcul','parameters': {'type':'object','properties':{'expression':{'type':'string'}},'required':['expression']}}}],
      'tool_choice': 'required', 'temperature': 0, 'max_tokens': 160
    }
    req = urllib.request.Request(url + '/chat/completions', json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    with opener.open(req, timeout=90) as reply:
        output = json.load(reply)
    calls = output['choices'][0]['message'].get('tool_calls', [])
    if not calls or calls[0].get('function',{}).get('name') != 'calculateur':
        raise RuntimeError('Tool calling non fonctionnel')
except Exception as err:
    print('Serveur absent ou tool calling KO:', type(err).__name__, str(err)[:120], file=sys.stderr)
    sys.exit(2)
print('API et appel outil: OK')
PY
then
  echo "OpenCode installé, mais modèle non configuré. Démarrer d'abord scripts/start_opencode_llm_windows.ps1 sur Windows."
  echo "Dans ce terminal : export PATH=\"$HOME/.opencode/bin:\$PATH\" (ou source ~/.bashrc)."
  echo "OpenCode peut déjà démarrer en mode cloud gratuit : opencode, puis /models."
  echo "Puis relancer ce script pour configurer le modèle local si souhaité."
  exit 0
fi
configdir="$HOME/.config/opencode"
mkdir -p "$configdir"
if [ -e "$configdir/opencode.json" ] || [ -e "$configdir/opencode.jsonc" ]; then
  target="$configdir/arvor-local.example.json"
  if [ -e "$target" ]; then
    echo "Exemple déjà présent : $target (non écrasé)."
    echo "Fusionner manuellement puis lancer OpenCode."
    exit 0
  fi
  echo 'Configuration globale existante conservée. Exemple généré sans écrasement.'
else
  target="$configdir/opencode.json"
fi
python3 - "$URL" "$target" <<'PY'
import json, os, sys
url, target = sys.argv[1:]
config = {
 '$schema':'https://opencode.ai/config.json',
 'model':'arvorlocal/coder',
 'providers': {
  'arvorlocal': {
   'name':'Qwen local PC (Windows llama.cpp)',
   'package':'@opencode/ai/providers/openai-compatible',
   'settings': {'baseURL':url},
   'models': {'coder': {
     'modelID':'arvor-coder-local',
     'name':'Qwen3-4B-Instruct-2507 Q4_K_M',
     'capabilities': {'tools':True,'input':['text'],'output':['text']},
     'limit': {'context':8192, 'output':2048}
   }}
  }
 }
}
with open(target, 'x', encoding='utf-8') as f:
    json.dump(config, f, indent=2)
os.chmod(target,0o600)
PY
echo "Configuration créée: $target"
echo "Lancer: cd '$REPO' && opencode"
echo "Si fichier .example.json, fusionner manuellement avec votre configuration globale OpenCode."
