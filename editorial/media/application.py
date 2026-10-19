"""Image orchestration: SQL, engine and storage are separate short operations."""
import hashlib
import time
from functools import partial
from uuid import UUID

from anyio.to_thread import run_sync

from editorial.media.contracts import (
    Identity, ImageRequest, MediaRepository, ImageRenderer, MediaStorage, MediaCapacity,
    MediaOperationError, PersistenceUnavailable, RunConflict, RunMissing,
)
from editorial.media_rules import ImagePromptTooLong, ImageUnavailable, validate_png


async def offload(function, *args, **kwargs):
    # Same cancellation shielding as Starlette's historical run_in_threadpool.
    return await run_sync(partial(function, *args, **kwargs))


class GenerateSceneImage:
    def __init__(self, repository: MediaRepository, renderer: ImageRenderer,
                 storage: MediaStorage, capacity: MediaCapacity):
        self.repository, self.renderer = repository, renderer
        self.storage, self.capacity = storage, capacity

    async def execute(self, identity: Identity, request: ImageRequest) -> dict:
        if not self.renderer.configured():
            raise MediaOperationError('provider_unconfigured')
        if not self.capacity.acquire(blocking=False):
            raise MediaOperationError('capacity_busy')
        try:
            return await self._execute(identity, request)
        finally:
            self.capacity.release()

    async def _execute(self, identity, request):
        try:
            plan = await offload(self.repository.plan, identity, request.run_id)
            if not plan['approved']:
                raise MediaOperationError('approval_required')
            if request.scene_number < 1 or request.scene_number > len(plan['scenes']):
                raise MediaOperationError('scene_missing')
            scene = plan['scenes'][request.scene_number - 1]
            await offload(self.storage.preflight, identity.tenant, request.run_id, UUID(scene['scene_id']))
            # The repository revalidates this exact prompt/scene under its SQL lock.
            scene_id, _ = await offload(self.repository.reserve, identity, request,
                                        UUID(scene['scene_id']), scene['prompt'])
        except ImagePromptTooLong:
            raise MediaOperationError('prompt_too_long') from None
        except RunMissing:
            raise MediaOperationError('scene_missing') from None
        except RunConflict:
            raise MediaOperationError('reservation_conflict') from None
        except ImageUnavailable:
            raise MediaOperationError('storage_unavailable') from None
        except PersistenceUnavailable:
            raise MediaOperationError('persistence_unavailable') from None

        started = time.monotonic()
        try:
            png = await self.renderer.render(scene['prompt'])
            width, height = validate_png(png)
            saved = await offload(self.storage.save, identity.tenant, request.run_id, scene_id, png)
            try:
                result = await offload(
                    self.repository.complete, identity, request, scene_id,
                    width=width, height=height,
                    duration_seconds=round(time.monotonic() - started, 6),
                    png_sha256=hashlib.sha256(png).hexdigest(), byte_count=len(png),
                    storage=saved.reference,
                )
            except (RunConflict, RunMissing, PersistenceUnavailable):
                # Do not overwrite uncertain success with a failure or erase recovery.
                raise MediaOperationError('commit_uncertain') from None
            try:
                await offload(self.storage.acknowledge, saved)
            except OSError:
                pass  # A redundant recovery file is safer than a false API failure.
            return result
        except ImageUnavailable as error:
            try:
                await offload(self.repository.fail, identity, request, scene_id,
                              error.code, round(time.monotonic() - started, 6))
            except (RunConflict, RunMissing, PersistenceUnavailable):
                raise MediaOperationError('failure_uncertain') from None
            raise MediaOperationError(error.code) from None


class ReadMedia:
    """Read-only projections and integrity checks, independent of HTTP and storage SDKs."""
    def __init__(self, repository: MediaRepository, storage: MediaStorage):
        self.repository, self.storage = repository, storage

    async def plan(self, identity, run_id):
        return await offload(self.repository.plan, identity, run_id)

    async def catalog(self, identity, run_id):
        return await offload(self.repository.catalog, identity, run_id)

    async def download(self, identity, run_id, scene_number):
        scene_id, reference = await offload(self.repository.asset, identity, run_id, scene_number)
        return await offload(self.storage.load, identity.tenant, run_id, scene_id, reference)

    async def verify(self, identity, run_id, expected_scenes):
        from editorial.image_verification import verify_scene, verification_report
        plan = await self.plan(identity, run_id)
        counts = await offload(self.repository.audit_counts, identity, run_id)
        checks = []
        for scene in plan['scenes']:
            png = None
            if plan['approved'] and scene['image_status'] == 'ready':
                try:
                    png = await self.download(identity, run_id, scene['scene_number'])
                except ImageUnavailable:
                    pass
            checks.append(verify_scene(scene, png, counts.get(scene['scene_id'], 0)))
        return verification_report(plan, checks, expected_scenes)
