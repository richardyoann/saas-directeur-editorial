"""Traceable development workflow CLI; run from any working directory."""
import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from workflows.orchestrator import Orchestrator, WorkflowError
from workflows.memory import MemoryIntegrityError


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--memory-dir", type=Path, help="Journal alternatif, notamment pour les tests.")
    sub = p.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Créer une mission et son objectif.")
    start.add_argument("task_id")
    start.add_argument("--objective", required=True)
    record = sub.add_parser("record", help="Consigner une action, décision, interaction ou preuve.")
    record.add_argument("task_id")
    record.add_argument("--kind", choices=["interaction", "action", "decision", "evidence", "handoff"], required=True)
    record.add_argument("--actor", default="orchestrator")
    record.add_argument("--summary", required=True)
    record.add_argument("--source", choices=["agent", "user", "tool", "simulated"], default="agent")
    record.add_argument("--occurred-at", help="Date ISO avec fuseau de la preuve d’origine.")
    record.add_argument("--data-json", default="{}", help="Objet JSON sans secrets.")
    status = sub.add_parser("status", help="Lire les étapes ou consigner un checkpoint.")
    status.add_argument("task_id")
    status.add_argument("--stage")
    status.add_argument("--outcome")
    status.add_argument("--summary")
    status.add_argument("--source", choices=["agent", "user", "tool", "simulated"], default="agent")
    for name in ("check", "manifest", "close"):
        item = sub.add_parser(name)
        item.add_argument("task_id")
        if name == "close":
            item.add_argument("--summary", required=True)
    context = sub.add_parser("context", help="Relire la mémoire pour reprendre une session.")
    context.add_argument("--task")
    context.add_argument("--write-current", action="store_true", help="Actualiser la synthèse de reprise.")
    sub.add_parser("verify", help="Vérifier l’intégrité du journal sans le réparer.")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    orchestrator = Orchestrator(REPOSITORY, args.memory_dir)
    try:
        match args.command:
            case "start":
                result = orchestrator.start(args.task_id, args.objective)
            case "record":
                data = json.loads(args.data_json)
                if not isinstance(data, dict):
                    raise WorkflowError("--data-json doit être un objet JSON.")
                result = orchestrator.record(args.task_id, kind=args.kind, actor=args.actor,
                    summary=args.summary, data=data, source=args.source, occurred_at=args.occurred_at)
            case "status":
                if args.stage:
                    if not args.outcome or not args.summary:
                        p.error("--stage exige --outcome et --summary")
                    result = orchestrator.checkpoint(args.task_id, args.stage, args.outcome,
                                                     args.summary, args.source)
                else:
                    if args.outcome or args.summary:
                        p.error("--outcome et --summary exigent --stage")
                    result = orchestrator.state(args.task_id)
            case "check":
                passed = orchestrator.check(args.task_id)
                print("Contrôles réussis." if passed else "Contrôles bloqués ; consulter le journal.")
                return 0 if passed else 1
            case "manifest":
                result = {"manifest": str(orchestrator.manifest(args.task_id))}
            case "close":
                result = orchestrator.close(args.task_id, args.summary)
            case "context":
                result = orchestrator.context(args.task)
                if args.write_current:
                    target = orchestrator.store.root / "CURRENT.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        os.fchmod(stream.fileno(), 0o600)
                        stream.write(result)
                print(result)
                return 0
            case "verify":
                result = {"events_verified": orchestrator.store.verify()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkflowError, MemoryIntegrityError, ValueError, OSError) as exc:
        print(f"Erreur : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
