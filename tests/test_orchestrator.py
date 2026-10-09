import subprocess
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflows.orchestrator import Orchestrator, WorkflowError


def concurrent_start(root):
    workflow = Orchestrator(Path(root), Path(root) / "shared-memory")
    try:
        workflow.start("DEV-CONCURRENT", "Une seule mission malgré plusieurs coordinateurs")
    except WorkflowError:
        pass


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.memory = self.root / "memory"
        self.workflow = Orchestrator(self.root, self.memory)
        self.workflow.start("DEV-TEST", "Développer la mémoire persistante")

    def test_resume_preserves_decisions_and_status(self):
        self.workflow.record("DEV-TEST", kind="decision", actor="analyst",
                             summary="Choisir JSONL pour la première étape", source="user")
        self.workflow.checkpoint("DEV-TEST", "analysis", "passed", "Périmètre confirmé")
        resumed = Orchestrator(self.root, self.memory)
        self.assertEqual(resumed.state("DEV-TEST")["stages"]["analysis"], "passed")
        self.assertIn("Choisir JSONL", resumed.context("DEV-TEST"))
        self.assertEqual(resumed.store.verify(), 3)

    def test_alternate_git_metadata_does_not_invalidate_evidence(self):
        (self.root / "app.py").write_text("value = 1\n")
        original = self.workflow.implementation_fingerprint()
        metadata = self.root / ".project-git"
        metadata.mkdir()
        (metadata / "config").write_text("private local configuration")
        (metadata / "HEAD").write_text("ref: refs/heads/main\n")
        self.assertEqual(self.workflow.implementation_fingerprint(), original)
        manifest_paths = {path.relative_to(self.root).as_posix()
                          for path in self.workflow._source_files()}
        self.assertFalse(any(path.startswith(".project-git/") for path in manifest_paths))
        (self.root / "app.py").write_text("value = 2\n")
        self.assertNotEqual(self.workflow.implementation_fingerprint(), original)

    def test_double_start_and_early_close_are_rejected(self):
        with self.assertRaises(WorkflowError):
            self.workflow.start("DEV-TEST", "Remplacer une mission")
        with self.assertRaises(WorkflowError):
            self.workflow.close("DEV-TEST", "Clôture prématurée")
        self.assertFalse(self.workflow.state("DEV-TEST")["closed"])

    def test_simulated_functional_evidence_is_rejected(self):
        self.workflow.record("DEV-TEST", kind="evidence", actor="tester", summary="Réponse simulée",
                             source="simulated", data={"gate": "functional_test", "outcome": "passed"})
        with self.assertRaises(WorkflowError):
            self.workflow.checkpoint("DEV-TEST", "functional_test", "passed", "Simulation réussie")
        self.assertEqual(self.workflow.state("DEV-TEST")["stages"]["functional_test"], "pending")

    @patch("workflows.orchestrator.subprocess.run")
    def test_check_failure_blocks_technical_gate(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 1, "", "Failure"),
                           subprocess.CompletedProcess([], 0, "OK", ""),
                           subprocess.CompletedProcess([], 0, "OK", "")]
        self.assertFalse(self.workflow.check("DEV-TEST"))
        self.assertEqual(self.workflow.state("DEV-TEST")["stages"]["technical_test"], "blocked")
        self.assertEqual(run.call_count, 3)
        with self.assertRaises(WorkflowError):
            self.workflow.checkpoint("DEV-TEST", "technical_test", "passed", "Ignorer échec")

    @patch("workflows.orchestrator.subprocess.run")
    def test_check_records_commands_and_results(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "Tool output", "")
        self.assertTrue(self.workflow.check("DEV-TEST"))
        events = self.workflow.store.read_events("DEV-TEST")
        actions = [event for event in events if event["kind"] == "action"]
        proofs = [event for event in events if event["kind"] == "evidence" and "command" in event["data"]]
        self.assertEqual(len(actions), 3)
        self.assertEqual(len(proofs), 3)
        self.assertEqual([event["data"]["command"] for event in actions],
                         [call.args[0] for call in run.call_args_list])
        self.assertTrue(all(event["data"]["exit_code"] == 0 for event in proofs))
        self.assertTrue(all(event["data"]["output"] == "Tool output" for event in proofs))
        self.assertEqual(self.workflow.state("DEV-TEST")["stages"]["technical_test"], "passed")

    @patch("workflows.orchestrator.subprocess.run", side_effect=subprocess.TimeoutExpired("tool", 60))
    def test_timeouts_are_recorded_as_blocked(self, run):
        self.assertFalse(self.workflow.check("DEV-TEST"))
        proofs = [event for event in self.workflow.store.read_events()
                  if "exit_code" in event["data"]]
        self.assertEqual([event["data"]["exit_code"] for event in proofs], [124, 124, 124])

    @patch("workflows.orchestrator.subprocess.run")
    def test_changed_code_invalidates_passed_evidence(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "OK", "")
        code = self.root / "main.py"
        code.write_text("value = 1\n")
        self.assertTrue(self.workflow.check("DEV-TEST"))
        self.workflow.record("DEV-TEST", kind="evidence", actor="user", source="user",
            summary="Parcours CLI testé réellement", data={"gate": "functional_test", "outcome": "passed",
                    "implementation_sha256": self.workflow.implementation_fingerprint()})
        self.workflow.checkpoint("DEV-TEST", "functional_test", "passed", "Preuve utilisateur")
        code.write_text("value = 2\n")
        for stage in ("technical_test", "functional_test"):
            with self.subTest(stage=stage), self.assertRaises(WorkflowError):
                self.workflow.checkpoint("DEV-TEST", stage, "passed", "Ancienne preuve")

    @patch("workflows.orchestrator.subprocess.run")
    def test_close_rechecks_manifest_and_code(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "OK", "")
        code = self.root / "main.py"
        code.write_text("value = 1\n")
        self.workflow.check("DEV-TEST")
        for stage in ("analysis", "development", "review", "documentation"):
            self.workflow.checkpoint("DEV-TEST", stage, "passed", "Étape vérifiée")
        self.workflow.checkpoint("DEV-TEST", "functional_test", "not_applicable", "Pas de parcours métier")
        manifest = self.workflow.manifest("DEV-TEST")
        self.workflow.checkpoint("DEV-TEST", "versioning", "passed", "Empreintes locales")
        original = manifest.read_bytes()
        manifest.write_bytes(original + b" ")
        with self.assertRaises(WorkflowError):
            self.workflow.close("DEV-TEST", "Ne doit pas clôturer")
        manifest.write_bytes(original)
        code.write_text("value = 2\n")
        with self.assertRaises(WorkflowError):
            self.workflow.close("DEV-TEST", "Code changé")
        code.write_text("value = 1\n")
        self.workflow.close("DEV-TEST", "Critères satisfaits")
        self.assertTrue(self.workflow.state("DEV-TEST")["closed"])

    def test_old_user_report_is_not_bound_to_current_code_implicitly(self):
        self.workflow.record("DEV-TEST", kind="evidence", actor="user", source="user",
            summary="Ancien compte rendu sans version confirmée",
            data={"gate": "functional_test", "outcome": "passed"})
        with self.assertRaises(WorkflowError):
            self.workflow.checkpoint("DEV-TEST", "functional_test", "passed", "Pas de version vérifiée")

    def test_concurrent_start_creates_only_one_mission(self):
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=concurrent_start, args=(str(self.root),)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail("Concurrent start timed out")
            self.assertEqual(process.exitcode, 0)
        resumed = Orchestrator(self.root, self.root / "shared-memory")
        self.assertEqual(len(resumed.store.read_events("DEV-CONCURRENT")), 1)

    def test_stores_are_isolated(self):
        isolated = Orchestrator(self.root, self.root / "other-memory")
        with self.assertRaises(WorkflowError):
            isolated.state("DEV-TEST")
        isolated.start("DEV-TEST", "Mission indépendante")
        self.assertEqual(isolated.store.verify(), 1)
        self.assertEqual(self.workflow.store.verify(), 1)


if __name__ == "__main__":
    unittest.main()
