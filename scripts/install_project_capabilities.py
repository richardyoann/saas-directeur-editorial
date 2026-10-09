"""Validate repository capabilities and safely activate native Codex discovery.

Canonical sources remain in skills/ and agents/. No configuration is replaced.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = "capabilities.lock.json"


def confined_source(root, path):
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Source hors dépôt : {path}")
    candidate = path
    while candidate != root:
        if candidate.is_symlink():
            raise ValueError(f"Lien interdit dans les sources : {candidate}")
        candidate = candidate.parent


def package_files(root):
    for directory in (root / "skills", root / "agents"):
        confined_source(root, directory)
    paths = sorted((root / "skills").rglob("*")) + sorted((root / "agents").glob("*.toml"))
    for path in paths:
        confined_source(root, path)
    return [path for path in paths if path.is_file()]


def inventory(root):
    skills, agents = [], []
    checked_files = package_files(root)
    for directory in sorted((root / "skills").iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Les sources des skills doivent être des dossiers locaux.")
        text = (directory / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
        if not frontmatter:
            raise ValueError(f"Frontmatter absent : {directory.name}")
        header = frontmatter[1]
        name = re.search(r"^name:\s*([^\n]+)$", header, re.M)
        description = re.search(r"^description:\s*([^\n]+)$", header, re.M)
        version = re.search(r'^\s+version:\s*[\"\']?(\d+\.\d+\.\d+)[\"\']?\s*$', header, re.M)
        if not name or name[1].strip() != directory.name or not description or not version:
            raise ValueError(f"Nom, description ou version invalide : {directory.name}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", directory.name):
            raise ValueError("Nom de skill invalide.")
        if "TODO" in text or "[INSERT" in text:
            raise ValueError(f"Scaffold inachevé : {directory.name}")
        skills.append({"name": directory.name, "version": version[1]})
    for path in sorted((root / "agents").glob("*.toml")):
        agent = tomllib.loads(path.read_text(encoding="utf-8"))
        if any(not isinstance(agent.get(key), str) or not agent[key].strip()
               for key in ("name", "description", "developer_instructions")):
            raise ValueError(f"Définition agent invalide : {path.name}")
        if agent["name"] != path.stem:
            raise ValueError(f"Le nom doit correspondre au fichier : {path.name}")
        agents.append({"name": agent["name"], "path": path.relative_to(root).as_posix()})
    if not skills or not agents:
        raise ValueError("Package vide.")
    files = []
    for path in checked_files:
        if path.is_symlink():
            raise ValueError("Les sources versionnées ne doivent pas être des liens.")
        files.append({"path": path.relative_to(root).as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema_version": 1, "package_version": "1.0.0", "skills": skills,
            "agents": agents, "files": files}


def validate(root):
    actual = inventory(root)
    locked = json.loads((root / LOCK).read_text(encoding="utf-8"))
    if locked != actual:
        raise ValueError("Le package diffère du lock ; revoir et versionner la modification.")
    return actual


def targets(root, package):
    result = [(root / "skills" / item["name"], root / ".agents/skills" / item["name"])
              for item in package["skills"]]
    result += [(root / item["path"], root / ".codex/agents" / f"{item['name']}.toml")
               for item in package["agents"]]
    return result


def installation_plan(root, package):
    planned, blockers = [], []
    for source, destination in targets(root, package):
        try:
            confined_source(root, source)
        except ValueError as exc:
            blockers.append(str(exc))
            continue
        # Only source-relative links in this repository; never follow a parent outside it.
        if not destination.parent.resolve().is_relative_to(root.resolve()):
            blockers.append(f"Destination hors dépôt : {destination}")
            continue
        if destination.is_symlink() and destination.resolve() == source.resolve():
            continue
        if destination.exists() or destination.is_symlink():
            blockers.append(f"Destination existante préservée : {destination.relative_to(root)}")
            continue
        parent = destination.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            blockers.append(f"Dossier en lecture seule : {parent.relative_to(root)}")
            continue
        planned.append((source, destination))
    return planned, sorted(set(blockers))


def activate(root, package):
    planned, blockers = installation_plan(root, package)
    if blockers:
        return {"activated": False, "created": [], "blockers": blockers}
    created = []
    for source, destination in planned:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.path.relpath(source, destination.parent),
                                   target_is_directory=source.is_dir())
            created.append(destination.relative_to(root).as_posix())
        except OSError as exc:
            return {"activated": False, "partial": bool(created), "created": created,
                    "blockers": [f"Activation interrompue : {type(exc).__name__}" ]}
    return {"activated": True, "created": created, "blockers": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Valider les sources et empreintes sans activer.")
    modes.add_argument("--apply", action="store_true", help="Ajouter les liens natifs ; aucun fichier remplacé.")
    modes.add_argument("--lock", action="store_true", help="Créer le lock initial ; refuse d’écraser un lock existant.")
    args = parser.parse_args(argv)
    try:
        if args.lock:
            content = json.dumps(inventory(ROOT), ensure_ascii=False, indent=2) + "\n"
            with (ROOT / LOCK).open("x", encoding="utf-8") as handle:
                handle.write(content)
            print("Lock initial créé.")
            return 0
        package = validate(ROOT)
        if args.apply:
            report = activate(ROOT, package)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["activated"] else 2
        planned, blockers = installation_plan(ROOT, package)
        print(json.dumps({"validated": True, "skills": len(package["skills"]),
                          "agents": len(package["agents"]), "native_links_to_create": len(planned),
                          "native_blockers": blockers}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Validation/activation impossible : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
