"""Exercise the real workflow CLI across processes in an isolated temporary journal.

No model request, native activation, Git mutation or database change is performed.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="editorial-workflow-") as directory:
        memory = Path(directory)
        base = [sys.executable, str(ROOT / "scripts/project.py"), "--memory-dir", str(memory)]
        commands = [
            ["start", "DEV-SMOKE", "--objective", "Vérifier le parcours CLI réel sans modifier le journal du projet"],
            ["record", "DEV-SMOKE", "--kind", "decision", "--summary", "Mémoire isolée de validation"],
            ["status", "DEV-SMOKE", "--stage", "analysis", "--outcome", "passed", "--summary", "Parcours CLI borné"],
            ["status", "DEV-SMOKE", "--stage", "development", "--outcome", "passed", "--summary", "Outils présents"],
            ["check", "DEV-SMOKE"],
            ["record", "DEV-SMOKE", "--kind", "evidence", "--source", "tool",
             "--summary", "Les commandes CLI réelles précédentes ont réussi",
             "--data-json", '{"gate":"functional_test","outcome":"passed","scope":"functional_cli"}'],
            ["status", "DEV-SMOKE", "--stage", "functional_test", "--outcome", "passed", "--summary", "Parcours réel de la CLI"],
            ["status", "DEV-SMOKE", "--stage", "review", "--outcome", "passed", "--summary", "Journal isolé, clôture contrôlée"],
            ["status", "DEV-SMOKE", "--stage", "documentation", "--outcome", "passed", "--summary", "Parcours reproductible documenté dans le script"],
            ["manifest", "DEV-SMOKE"],
            ["status", "DEV-SMOKE", "--stage", "versioning", "--outcome", "passed", "--summary", "Manifeste local, aucun commit"],
            ["close", "DEV-SMOKE", "--summary", "Parcours CLI validé dans le journal temporaire"],
            ["context", "--write-current"],
            ["verify"],
            ["status", "DEV-SMOKE"],
        ]
        for arguments in commands:
            process = subprocess.run(base + arguments, cwd=ROOT, capture_output=True,
                                     text=True, check=False, timeout=60)
            if process.returncode:
                print(json.dumps({"failed_command": arguments, "exit_code": process.returncode,
                                  "output": process.stdout + process.stderr}, ensure_ascii=False))
                return 1
        state = json.loads(process.stdout)
        if not state["closed"] or not (memory / "CURRENT.md").is_file():
            print("Échec : clôture ou reprise non persistée.")
            return 1
        print(json.dumps({"scope": "functional_cli", "commands_passed": len(commands),
                          "journal_isolated": True, "closed": state["closed"],
                          "events": state["event_count"], "real_qwen_call": False},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
