from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deploy_local import activate, assert_current_main


class ReleaseTests(unittest.TestCase):
    def test_obsolete_commit_blocks_install(self):
        from unittest.mock import patch
        import io
        with patch.dict("os.environ", {"GITHUB_TOKEN": "synthetic"}), patch(
            "deploy_local.urllib.request.urlopen", return_value=io.BytesIO(
                b'{"object":{"sha":"newer"}}')):
            with self.assertRaises(RuntimeError):
                assert_current_main("older")

    def test_failed_live_check_restores_previous_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, current = root / "old", root / "new", root / "current"
            old.mkdir(); new.mkdir(); current.symlink_to(old)
            restart, verify, stop = Mock(), Mock(side_effect=[RuntimeError("failed"), None]), Mock()
            with self.assertRaises(RuntimeError):
                activate(current, new, restart, verify, stop)
            self.assertEqual(current.resolve(), old)
            self.assertEqual(restart.call_count, 2)
            stop.assert_not_called()

    def test_first_install_failure_stops_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"; candidate.mkdir()
            stop = Mock()
            with self.assertRaises(RuntimeError):
                activate(root / "current", candidate, Mock(), Mock(side_effect=RuntimeError()), stop)
            self.assertFalse((root / "current").is_symlink())
            stop.assert_called_once()

    def test_success_keeps_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"; candidate.mkdir()
            activate(root / "current", candidate, Mock(), Mock(), Mock())
            self.assertEqual((root / "current").resolve(), candidate)


class ServiceIdentityTests(unittest.TestCase):
    def test_wrong_service_release_blocks_success(self):
        from deploy_local import assert_service_release
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            other = root / "other"
            candidate.mkdir(); other.mkdir()
            process = root / "proc" / "123"
            process.mkdir(parents=True)
            (process / "cwd").symlink_to(other)
            with patch("deploy_local.subprocess.check_output", return_value="123\n"):
                with self.assertRaises(RuntimeError):
                    assert_service_release(candidate, root / "proc")

    def test_matching_service_release_passes(self):
        from deploy_local import assert_service_release
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            candidate.mkdir()
            process = root / "proc" / "123"
            process.mkdir(parents=True)
            (process / "cwd").symlink_to(candidate)
            with patch("deploy_local.subprocess.check_output", return_value="123\n"):
                assert_service_release(candidate, root / "proc")

    def test_stopped_service_blocks_success(self):
        from deploy_local import assert_service_release
        from unittest.mock import patch
        with patch("deploy_local.subprocess.check_output", return_value="0\n"):
            with self.assertRaises(RuntimeError):
                assert_service_release(Path("/synthetic"))


class DuplicateDeliveryTests(unittest.TestCase):
    def test_receipt_must_match_current_release(self):
        from deploy_local import already_delivered
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sha = "a" * 40
            releases = root / "releases"; releases.mkdir()
            release = releases / (sha + "-123"); release.mkdir()
            current = root / "current"; current.symlink_to(release)
            report = root / "last_delivery.json"
            report.write_text(json.dumps({"sha": sha, "installed_live": "passed"}))
            self.assertTrue(already_delivered(root, sha))
            self.assertFalse(already_delivered(root, "b" * 40))
            current.unlink()
            other = releases / ("b" * 40 + "-123"); other.mkdir()
            current.symlink_to(other)
            self.assertFalse(already_delivered(root, sha))
