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
