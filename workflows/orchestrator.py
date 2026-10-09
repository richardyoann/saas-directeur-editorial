"""Development workflow checkpoints, evidence and source fingerprints.

This coordinates human/Codex agents; it does not execute generated model code.
"""
import hashlib
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from workflows.memory import MemoryStore

STAGES = (
    "analysis", "development", "technical_test", "functional_test",
    "review", "documentation", "versioning",
)
OUTCOMES = {"in_progress", "passed", "blocked", "not_applicable"}
ROLES = {
    "analysis": "analyst", "development": "developer",
    "technical_test": "technical_tester", "functional_test": "functional_tester",
    "review": "reviewer", "documentation": "documenter", "versioning": "versioner",
}


class WorkflowError(ValueError):
    pass


class Orchestrator:
    def __init__(self, repository: Path, memory: Path | None = None):
        self.repository = repository.resolve()
        self.store = MemoryStore(Path(memory).resolve() if memory else self.repository / "docs/memory")

    def _source_files(self):
        excluded = {".git", ".project-git", ".venv", ".agents", ".codex", ".aws", "__pycache__",
                    ".pytest_cache", "media", "models", "node_modules"}
        for directory, folders, names in os.walk(self.repository, followlinks=False):
            parent = Path(directory)
            relative_parent = parent.relative_to(self.repository)
            folders[:] = sorted(folder for folder in folders
                if folder not in excluded and not (parent / folder).is_symlink()
                and relative_parent / folder != Path("docs/memory")
                and (parent / folder).resolve() != self.store.root.resolve())
            for name in sorted(names):
                path = parent / name
                if ((name.startswith(".env") and name != ".env.example")
                    or path.suffix in {".log", ".bak", ".pyc"} or path.is_symlink()
                    or not path.is_file()):
                    continue
                yield path

    def implementation_fingerprint(self):
        files = []
        for path in self._source_files():
            relative = path.relative_to(self.repository)
            if relative.parts[0] in {"docs"} or (
                path.suffix == ".md" and relative.parts[0] != "skills"
            ):
                continue
            files.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    def _validate_gate(self, task_id, stage):
        evidence = [e for e in self._events(task_id)
                    if e["kind"] == "evidence" and e["data"].get("gate") == stage]
        if not evidence or evidence[-1]["data"].get("outcome") != "passed":
            raise WorkflowError("Une preuve réussie correspondant à cette étape est requise.")
        latest = evidence[-1]
        data = latest["data"]
        if stage == "functional_test" and latest["source"] == "simulated":
            raise WorkflowError("Un test simulé ne constitue pas une preuve fonctionnelle réelle.")
        if stage == "technical_test" and latest["source"] != "tool":
            raise WorkflowError("La preuve technique doit provenir des contrôles exécutés.")
        if stage in {"technical_test", "functional_test"} and (
            data.get("implementation_sha256") != self.implementation_fingerprint()
        ):
            raise WorkflowError("Le code a changé ou la preuve n’est pas liée à sa version ; relancer la validation.")
        if stage == "versioning":
            path = Path(data.get("manifest", ""))
            if not path.resolve().is_relative_to((self.store.root / "manifests").resolve()):
                raise WorkflowError("Manifeste hors du dossier attendu.")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != data.get("sha256"):
                raise WorkflowError("Manifeste absent ou altéré.")
            saved = json.loads(path.read_text(encoding="utf-8"))
            current = [{"path": p.relative_to(self.repository).as_posix(),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in self._source_files()]
            if saved["files"] != current:
                raise WorkflowError("Les sources ont changé depuis le manifeste ; en créer un nouveau.")

    def _events(self, task_id):
        events = self.store.read_events(task_id=task_id)
        if not any(e["kind"] == "status" and e["data"].get("action") == "task_started" for e in events):
            raise WorkflowError(f"Mission inconnue : {task_id}")
        return events

    def start(self, task_id, objective, actor="orchestrator"):
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,63}", task_id):
            raise WorkflowError("Identifiant attendu : DEV-002, OPS-MEMORY, etc.")
        if not objective.strip():
            raise WorkflowError("Objectif vide.")
        self.store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.store.root / "missions.lock",
                             os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+b") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.store.read_events(task_id=task_id):
                raise WorkflowError("Cet identifiant existe déjà ; reprendre la mission existante.")
            return self.store.append(task_id=task_id, kind="status", actor=actor,
                summary=objective, data={"action": "task_started", "status": "in_progress",
                                         "stages": list(STAGES)})

    def record(self, task_id, *, kind, actor, summary, data=None, source="agent", occurred_at=None):
        self._events(task_id)
        if kind == "status":
            raise WorkflowError("Utiliser checkpoint pour les changements de statut.")
        if data and data.get("action") in {"task_started", "task_closed", "checkpoint"}:
            raise WorkflowError("Action réservée à l’orchestrateur.")
        data = dict(data or {})
        if (kind == "evidence" and data.get("gate") == "functional_test"
            and data.get("outcome") == "passed" and source == "tool"):
            data.setdefault("implementation_sha256", self.implementation_fingerprint())
        return self.store.append(task_id=task_id, kind=kind, actor=actor,
            summary=summary, data=data, source=source, occurred_at=occurred_at)

    def state(self, task_id):
        events = self._events(task_id)
        stages = {stage: "pending" for stage in STAGES}
        closed = False
        for event in events:
            data = event["data"]
            if event["kind"] == "status" and data.get("action") == "checkpoint":
                stages[data["stage"]] = data["outcome"]
            if event["kind"] == "status" and data.get("action") == "task_closed":
                closed = True
        return {"task_id": task_id, "closed": closed, "stages": stages,
                "event_count": len(events), "implementation_sha256": self.implementation_fingerprint()}

    def checkpoint(self, task_id, stage, outcome, summary, source="agent"):
        if stage not in STAGES or outcome not in OUTCOMES:
            raise WorkflowError("Étape ou résultat invalide.")
        if not summary.strip():
            raise WorkflowError("Une justification est requise.")
        state = self.state(task_id)
        if state["closed"]:
            raise WorkflowError("Mission clôturée ; créer une nouvelle mission pour les changements.")
        if stage == "technical_test" and outcome == "not_applicable":
            raise WorkflowError("La validation technique est obligatoire.")
        if outcome == "not_applicable" and stage != "functional_test":
            raise WorkflowError("Seule une validation fonctionnelle hors périmètre peut être dispensée.")
        if outcome == "passed" and stage in {"technical_test", "functional_test", "versioning"}:
            self._validate_gate(task_id, stage)
        return self.store.append(task_id=task_id, kind="status", actor=ROLES[stage],
            summary=summary, source=source,
            data={"action": "checkpoint", "stage": stage, "outcome": outcome})

    def close(self, task_id, summary):
        state = self.state(task_id)
        if state["closed"]:
            raise WorkflowError("Mission déjà clôturée.")
        if any(value not in {"passed", "not_applicable"} for value in state["stages"].values()):
            raise WorkflowError("Toutes les étapes doivent être validées ou justifiées hors périmètre.")
        for stage in ("technical_test", "functional_test", "versioning"):
            if state["stages"][stage] == "passed":
                self._validate_gate(task_id, stage)
        return self.store.append(task_id=task_id, kind="status", actor="orchestrator",
            summary=summary, data={"action": "task_closed", "status": "complete"})

    def check(self, task_id):
        self._events(task_id)
        if self.state(task_id)["closed"]:
            raise WorkflowError("Mission clôturée.")
        commands = [
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            [sys.executable, "-m", "compileall", "-q", "apps/api", "workflows", "scripts", "tests"],
            [sys.executable, "scripts/install_project_capabilities.py", "--check"],
        ]
        fingerprint = self.implementation_fingerprint()
        results = []
        for command in commands:
            self.record(task_id, kind="action", actor="technical_tester",
                summary="Exécution d’un contrôle technique non destructif.",
                data={"command": command}, source="tool")
            try:
                process = subprocess.run(command, cwd=self.repository, capture_output=True,
                                         text=True, timeout=60, check=False)
                code, output = process.returncode, process.stdout + process.stderr
            except subprocess.TimeoutExpired:
                code, output = 124, "Contrôle interrompu après 60 secondes."
            except OSError as exc:
                code, output = 127, f"Exécution impossible : {type(exc).__name__}"
            success = code == 0
            results.append(success)
            self.record(task_id, kind="evidence", actor="technical_tester",
                summary="Résultat du contrôle technique.", source="tool",
                data={"command": command, "exit_code": code, "output": output,
                      "outcome": "passed" if success else "blocked", "scope": "automated"})
        passed = all(results) and fingerprint == self.implementation_fingerprint()
        self.record(task_id, kind="evidence", actor="technical_tester", source="tool",
            summary="Synthèse des contrôles techniques.",
            data={"gate": "technical_test", "outcome": "passed" if passed else "blocked",
                  "commands_passed": sum(results), "commands_total": len(results),
                  "implementation_sha256": fingerprint})
        self.checkpoint(task_id, "technical_test", "passed" if passed else "blocked",
                        "Contrôles techniques réussis." if passed else "Contrôles techniques en échec.", "tool")
        return passed

    def manifest(self, task_id):
        self._events(task_id)
        if self.state(task_id)["closed"]:
            raise WorkflowError("Mission clôturée.")
        files = [{"path": path.relative_to(self.repository).as_posix(),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in self._source_files()]
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repository,
                             capture_output=True, text=True, check=False, timeout=10)
        snapshot = {"schema_version": 1, "task_id": task_id,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": files,
                    "git_head": git.stdout.strip() if git.returncode == 0 else None,
                    "git_available": git.returncode == 0,
                    "note": "Empreintes locales ; aucun commit créé. Mémoire mutable exclue."}
        directory = self.store.root / "manifests"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = directory / f"{task_id}-{stamp}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.record(task_id, kind="evidence", actor="versioner", source="tool",
            summary="Manifeste local des sources créé ; aucun commit Git.",
            data={"gate": "versioning", "outcome": "passed", "manifest": str(path),
                  "sha256": digest, "files": len(files), "git_available": snapshot["git_available"]})
        return path

    def context(self, task_id=None):
        events = self.store.read_events(task_id=task_id)
        lines = ["# Contexte de reprise", "", "Source : journal local vérifié ; extraits utiles, pas transcript intégral.", ""]
        tasks = dict.fromkeys(e["task_id"] for e in events)
        for task in tasks:
            try:
                state = self.state(task)
            except WorkflowError:
                continue
            lines += [f"## {task}", "", f"Clôturé : {state['closed']}",
                      "Étapes : " + ", ".join(f"{s}={v}" for s, v in state["stages"].items()), ""]
            task_events = [e for e in events if e["task_id"] == task]
            relevant = [e for e in task_events if e["kind"] in {"interaction", "decision", "handoff"}]
            relevant += [e for e in task_events if e["kind"] == "status"][-2:]
            for event in relevant:
                summary = event["summary"].replace("\n", " ")
                lines.append(f"- {event['recorded_at']} [{event['source']}/{event['actor']}] {summary}")
            lines.append("")
        lines += ["Consulter ETAT_PROJET.md, ORCHESTRATION.md et les preuves complètes du journal.",
                  "Ne pas afficher .env ; confirmer avant migration appliquée, infrastructure ou suppression.", ""]
        return "\n".join(lines)
