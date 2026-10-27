"""Instrumentation points stay callable when tracking is disabled or broken."""
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from editorial.models import Brief
from editorial.service import run_steps
from production import voice_timeline
from scripts import render_episode


class FakeStore:
    def __init__(self):
        self.steps = []

    def begin_step(self, tenant, actor, run_id, step, prompt):
        self.steps.append(step)

    def save_step(self, tenant, actor, run_id, step, prompt, response, parsed, error):
        return {"status": "failed" if error else "waiting_validation",
                "analysis": parsed if step == "analysis" else None,
                "steps": list(self.steps)}


def analysis_output():
    return json.dumps({"angle": "Angle", "message": "Message",
                       "historical_checks": ["Vérifier"]})


def storyboard_output():
    scene = {"title": "Scène", "duration_seconds": 25,
             "narration": "Narration.", "visual_description": "Village.",
             "characters": ["Marin"], "landscape": "Côte", "colors": ["bleu"],
             "shot": "Large", "emotion": "Calme", "sound": "Vagues",
             "image_prompt": "Village breton"}
    return json.dumps({"title": "Titre", "synopsis": "Synopsis",
                       "scenes": [dict(scene) for _ in range(3)]})


class ScenarioInstrumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_real_steps_are_reported_without_content(self):
        brief = Brief(topic="Légende bretonne", duration_seconds=75, scene_count=3)
        run = {"id": str(uuid4()), "status": "running", "steps": [], "current_step": None,
               "brief": brief.model_dump(), "analysis": None}
        captures = []

        async def fake_generate(client, base_url, prompt, max_tokens, **kwargs):
            step = "analysis" if not captures else "storyboard"
            text = analysis_output() if step == "analysis" else storyboard_output()
            return {"status": "success", "provider": "llama.cpp",
                    "model": r"C:\models\qwen2.5-3b-instruct.gguf",
                    "prompt": prompt, "response": text, "duration_seconds": 1.5,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                              "total_tokens": 15}, "finish_reason": "stop"}

        with patch("editorial.service.generate_text", side_effect=fake_generate), \
                patch.object(run_steps.__globals__["mlflow_tracker"],
                             "record_scenario_step",
                             side_effect=lambda **kwargs: captures.append(kwargs)):
            result = await run_steps(FakeStore(), uuid4(), uuid4(), run,
                                     MagicMock(), "http://127.0.0.1:8081")
        self.assertEqual(result["status"], "waiting_validation")
        self.assertEqual([item["step"] for item in captures], ["analysis", "storyboard"])
        for item in captures:
            self.assertEqual(item["status"], "success")
            self.assertEqual(item["prompt_version"], "1.2.0")
            self.assertEqual(item["max_tokens"], 2048)
            self.assertIn("prompt", item)
            self.assertIn("response", item)

    async def test_provider_failure_is_still_reported_as_failure(self):
        brief = Brief(topic="Légende", duration_seconds=75, scene_count=3)
        run = {"id": str(uuid4()), "status": "running", "steps": [], "current_step": None,
               "brief": brief.model_dump(), "analysis": None}
        from apps.api.llama_provider import ProviderError
        captures = []

        async def failing(client, base_url, prompt, max_tokens, **kwargs):
            raise ProviderError(504, "timeout")

        with patch("editorial.service.generate_text", side_effect=failing), \
                patch.object(run_steps.__globals__["mlflow_tracker"],
                             "record_scenario_step",
                             side_effect=lambda **kwargs: captures.append(kwargs)):
            result = await run_steps(FakeStore(), uuid4(), uuid4(), run,
                                     MagicMock(), "http://127.0.0.1:8081")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0]["status"], "failed")
        self.assertEqual(captures[0]["error_code"], "provider_timeout")


class ExportInstrumentationTests(unittest.TestCase):
    def test_receipt_is_reported_once_with_external_audio(self):
        receipt = {"duration_seconds": 75, "width": 720, "height": 1280,
                   "audio": True, "scenes": [{"scene": 1}], "video_sha256": "a" * 64,
                   "voice_sha256": "b" * 64, "ffmpeg_version": "ffmpeg version test"}
        with patch.object(render_episode.mlflow_tracker, "record_video",
                          return_value="queued") as video, \
                patch.object(render_episode.mlflow_tracker, "record_voice",
                             return_value="queued") as voice:
            result = render_episode.mlflow_tracker.record_export_receipt(
                receipt, tenant=uuid4(), story_id=uuid4())
        self.assertEqual(result, "queued/queued")
        self.assertEqual(video.call_count, 1)
        self.assertEqual(voice.call_count, 1)
        self.assertEqual(voice.call_args.kwargs["engine"], "external-wav")
        self.assertEqual(voice.call_args.kwargs["audio_sha256"], "b" * 64)

    def test_voice_success_and_failure_are_reported(self):
        scenes = [{"duration_seconds": 25, "narration": "Texte secret"} for _ in range(3)]
        with patch.object(voice_timeline, "_synthesize_voice",
                          return_value={"voice_created": True, "duration_seconds": 75,
                                        "voice_sha256": "c" * 64}), \
                patch.object(voice_timeline.mlflow_tracker, "record_voice") as recorder:
            result = voice_timeline.synthesize_voice(
                scenes, "fr.onnx", "/tmp/voice.wav", tenant=uuid4(), story_id=uuid4())
        self.assertTrue(result["voice_created"])
        self.assertEqual(recorder.call_args.kwargs["status"], "ready")
        self.assertEqual(recorder.call_args.kwargs["text"], "Texte secret Texte secret Texte secret")

        with patch.object(voice_timeline, "_synthesize_voice",
                          side_effect=ValueError("tts_scene_too_long")), \
                patch.object(voice_timeline.mlflow_tracker, "record_voice") as recorder:
            with self.assertRaisesRegex(ValueError, "tts_scene_too_long"):
                voice_timeline.synthesize_voice(scenes, "fr.onnx", "/tmp/voice.wav")
        self.assertEqual(recorder.call_args.kwargs["status"], "failed")
        self.assertEqual(recorder.call_args.kwargs["error_code"], "tts_scene_too_long")

    def test_non_uuid_story_reference_is_normalised(self):
        from uuid import UUID
        with patch.object(voice_timeline, "_synthesize_voice",
                          return_value={"voice_created": True, "duration_seconds": 1,
                                        "voice_sha256": "d" * 64}), \
                patch.object(voice_timeline.mlflow_tracker, "record_voice") as recorder:
            voice_timeline.synthesize_voice(
                [{"duration_seconds": 1, "narration": "x"}], "fr.onnx",
                "/tmp/voice.wav", story_id="offline-story")
        UUID(str(recorder.call_args.kwargs["story_id"]))


if __name__ == "__main__":
    unittest.main()
