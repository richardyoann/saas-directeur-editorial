"""Explicit offline preproduction -> FFmpeg -> technical review.

Input snapshots are operator-supplied, not authenticated database reads.
No model invocation, database mutation, publication or automatic retry.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from uuid import UUID, uuid5

from apps.api.llama_provider import strict_json
from production.crew import (ROLES, SPECIALISTS, SpecialistOutput, CriticOutput,
                             quality_gate, source_snapshot)
from production.media_qc import inspect_export
from scripts.render_episode import local_file, render


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_manifest(bundle, *, human_review_confirmed=False):
    """Check snapshot consistency and explicit operator review before rendering."""
    if human_review_confirmed is not True:
        raise ValueError("human_review_confirmation_required")
    if not isinstance(bundle, dict) or type(bundle.get("schema_version")) is not int or bundle["schema_version"] != 1:
        raise ValueError("production_bundle_invalid")
    run, session, media = (bundle.get(key) for key in ("run", "production", "media"))
    if not all(isinstance(value, dict) for value in (run, session, media)):
        raise ValueError("production_bundle_invalid")
    source = source_snapshot(run)
    if source["review_revision"] < 0:
        raise ValueError("source_revision_invalid")
    run_id = str(UUID(run["id"]))
    expected_id = str(uuid5(UUID(run_id), "production-crew-v1:" + str(source["review_revision"])))
    if (session.get("type") != "production_crew_session"
            or session.get("run_id") != run_id or session.get("id") != expected_id
            or session.get("phase") != "ready_for_human_review"
            or session.get("stale") is not False
            or session.get("current_role") is not None or session.get("next_roles") != []):
        raise ValueError("production_not_ready")
    source_hash = fingerprint(source)
    if (type(session.get("source_revision")) is not int
            or session["source_revision"] != source["review_revision"]
            or session.get("source") != source or session.get("source_hash") != source_hash):
        raise ValueError("production_source_mismatch")
    outputs = session.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(ROLES):
        raise ValueError("production_outputs_incomplete")
    validated = {role: SpecialistOutput.model_validate(outputs[role]).model_dump()
                 for role in SPECIALISTS}
    critic = CriticOutput.model_validate(outputs["critic"]).model_dump()
    if critic != session.get("critique") or not quality_gate(critic)["passed"]:
        raise ValueError("production_quality_rejected")
    validated["critic"] = critic
    scenes = source["storyboard"]["scenes"]
    images = media.get("images")
    if (not isinstance(images, list) or len(images) != len(scenes)
            or not isinstance(media.get("voice"), str) or not media["voice"].strip()):
        raise ValueError("production_media_incomplete")
    manifest_scenes = []
    for index, (scene, binding) in enumerate(zip(scenes, images), 1):
        if (not isinstance(binding, dict) or set(binding) != {"scene_index", "image"}
                or type(binding["scene_index"]) is not int or binding["scene_index"] != index
                or not isinstance(binding["image"], str) or not binding["image"].strip()):
            raise ValueError("scene_image_binding_invalid")
        manifest_scenes.append({"image": binding["image"],
                                "duration_seconds": scene["duration_seconds"],
                                "narration": scene["narration"]})
    return {"schema_version": 1, "approved": True, "voice": media["voice"],
            "scenes": manifest_scenes,
            "preproduction": {"run_id": run_id, "session_id": expected_id,
                              "source_revision": source["review_revision"],
                              "source_sha256": source_hash,
                              "role_outputs_sha256": fingerprint(validated),
                              "approval_scope": "offline_operator_declaration"}}


def _private_directory(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_dir():
        raise ValueError("private_directory_invalid")
    return path.resolve()


def render_production(bundle_path, media_directory, destination, *, human_review_confirmed=False):
    """One explicit local attempt; preserve a rejected export for manual inspection."""
    bundle_path = Path(bundle_path)
    if bundle_path.is_symlink() or not bundle_path.is_file() or bundle_path.stat().st_size > 512000:
        raise ValueError("production_bundle_file_invalid")
    raw = bundle_path.read_bytes()
    bundle = strict_json(raw)
    manifest = prepare_manifest(bundle, human_review_confirmed=human_review_confirmed)
    media_root = _private_directory(media_directory)
    images = [local_file(media_root, scene["image"], ".png") for scene in manifest["scenes"]]
    voice = local_file(media_root, manifest["voice"], ".wav")
    destination = Path(destination).absolute()
    _private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination_exists")
    # Atomic exclusive reservation: concurrent invocations cannot share outputs.
    destination.mkdir(mode=0o700)
    evidence = {"schema_version": 1, "status": "rendering",
                "bundle_sha256": hashlib.sha256(raw).hexdigest(),
                "preproduction": manifest["preproduction"],
                "human_release_required": True, "visual_review_required": True,
                "automatic_retry_allowed": False}
    receipt_path = destination / "pipeline_receipt.json"
    receipt_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix=".inputs-", dir=destination) as work:
            work = Path(work)
            for index, image in enumerate(images, 1):
                name = f"scene-{index}.png"
                shutil.copyfile(image, work / name)
                manifest["scenes"][index - 1]["image"] = name
            shutil.copyfile(voice, work / "voice.wav")
            manifest["voice"] = "voice.wav"
            staged_manifest = work / "production.json"
            staged_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = render(staged_manifest, destination / "export")
            report = inspect_export(destination / "export")
            evidence.update(status="technical_passed" if report["technical_passed"] else "technical_rejected",
                            export_receipt_sha256=hashlib.sha256((destination / "export" / "receipt.json").read_bytes()).hexdigest(),
                            technical_review=report, video_sha256=result["video_sha256"])
        receipt_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return {"rendered": True, **report, "duration_seconds": result["duration_seconds"]}
    except Exception:
        # Fixed status only; inputs and any retained export are private.
        evidence.update(status="failed_or_interrupted", automatic_retry_allowed=False)
        receipt_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        raise
