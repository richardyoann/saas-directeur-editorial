import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from workflows.memory import MemoryIntegrityError, MemoryStore


def write_events(root, actor):
    store = MemoryStore(Path(root))
    for index in range(15):
        store.append(task_id="DEV-002", kind="action", actor=actor, summary=f"Action {index}")


class MemoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = MemoryStore(self.root)

    def append(self, **changes):
        fields = dict(task_id="DEV-002", kind="decision", actor="orchestrator", summary="Decision")
        fields.update(changes)
        return self.store.append(**fields)

    def test_persistence_and_filtering(self):
        first = self.append(occurred_at="2026-10-09T01:19:00+02:00", source="user")
        second = self.append(task_id="DEV-003")
        other = MemoryStore(self.root)
        self.assertEqual(other.verify(), 2)
        self.assertEqual(other.read_events("DEV-002"), [first])
        self.assertEqual(second["prev_hash"], first["hash"])
        self.assertEqual(first["source"], "user")
        self.assertEqual(first["occurred_at"], "2026-10-09T01:19:00+02:00")

    def test_tampering_blocks_reads_and_append_without_repair(self):
        self.append()
        raw = self.store.path.read_bytes().replace(b"Decision", b"Changed!")
        self.store.path.write_bytes(raw)
        for operation in (self.store.verify, self.store.read_events, self.append):
            with self.assertRaises(MemoryIntegrityError):
                operation()
        self.assertEqual(self.store.path.read_bytes(), raw)

    def test_incomplete_tail_blocks_append(self):
        self.append()
        with self.store.path.open("ab") as handle:
            handle.write(b'{"partial":')
        original = self.store.path.read_bytes()
        with self.assertRaises(MemoryIntegrityError):
            self.append()
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_concurrent_processes_keep_chain(self):
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=write_events, args=(str(self.root), f"agent-{index}"))
                     for index in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail("Concurrent writer timed out")
            self.assertEqual(process.exitcode, 0)
        events = self.store.read_events()
        self.assertEqual(len(events), 60)
        self.assertEqual(len({event["id"] for event in events}), 60)

    def test_redaction_preserves_usage(self):
        event = self.append(
            summary="Bearer abc-private https://user:my-password@example.com TOKEN=hidden",
            data={"password": "private", "nested": [{"api_key": "key-private"}],
                  "access_token": "token-private", "credentials": {"user": "private"},
                  "usage": {"prompt_tokens": 47, "completion_tokens": 150, "total_tokens": 197},
                  "text": "API_KEY='quoted private' max_tokens=150"})
        text = json.dumps(event)
        for secret in ("abc-private", "my-password", "hidden", "quoted private", "key-private", "token-private"):
            self.assertNotIn(secret, text)
        self.assertEqual(event["data"]["usage"]["total_tokens"], 197)
        self.assertIn("max_tokens=150", event["data"]["text"])
        self.assertEqual(self.store.verify(), 1)

    def test_labelled_secrets_in_json_and_query_strings(self):
        event = self.append(data={"output": 'Response: {"access_token":"query-private",'
                                 '"authorization":"Basic base64-private",'
                                 '"token_count":"197"}\n'
                                 'https://example.test/?access_token=url-private&limit=2'})
        output = event["data"]["output"]
        for secret in ("query-private", "base64-private", "url-private"):
            self.assertNotIn(secret, output)
        self.assertIn('"token_count":"197"', output)

    def test_invalid_input_creates_no_events(self):
        cases = [{"task_id": " "}, {"actor": ""}, {"summary": None}, {"source": ""},
                 {"kind": "delete"}, {"data": []}, {"data": {"x": float("nan")}},
                 {"data": {"x": float("inf")}}, {"data": {"x": object()}},
                 {"data": {1: "invalid key"}}, {"occurred_at": "2026-10-09"}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises((ValueError, TypeError)):
                self.append(**case)
        self.assertEqual(self.store.verify(), 0)

    def test_journal_created_private_and_existing_mode_tightened(self):
        store = MemoryStore(self.root / "private-memory")
        store.append(task_id="DEV-TEST", kind="action", actor="tester", summary="Private")
        self.assertEqual(store.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
        store.path.chmod(0o644)
        self.assertEqual(store.verify(), 1)
        self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_journal_symlink_is_rejected_without_touching_target(self):
        target = self.root / "unrelated-file"
        target.write_text("Do not change")
        target.chmod(0o644)
        self.store.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.append()
        self.assertEqual(target.read_text(), "Do not change")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_authorization_headers_redact_complete_credentials(self):
        credentials = "dXNlcjpzdXBlcnNlY3JldA=="
        event = self.append(
            summary=f"Authorization: Basic {credentials}\nNext action",
            data={"output": f"Proxy-Authorization: Basic {credentials}; status=200\n"
                            "Authorization: Bearer private-header\n"
                            "token_count=197"})
        serialized = json.dumps(event)
        self.assertNotIn(credentials, serialized)
        self.assertNotIn("private-header", serialized)
        self.assertIn("Next action", event["summary"])
        self.assertIn("status=200", event["data"]["output"])
        self.assertIn("token_count=197", event["data"]["output"])
        self.assertNotIn(credentials.encode(), self.store.path.read_bytes())
        self.assertEqual(self.store.verify(), 1)


if __name__ == "__main__":
    unittest.main()
