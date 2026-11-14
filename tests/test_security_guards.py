import unittest
from unittest.mock import patch

from editorial.media.contracts import RunConflict
from infrastructure.persistence.production_media_repository import PostgresProductionMediaRepository
from scripts import arvor_ci_publish, install_external_skills, mlflow_acceptance, mlflow_healthcheck


class StoryboardIntegrityTests(unittest.TestCase):
    def test_scene_ids_must_match_scenes(self):
        run = {"storyboard": {"scenes": [{}, {}]}, "scene_ids": ["a"]}
        with self.assertRaises(RunConflict):
            PostgresProductionMediaRepository._scenes(run)


class UrlGuardTests(unittest.TestCase):
    def test_github_token_never_leaves_github_api(self):
        for url in ("http://api.github.com/x", "https://evil.example/x", "file:///etc/passwd"):
            with self.subTest(url=url), patch.object(arvor_ci_publish, "urlopen") as opened:
                with self.assertRaises(ValueError):
                    arvor_ci_publish.http_json("GET", url, token="t" * 40)
                opened.assert_not_called()

    def test_skill_installer_only_fetches_github_api(self):
        with patch.object(install_external_skills, "urlopen") as opened:
            with self.assertRaises(ValueError):
                install_external_skills.fetch_json("file:///etc/passwd")
            opened.assert_not_called()

    def test_mlflow_clients_reject_non_http_schemes(self):
        with self.assertRaises(ValueError):
            mlflow_healthcheck.health("file:///etc/passwd", 1)
        with self.assertRaises(ValueError):
            mlflow_acceptance.write_basic_request("ftp://127.0.0.1", "/x", {})


if __name__ == "__main__":
    unittest.main()
