"""PostgreSQL transactions for voice, video and subtitle production media.

Bytes are written by the storage adapter outside the transaction. This module
only owns rows, version checks, audit and outbox; no HTTP, renderer or S3 call.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid5

import psycopg

from editorial.media.contracts import PersistenceUnavailable, RunConflict, RunMissing

VOICE = "voice"
VIDEO = "video"
SUBTITLES = "subtitles"
KINDS = (VOICE, VIDEO, SUBTITLES)
# One deterministic asset per storyboard scenario and media kind. A revised
# storyboard produces a new scenario id, therefore new asset ids.
_SUFFIX = {"voice": "production-voice-v1", "video": "production-video-v1",
           "subtitles": "production-subtitles-v1"}
UNCERTAIN = frozenset({"voice_provider_timeout", "voice_storage_result_uncertain",
                       "video_render_interrupted", "video_storage_result_uncertain",
                       "media_reservation_expired"})
# A reservation that was never closed (process crash, database outage during
# publication) may be recovered after this delay; the longest synthesis is far
# below it, so an in-flight job is never taken over.
LEASE_SECONDS = 3600
MAX_ATTEMPTS = 1000


class PostgresProductionMediaRepository:
    def __init__(self, connect, audit_write, get_run, clock, code_version):
        self.connect, self._write, self.get = connect, audit_write, get_run
        self._clock, self._code_version = clock, code_version

    @staticmethod
    def asset_id(scenario_id, kind):
        if kind not in KINDS:
            raise ValueError("production_media_kind_invalid")
        return uuid5(UUID(str(scenario_id)), _SUFFIX[kind])

    @staticmethod
    def _approved_run(conn, tenant, run_id, *, lock):
        # Same lock order as image reservation and review: run first.
        query = ("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                 "AND entity_id=%s AND NOT deleted" + (" FOR UPDATE" if lock else ""))
        row = conn.execute(query, (tenant, run_id)).fetchone()
        if not row or row[0].get("type") != "editorial_run":
            raise RunMissing()
        return row[0]

    @staticmethod
    def _scenes(run):
        board = run.get("storyboard")
        scene_ids = run.get("scene_ids")
        if not board or not isinstance(board.get("scenes"), list) or not isinstance(scene_ids, list):
            raise RunConflict()
        scenes = []
        for number, (scene, scene_id) in enumerate(zip(board["scenes"], scene_ids), 1):
            scenes.append({"scene_number": number, "scene_id": str(scene_id),
                           "title": scene.get("title"), "narration": scene.get("narration"),
                           "duration_seconds": scene.get("duration_seconds")})
        return scenes

    def _asset(self, conn, tenant, asset_id):
        return conn.execute(
            "SELECT version, content FROM po_entity WHERE tenant_id=%s AND kind='result' "
            "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, asset_id)).fetchone()

    def plan(self, tenant, run_id):
        """Read-only production state: prerequisites, media and scene inputs."""
        run = self.get(tenant, run_id)
        if not run.get("storyboard") or run.get("storyboard_stale"):
            return {"run_id": str(run_id), "approved": False, "scenario_id": None,
                    "scene_count": 0, "duration_seconds": 0, "scenes": [], "media": {},
                    "ready_for_voice": False, "ready_for_video": False,
                    "missing_images": []}
        scenes = self._scenes(run)
        scenario_id = run.get("scenario_id")
        if not isinstance(scenario_id, str):
            raise RunConflict()
        with self.connect() as conn:
            images = []
            for scene in scenes:
                row = conn.execute(
                    "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                    "AND entity_id=%s AND NOT deleted",
                    (tenant, self._image_id(scene["scene_id"]))).fetchone()
                asset = row[0] if row and row[0].get("scenario_id") == scenario_id else None
                images.append({
                    "status": asset.get("status", "not_generated") if asset else "not_generated",
                    "storage": asset.get("storage") if asset else None,
                })
            media = {}
            for kind in KINDS:
                row = conn.execute(
                    "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                    "AND entity_id=%s AND NOT deleted",
                    (tenant, self.asset_id(scenario_id, kind))).fetchone()
                content = row[0] if row and row[0].get("scenario_id") == scenario_id else None
                if content:
                    media[kind] = {
                        "id": str(self.asset_id(scenario_id, kind)),
                        "status": content.get("status", "failed"),
                        "sha256": content.get("sha256"),
                        "size_bytes": content.get("byte_count"),
                        "duration_seconds": content.get("duration_seconds"),
                        "created_at": content.get("created_at"),
                        "finished_at": content.get("finished_at"),
                        "error_code": content.get("error_code"),
                    }
        approved = run.get("status") == "approved" and run.get("storyboard_stale") in (None, False)
        total = sum(scene.get("duration_seconds") or 0 for scene in scenes
                    if type(scene.get("duration_seconds")) is int)
        missing = [image["status"] != "ready" for image in images]
        voice_ready = media.get(VOICE, {}).get("status") == "ready"
        return {"run_id": str(run_id), "approved": approved, "scenario_id": scenario_id,
                "scene_count": len(scenes), "duration_seconds": total,
                "scenes": [
                    {**{key: scene[key] for key in ("scene_number", "title", "narration",
                                                    "duration_seconds")},
                     "image_status": image["status"]}
                    for scene, image in zip(scenes, images)
                ],
                "media": media,
                "ready_for_voice": approved and total == 75 and len(scenes) >= 1,
                "ready_for_video": (approved and total == 75 and voice_ready
                                    and not any(missing)),
                "missing_images": [scene["scene_number"] for scene, absent
                                   in zip(scenes, missing) if absent]}

    @staticmethod
    def _timestamp(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _abandoned(self, record):
        created, now = self._timestamp(record.get("created_at")), self._timestamp(self._clock())
        return bool(created and now and (now - created).total_seconds() >= LEASE_SECONDS)

    @staticmethod
    def _image_id(scene_id):
        return uuid5(UUID(str(scene_id)), "private-image-v1")

    def inputs(self, tenant, run_id, kind):
        """Resolve approved narration, scene durations and stored prerequisites."""
        with self.connect() as conn:
            run = self._approved_run(conn, tenant, run_id, lock=False)
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunConflict()
            scenes = self._scenes(run)
            scenario_id = run.get("scenario_id")
            images, voice = [], None
            for scene in scenes:
                scene_id = UUID(str(scene["scene_id"]))
                row = conn.execute(
                    "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                    "AND entity_id=%s AND NOT deleted",
                    (tenant, self._image_id(scene_id))).fetchone()
                asset = row[0] if row and row[0].get("scenario_id") == scenario_id else None
                if not asset or asset.get("status") != "ready" or not asset.get("storage"):
                    images.append(None)
                else:
                    # The image adapter keys files by scene id; the asset id is
                    # the database identity and must never be used as a path.
                    images.append({"asset_id": str(self._image_id(scene_id)),
                                   "scene_id": str(scene_id),
                                   "storage": asset["storage"]})
            voice_id = self.asset_id(scenario_id, VOICE)
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, voice_id)).fetchone()
            if row and row[0].get("scenario_id") == scenario_id and row[0].get("status") == "ready":
                voice = {"asset_id": str(voice_id), "storage": row[0].get("storage")}
            total = sum(scene["duration_seconds"] for scene in scenes
                        if type(scene["duration_seconds"]) is int)
            return {"scenario_id": scenario_id, "scenes": scenes,
                    "images": images, "voice": voice, "total_seconds": total}

    def reserve(self, tenant, actor, run_id, kind, *, scenario_id):
        """Reserve one media attempt; a failed attempt may be retried once at a time."""
        with self.connect() as conn:
            run = self._approved_run(conn, tenant, run_id, lock=True)
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunConflict()
            if run.get("scenario_id") != scenario_id:
                raise RunConflict()
            asset_id = self.asset_id(scenario_id, kind)
            row = self._asset(conn, tenant, asset_id)
            version, previous = (row if row else (0, None))
            if previous and previous.get("status") == "ready":
                raise RunConflict()
            if previous and previous.get("status") == "generating":
                if not self._abandoned(previous):
                    raise RunConflict()
                expired = dict(previous)
                expired.update(status="failed", finished_at=self._clock(),
                               error_code="media_reservation_expired",
                               outcome_uncertain=True)
                self._write(conn, tenant, actor, run_id, "result", asset_id, expired,
                            version)
                version, previous = version + 1, expired
            elif previous and previous.get("status") != "failed":
                raise RunConflict()
            attempt = (previous or {}).get("attempt", 0) + 1
            if attempt > MAX_ATTEMPTS:
                raise RunConflict()
            record = {"type": "production_media", "run_id": str(run_id),
                      "scenario_id": scenario_id, "kind": kind,
                      "status": "generating", "created_at": self._clock(),
                      "code_version": self._code_version(),
                      "attempt": attempt}
            self._write(conn, tenant, actor, run_id, "result", asset_id, record, version)
            result = {"asset_id": asset_id, "version": version + 1,
                      "attempt": record["attempt"], "scenario_id": scenario_id}
            if kind == VIDEO:
                result["subtitles_id"] = self.asset_id(scenario_id, SUBTITLES)
            return result

    def complete(self, tenant, actor, run_id, kind, *, scenario_id, storage,
                 sha256, byte_count, duration_seconds=None, extra_storage=None):
        """Publish a ready media row, plus sidecar rows (subtitles) atomically."""
        with self.connect() as conn:
            run = self._approved_run(conn, tenant, run_id, lock=True)
            if run.get("status") != "approved" or run.get("scenario_id") != scenario_id:
                raise RunConflict()
            asset_id = self.asset_id(scenario_id, kind)
            row = self._asset(conn, tenant, asset_id)
            if not row or row[1].get("status") != "generating":
                raise RunConflict()
            version, record = row
            record.update(status="ready", finished_at=self._clock(), storage=storage,
                          sha256=sha256, byte_count=byte_count,
                          duration_seconds=duration_seconds, error_code=None,
                          outcome_uncertain=False)
            self._write(conn, tenant, actor, run_id, "result", asset_id, record, version)
            for side_kind, reference in (extra_storage or {}).items():
                side_id = self.asset_id(scenario_id, side_kind)
                side_row = self._asset(conn, tenant, side_id)
                side_version, side_previous = (side_row if side_row else (0, None))
                side = {"type": "production_media", "run_id": str(run_id),
                        "scenario_id": scenario_id, "kind": side_kind,
                        "status": "ready", "created_at": self._clock(),
                        "finished_at": self._clock(), "code_version": self._code_version(),
                        "storage": reference.get("reference", reference),
                        "sha256": reference.get("sha256"),
                        "byte_count": reference.get("size"),
                        "attempt": reference.get("attempt")
                        or (side_previous or {}).get("attempt", 0) + 1}
                self._write(conn, tenant, actor, run_id, "result", side_id, side, side_version)
            return {"media_id": str(asset_id), "kind": kind, "sha256": sha256,
                    "size_bytes": byte_count, "duration_seconds": duration_seconds}

    def fail(self, tenant, actor, run_id, kind, *, scenario_id, error_code, duration_seconds=None):
        with self.connect() as conn:
            run = self._approved_run(conn, tenant, run_id, lock=True)
            asset_id = self.asset_id(scenario_id, kind)
            row = self._asset(conn, tenant, asset_id)
            if not row or row[1].get("status") != "generating":
                return
            version, record = row
            record.update(status="failed", finished_at=self._clock(),
                          error_code=error_code, duration_seconds=duration_seconds,
                          outcome_uncertain=error_code in UNCERTAIN)
            self._write(conn, tenant, actor, run_id, "result", asset_id, record, version)

    def reference(self, tenant, run_id, media_id):
        """Tenant-scoped ready media reference, never a bucket/object key to clients."""
        self.get(tenant, run_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, media_id)).fetchone()
        if (not row or row[0].get("type") != "production_media"
                or row[0].get("run_id") != str(run_id) or row[0].get("status") != "ready"
                or not row[0].get("storage")):
            raise RunMissing()
        content = row[0]
        return {"kind": content.get("kind"), "storage": content["storage"],
                "sha256": content.get("sha256"), "size": content.get("byte_count"),
                "duration_seconds": content.get("duration_seconds")}


class ProductionMediaAdapter:
    """Translate connectivity failures at the application port boundary."""

    def __init__(self, backend):
        self.backend = backend

    def _call(self, name, *args, **kwargs):
        try:
            return getattr(self.backend, name)(*args, **kwargs)
        except psycopg.Error:
            raise PersistenceUnavailable() from None

    def plan(self, identity, run_id):
        return self._call("plan", identity.tenant, run_id)

    def inputs(self, identity, run_id, kind):
        return self._call("inputs", identity.tenant, run_id, kind)

    def reserve(self, identity, run_id, kind, scenario_id):
        return self._call("reserve", identity.tenant, identity.actor, run_id, kind,
                          scenario_id=scenario_id)

    def complete(self, identity, run_id, kind, **kwargs):
        return self._call("complete", identity.tenant, identity.actor, run_id, kind, **kwargs)

    def fail(self, identity, run_id, kind, **kwargs):
        return self._call("fail", identity.tenant, identity.actor, run_id, kind, **kwargs)

    def reference(self, identity, run_id, media_id):
        return self._call("reference", identity.tenant, run_id, media_id)
