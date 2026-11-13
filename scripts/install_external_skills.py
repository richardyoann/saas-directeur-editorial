"""Plan or install pinned external skills through the official installer only.

Planning/checking never uses network. Third-party scripts, hooks and skills are
never executed. Native activation is separate from this installation command.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REGISTRY = "external-skills.json"
RECEIPTS = Path("docs/memory/external-installs")
SAFE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def safe_path(value, allow_root=False):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Unsafe source path")
    if allow_root and value == ".":
        return
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("Unsafe source path")


def registry(root):
    package = json.loads((root / REGISTRY).read_text())
    if package.get("schema_version") != 1 or not package.get("sources"):
        raise ValueError("Invalid external registry")
    namespaces = set()
    for source in package["sources"]:
        name = source.get("namespace", "")
        if not SAFE_NAME.fullmatch(name) or name in namespaces:
            raise ValueError("Invalid or duplicate namespace")
        namespaces.add(name)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source.get("repo", "")):
            raise ValueError("Invalid GitHub repository")
        ref = source.get("ref", "")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", ref) or ".." in ref:
            raise ValueError("Unsafe ref")
        if not source.get("selectors"):
            raise ValueError("Empty selectors")
        for selector in source["selectors"]:
            if "name" in selector and not SAFE_NAME.fullmatch(selector["name"]):
                raise ValueError("Invalid skill name")
            if "path" in selector:
                safe_path(selector["path"], allow_root=True)
            if "glob" in selector:
                safe_path(selector["glob"])
            if not any(key in selector for key in ("name", "path", "glob")):
                raise ValueError("Empty selector")
    return package


def fetch_json(url):
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "editorial-skills-installer"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def resolve(source):
    base = "https://api.github.com/repos/" + source["repo"]
    commit = fetch_json(base + "/commits/" + quote(source["ref"], safe=""))
    sha = commit.get("sha", "")
    if not SHA.fullmatch(sha):
        raise ValueError("GitHub returned invalid commit SHA")
    tree = fetch_json(base + "/git/trees/" + sha + "?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Incomplete GitHub tree; refusing partial installation")
    files = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
    return sha, select_skills(source, files)


def select_skills(source, files):
    skill_files = []
    for value in files:
        safe_path(value)
        if PurePosixPath(value).name == "SKILL.md":
            skill_files.append(value)
    selected = {}
    for selector in source["selectors"]:
        if "path" in selector:
            path = selector["path"]
            expected = "SKILL.md" if path == "." else path + "/SKILL.md"
            matches = [item for item in skill_files if item == expected]
        elif "glob" in selector:
            # pathlib matching treats '*' as one path segment; fnmatch alone does not.
            pattern = selector["glob"].split("/")
            matches = [item for item in skill_files if len(item.split("/")) == len(pattern)
                       and all(fnmatch.fnmatchcase(part, wanted)
                               for part, wanted in zip(item.split("/"), pattern, strict=True))]
        else:
            matches = [item for item in skill_files if PurePosixPath(item).parent.name == selector["name"]]
        if not matches or ("glob" not in selector and len(matches) != 1):
            raise ValueError("Missing or ambiguous skill selector: " + json.dumps(selector))
        for item in matches:
            path = str(PurePosixPath(item).parent)
            name = selector.get("name", PurePosixPath(item).parent.name)
            if not SAFE_NAME.fullmatch(name):
                raise ValueError("Unsafe discovered skill name")
            if name in selected and selected[name]["path"] != path:
                raise ValueError("Duplicate discovered skill name")
            selected[name] = {"name": name, "path": path}
    return sorted(selected.values(), key=lambda item: item["name"])


def confined(root, path):
    root = root.resolve()
    path = path.absolute()
    if not path.absolute().is_relative_to(root):
        raise ValueError("Destination outside repository")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Destination symlink refused")
        current = current.parent
    if not path.resolve().is_relative_to(root):
        raise ValueError("Destination escapes repository")


def digests(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Invalid installed directory")
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Installed symlinks refused")
        if path.is_file():
            result.append({"path": path.relative_to(directory).as_posix(),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not (directory / "SKILL.md").is_file():
        raise ValueError("Installed SKILL.md missing")
    return result


def load_receipts(root):
    directory = root / RECEIPTS
    confined(root, directory)
    receipts = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise ValueError("Receipt symlink refused")
        receipt = json.loads(path.read_text())
        if receipt.get("schema_version") != 1:
            raise ValueError("Invalid receipt schema")
        safe_path(receipt["destination"])
        receipts.append(receipt)
    return receipts


def write_receipt(root, result):
    directory = root / RECEIPTS
    confined(root, directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {"schema_version": 1, "recorded_at": datetime.now(timezone.utc).isoformat(), **result}
    path = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(uuid.uuid4()) + ".json")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Integrate only with an already-created project task. Never fabricate it.
    from workflows.memory import MemoryStore
    memory = root / "docs/memory"
    if (memory / "events.jsonl").is_file():
        store = MemoryStore(memory)
        if any(event["data"].get("action") == "task_started" for event in store.read_events("DEV-002")):
            store.append(task_id="DEV-002", kind="evidence", actor="skill-installer", source="tool",
                         summary="Résultat installation externe : " + result["status"], data=result)
    return result


def check(root):
    package = registry(root)
    receipts = load_receipts(root)
    latest = {receipt["destination"]: receipt for receipt in receipts}
    installed = []
    for destination, receipt in latest.items():
        if receipt["status"] not in {"installed", "skipped"}:
            continue
        path = root / destination
        confined(root, path)
        if digests(path) != receipt.get("files"):
            raise ValueError("Installed skill differs from receipt: " + destination)
        installed.append(destination)
    completed_sources = 0
    for source in package["sources"]:
        members = [receipt for destination, receipt in latest.items()
                   if destination in installed and receipt["repo"] == source["repo"]
                   and destination.startswith("vendor/skills/" + source["namespace"] + "/")]
        names = {receipt["name"] for receipt in members}
        expected = set().union(*(set(receipt.get("expected_skills", [])) for receipt in members))
        selectors_complete = all((selector["name"] in names if "name" in selector else bool(expected))
                                 for selector in source["selectors"])
        same_ref = len({receipt.get("ref") for receipt in members}) == 1
        if selectors_complete and same_ref and expected.issubset(names):
            completed_sources += 1
    status = "pending" if not installed else "installed" if completed_sources == len(package["sources"]) else "partial"
    return {"validated": True, "status": status,
            "installed": installed, "sources_planned": len(package["sources"]),
            "sources_completed": completed_sources,
            "receipts": len(receipts), "network_used": False}


def apply(root, installer):
    package = registry(root)
    if not installer.is_file() or installer.is_symlink():
        raise ValueError("Official installer missing or symlink; specify --installer")
    receipts = load_receipts(root)
    latest = {item["destination"]: item for item in receipts if item["status"] in {"installed", "skipped"}}
    results = []
    for source in package["sources"]:
        namespace = root / "vendor/skills" / source["namespace"]
        confined(root, namespace)
        try:
            sha, skills = resolve(source)
        except (ValueError, OSError) as error:
            results.append(write_receipt(root, {"repo": source["repo"], "requested_ref": source["ref"],
                "name": None, "destination": namespace.relative_to(root).as_posix(),
                "status": "blocked", "scope": "source_resolution",
                "selection_note": source.get("note", "Explicitly requested collection"),
                "reason": "Source resolution failed: " + type(error).__name__}))
            continue
        for skill in skills:
            destination = namespace / skill["name"]
            confined(root, destination)
            relative = destination.relative_to(root).as_posix()
            result = {"repo": source["repo"], "ref": sha, "source_path": skill["path"],
                      "name": skill["name"], "destination": relative,
                      "expected_skills": [item["name"] for item in skills],
                      "selection_note": source.get("note", "Explicitly requested skill collection")}
            if destination.exists():
                old = latest.get(relative)
                if (old and old["repo"] == source["repo"] and old["ref"] == sha
                        and old["source_path"] == skill["path"] and old["files"] == digests(destination)):
                    result.update(status="skipped", files=old["files"])
                else:
                    result.update(status="conflict", reason="Existing destination preserved; no matching receipt")
            else:
                namespace.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, str(installer), "--repo", source["repo"], "--path", skill["path"],
                           "--name", skill["name"], "--ref", sha, "--method", "download", "--dest", str(namespace)]
                try:
                    process = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
                    if process.returncode:
                        result.update(status="blocked", exit_code=process.returncode,
                                      reason="Official installer failed; any partial destination preserved for review")
                    else:
                        result.update(status="installed", files=digests(destination))
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    result.update(status="blocked", reason="Installer failed: " + type(error).__name__)
            results.append(write_receipt(root, result))
    return results


def activate(root):
    report = check(root)
    if report["status"] != "installed":
        return {"activated": False, "created": [],
                "blockers": ["La sélection externe complète n’est pas installée et vérifiée."]}
    planned, blockers, names = [], [], set()
    for relative in report["installed"]:
        source = root / relative
        confined(root, source)
        text = (source / "SKILL.md").read_text(encoding="utf-8")
        header = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
        match = re.search(r"^name:\s*([^\n]+)$", header[1], re.M) if header else None
        name = match[1].strip().strip("\"'") if match else ""
        if not SAFE_NAME.fullmatch(name) or name in names:
            blockers.append("Nom de skill absent, invalide ou en doublon : " + relative)
            continue
        names.add(name)
        destination = root / ".agents/skills" / name
        try:
            confined(root, destination.parent)
        except ValueError as exc:
            blockers.append(str(exc))
            continue
        if destination.is_symlink() and destination.resolve() == source.resolve():
            continue
        if destination.exists() or destination.is_symlink():
            blockers.append("Destination existante préservée : " + str(destination.relative_to(root)))
            continue
        parent = destination.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            blockers.append("Dossier en lecture seule : " + str(parent.relative_to(root)))
            continue
        planned.append((source, destination))
    if blockers:
        return {"activated": False, "created": [], "blockers": sorted(set(blockers))}
    created = []
    for source, destination in planned:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(os.path.relpath(source, destination.parent), target_is_directory=True)
            created.append(destination.relative_to(root).as_posix())
        except OSError as exc:
            return {"activated": False, "partial": bool(created), "created": created,
                    "blockers": ["Activation interrompue : " + type(exc).__name__]}
    return {"activated": True, "created": created, "blockers": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--activate", action="store_true", help="Activer uniquement la sélection complète vérifiée, sans écrasement.")
    parser.add_argument("--installer", type=Path,
                        default=Path.home() / ".codex/skills/.system/skill-installer/scripts/install-skill-from-github.py")
    args = parser.parse_args(argv)
    try:
        if args.apply:
            results = apply(ROOT, args.installer)
            report = {"results": results, "native_activation": "not_applied"}
            code = 0 if all(item["status"] in {"installed", "skipped"} for item in results) else 2
        elif args.activate:
            report = activate(ROOT)
            code = 0 if report["activated"] else 2
        elif args.check:
            report, code = check(ROOT), 0
        else:
            report = {"status": "pending", "network_used": False, "writes": False,
                      "destination": "vendor/skills/<namespace>/<skill>", **registry(ROOT)}
            code = 0
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("External skills blocked: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Allow this repository script to import its own memory module, not vendor code.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
