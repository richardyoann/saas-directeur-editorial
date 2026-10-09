"""Read-only diagnostics; never print credential files or raw command output."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.install_external_skills import check as external_check
from scripts.install_project_capabilities import installation_plan, validate


def probe(command):
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                              timeout=15, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def diagnose():
    checks = []

    def add(name, passed, action):
        checks.append({"name": name, "status": "passed" if passed else "blocked",
                       "next_action": None if passed else action})

    add("local_git", probe(["bash", "scripts/git_project.sh", "rev-parse", "--git-dir"]),
        "Vérifier le dépôt original ou .project-git ; ne pas remplacer un historique existant.")
    add("github_cli", bool(shutil.which("gh")), "Installer GitHub CLI dans WSL2.")
    online = probe(["gh", "api", "user", "--jq", ".login"])
    add("github_authenticated_api", online,
        "Vérifier le réseau et gh auth status depuis WSL2 ; un échec réseau ne prouve pas un jeton invalide.")
    if online:
        add("github_repository", probe(["gh", "repo", "view", "richardyoann/saas-directeur-editorial"]),
            "Vérifier les droits et l’existence du dépôt avant une création.")
        add("git_remote", probe(["bash", "scripts/git_project.sh", "ls-remote", "origin"]),
            "Vérifier le remote HTTPS et gh auth setup-git ; ne pas pousser avant examen de l’historique.")
    else:
        checks.append({"name": "github_repository_and_remote", "status": "unverified",
                       "next_action": "Relancer après rétablissement de l’accès GitHub."})
    compose = ["docker", "compose"]
    if not probe(compose + ["version"]):
        compose = ["docker-compose"]
    compose_ok = probe(compose + ["version"])
    add("docker_compose", compose_ok,
        "Activer l’intégration WSL de cette distribution dans Docker Desktop, ou installer Compose v2.")
    add("docker_daemon", probe(["docker", "info", "--format", "{{.ServerVersion}}"]),
        "Vérifier Docker Desktop et les droits sur le socket depuis WSL2 ; aucune modification de permissions automatique.")
    checks.append({"name": "services", "status": "unverified",
                   "next_action": "Exécuter docker compose ps depuis un terminal disposant de Compose et du socket ; vérifier chaque service."})
    try:
        package = validate(ROOT)
        planned, blockers = installation_plan(ROOT, package)
        add("internal_capabilities", True, "")
        add("native_activation", not planned and not blockers,
            "Exécuter .venv/bin/python scripts/install_project_capabilities.py --apply depuis WSL2, puis vérifier la découverte dans une nouvelle session.")
    except (ValueError, OSError):
        add("internal_capabilities", False, "Vérifier capabilities.lock.json et les sources locales.")
    try:
        external = external_check(ROOT)
        add("external_skills", external["status"] == "installed",
            "Exécuter install_external_skills.py --apply, --check et --activate depuis WSL2 connecté.")
    except (ValueError, OSError):
        add("external_skills", False, "Vérifier le registre et les reçus privés ; ne pas écraser les installations existantes.")
    return {"read_only": True, "checks": checks,
            "blocking_checks": sum(item["status"] == "blocked" for item in checks)}


if __name__ == "__main__":
    report = diagnose()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["blocking_checks"] else 0)
