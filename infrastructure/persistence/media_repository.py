"""PostgreSQL media transactions. No HTTP, renderer, file IO or S3 calls."""
from uuid import UUID, uuid5
import psycopg
from editorial.media.contracts import RunConflict, RunMissing, PersistenceUnavailable


class PostgresMediaRepository:
    def __init__(self, connect, audit_write, get_run, clock, code_version):
        self.connect, self._write, self.get = connect, audit_write, get_run
        self._clock, self._code_version = clock, code_version

    @staticmethod
    def _visual_scene(run, scene_number):
        if not run.get("storyboard") or not isinstance(scene_number, int):
            raise RunConflict()
        scene_ids = run.get("scene_ids") or []
        if not (1 <= scene_number <= len(scene_ids)):
            raise RunMissing()
        return UUID(scene_ids[scene_number - 1])

    @staticmethod
    def _visual_id(scene_id):
        return uuid5(scene_id, "private-image-v1")

    def visual_plan(self, tenant, run_id):
        """Projection for UI, no binary payload and no secret storage paths."""
        from editorial.media_rules import characters, image_prompt
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id),
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            board = run.get("storyboard")
            if not board or run.get("storyboard_stale"):
                return {"run_id": str(run_id), "characters": [], "scenes": [],
                        "approved": False}
            entries = []
            scene_ids = run.get("scene_ids") or []
            for i, scene_id in enumerate(scene_ids, 1):
                asset_id = self._visual_id(UUID(scene_id))
                record = conn.execute(
                    "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                    "AND entity_id=%s AND NOT deleted", (tenant, asset_id),
                ).fetchone()
                asset = record[0] if record and record[0].get("scenario_id") == run.get("scenario_id") else None
                generation = None
                if asset:
                    generation = {key: asset.get(key) for key in (
                        "created_at", "finished_at", "duration_seconds", "error_code",
                        "png_sha256", "byte_count", "width", "height", "provenance",
                        "outcome_uncertain", "code_version", "scenario_id")}
                    # Full character/prompt snapshots stay in the private audit record.
                    if generation["provenance"]:
                        generation["provenance"] = {
                            key: value for key, value in generation["provenance"].items()
                            if key != "character_references"}
                entries.append({"scene_number": i, "scene_id": scene_id,
                                "title": board["scenes"][i - 1]["title"],
                                "prompt": image_prompt(run, i),
                                "image_status": asset.get("status", "not_generated") if asset else "not_generated",
                                "generation": generation})
            return {"run_id": str(run_id), "characters": characters(board),
                    "scenes": entries, "approved": run["status"] == "approved"}

    def begin_image(self, tenant, actor, run_id, scene_number, prompt, expected_scene_id=None):
        """Reserve image exactly once; audit and outbox share the transaction."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, run_id),
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunConflict()
            scene_id = self._visual_scene(run, scene_number)
            from editorial.media_rules import image_prompt, image_provenance
            if ((expected_scene_id is not None and scene_id != expected_scene_id)
                    or prompt != image_prompt(run, scene_number)):
                raise RunConflict()
            asset_id = self._visual_id(scene_id)
            existing = conn.execute(
                "SELECT 1 FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, asset_id),
            ).fetchone()
            if existing:
                # Manual reconciliation of failed/ambiguous images only.
                raise RunConflict()
            self._write(conn, tenant, actor, run_id, "result", asset_id,
                        {"type": "scene_image_asset", "run_id": str(run_id),
                         "scenario_id": run["scenario_id"], "scene_id": str(scene_id),
                         "scene_number": scene_number, "status": "generating",
                         "prompt": prompt, "created_at": self._clock(),
                         "code_version": self._code_version(),
                         "provenance": image_provenance(run, scene_number, prompt)})
            return scene_id, asset_id

    def finish_image(self, tenant, actor, run_id, scene_id, *, width=None, height=None,
                     error_code=None, duration_seconds=None, png_sha256=None, byte_count=None, storage=None):
        """Finalize exact reserved record; never overwrite an earlier asset."""
        with self.connect() as conn:
            # Same lock order as reservation/review: treatment before asset.
            # Approval cannot be invalidated between this check and the audit commit.
            current = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, run_id),
            ).fetchone()
            asset_id = self._visual_id(scene_id)
            row = conn.execute(
                "SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, asset_id),
            ).fetchone()
            if not row or row[1].get("type") != "scene_image_asset" or row[1].get("run_id") != str(run_id):
                raise RunMissing()
            version, record = row
            if record["status"] != "generating":
                raise RunConflict()
            if not current or current[0].get("scenario_id") != record["scenario_id"] or current[0].get("status") != "approved":
                raise RunConflict()
            record.update(status="failed" if error_code else "ready",
                          finished_at=self._clock(), error_code=error_code,
                          duration_seconds=duration_seconds,
                          outcome_uncertain=error_code in {
                              "image_provider_timeout", "image_provider_response_uncertain", "image_storage_result_uncertain"})
            if not error_code:
                record.update(width=width, height=height, mime_type="image/png",
                              png_sha256=png_sha256, byte_count=byte_count)
                if storage:
                    record["storage"] = storage
            self._write(conn, tenant, actor, run_id, "result", asset_id, record, version)
            return {"scene_number": record["scene_number"], "status": record["status"],
                    "width": record.get("width"), "height": record.get("height"),
                    "duration_seconds": duration_seconds}

    def image_audit_counts(self, tenant, run_id):
        """Read-only evidence, scoped to the current run and its current scenes."""
        run = self.get(tenant, run_id)
        with self.connect() as conn:
            counts = {}
            for scene_id in run.get("scene_ids") or []:
                asset_id = self._visual_id(UUID(scene_id))
                count = conn.execute(
                    "SELECT COUNT(*) FROM po_audit a JOIN po_outbox o USING(event_id) "
                    "WHERE a.tenant_id=%s AND a.kind='result' AND a.entity_id=%s AND a.correlation_id=%s",
                    (tenant, asset_id, run_id)).fetchone()[0]
                counts[scene_id] = count
            return counts

    def image_asset(self, tenant, run_id, scene_number, include_storage=False):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id)
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunMissing()
            scene_id = self._visual_scene(run, scene_number)
            asset = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, self._visual_id(scene_id)),
            ).fetchone()
            if not asset or asset[0].get("status") != "ready" or asset[0].get("scenario_id") != run["scenario_id"]:
                raise RunMissing()
            return (scene_id, asset[0].get("storage")) if include_storage else scene_id

    def list_media(self, tenant, run_id):
        """Tenant-scoped production media catalog; never expose bucket/object keys."""
        self.get(tenant, run_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT entity_id, content FROM po_entity "
                "WHERE tenant_id=%s AND kind='result' "
                "AND content->>'type'='production_media' "
                "AND content->>'run_id'=%s AND NOT deleted "
                "ORDER BY content->>'created_at' DESC, entity_id DESC LIMIT 100",
                (tenant, str(run_id)),
            ).fetchall()
        return [
            {
                "id": str(entity_id),
                "kind": content.get("storage", {}).get("kind"),
                "size_bytes": content.get("storage", {}).get("size"),
                "sha256": content.get("storage", {}).get("sha256"),
                "created_at": content.get("created_at"),
            }
            for entity_id, content in rows
            if isinstance(content.get("storage"), dict)
        ]

    def record_media(self, tenant, actor, run_id, asset_id, reference):
        """Archive metadata, audit and outbox atomically; bytes stay in MinIO."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, run_id)).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            if row[0].get("status") != "approved" or row[0].get("storyboard_stale"):
                raise RunConflict()
            self._write(conn, tenant, actor, run_id, "result", asset_id,
                        {"type": "production_media", "run_id": str(run_id),
                         "scenario_id": row[0]["scenario_id"], "storage": reference,
                         "created_at": self._clock()}, 0)


class ImageRepositoryAdapter:
    """Translate DB connectivity failures at the application port boundary."""
    def __init__(self, backend):
        self.backend = backend

    def _call(self, name, *args, **kwargs):
        try:
            return getattr(self.backend, name)(*args, **kwargs)
        except psycopg.Error:
            raise PersistenceUnavailable() from None

    def plan(self, identity, run_id):
        return self._call('visual_plan', identity.tenant, run_id)

    def reserve(self, identity, request, scene_id, prompt):
        return self._call('begin_image', identity.tenant, identity.actor,
                          request.run_id, request.scene_number, prompt, scene_id)

    def complete(self, identity, request, scene_id, **metadata):
        return self._call('finish_image', identity.tenant, identity.actor,
                          request.run_id, scene_id, **metadata)

    def fail(self, identity, request, scene_id, code, duration):
        self._call('finish_image', identity.tenant, identity.actor, request.run_id,
                   scene_id, error_code=code, duration_seconds=duration)

    def catalog(self, identity, run_id):
        return self._call('list_media', identity.tenant, run_id)

    def asset(self, identity, run_id, scene_number):
        return self._call('image_asset', identity.tenant, run_id, scene_number, True)

    def audit_counts(self, identity, run_id):
        return self._call('image_audit_counts', identity.tenant, run_id)
