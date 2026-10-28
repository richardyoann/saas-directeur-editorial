"""Failure boundaries of image generation without an HTTP framework or database."""
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from threading import BoundedSemaphore

from editorial.media.application import GenerateSceneImage
from editorial.media.contracts import Identity, ImageRequest, StoredAsset, MediaOperationError, PersistenceUnavailable, RunConflict
from editorial.media_rules import ImageUnavailable
from test_visuals import PNG


class ImageApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identity = Identity(uuid4(), uuid4())
        self.request = ImageRequest(uuid4(), 1)
        self.scene = uuid4()
        self.repository = Mock()
        self.repository.plan.return_value = {"approved": True, "scenes": [
            {"scene_id": str(self.scene), "prompt": "synthetic coast"}]}
        self.repository.reserve.return_value = (self.scene, uuid4())
        self.repository.complete.return_value = {"status": "ready"}
        self.renderer = Mock()
        self.renderer.configured.return_value = True
        self.renderer.render = AsyncMock(return_value=PNG)
        self.storage = Mock()
        self.storage.save.return_value = StoredAsset(None, None)
        self.capacity = BoundedSemaphore(1)
        self.service = GenerateSceneImage(self.repository, self.renderer, self.storage, self.capacity)

    async def test_success_reserves_authenticated_identity_and_acknowledges_after_commit(self):
        order = []
        self.repository.complete.side_effect = lambda *a, **kw: order.append('commit') or {"status": "ready"}
        self.storage.acknowledge.side_effect = lambda receipt: order.append('ack')
        self.assertEqual(await self.service.execute(self.identity, self.request), {"status": "ready"})
        self.assertEqual(order, ['commit', 'ack'])
        self.repository.reserve.assert_called_once_with(self.identity, self.request, self.scene, 'synthetic coast')
        self.assertEqual(self.repository.complete.call_args.kwargs['byte_count'], len(PNG))

    async def test_unapproved_never_reserves_or_calls_engine(self):
        self.repository.plan.return_value['approved'] = False
        with self.assertRaisesRegex(MediaOperationError, 'approval_required'):
            await self.service.execute(self.identity, self.request)
        self.repository.reserve.assert_not_called()
        self.renderer.render.assert_not_called()

    async def test_preflight_failure_never_reserves(self):
        self.storage.preflight.side_effect = ImageUnavailable()
        with self.assertRaisesRegex(MediaOperationError, 'storage_unavailable'):
            await self.service.execute(self.identity, self.request)
        self.repository.reserve.assert_not_called()

    async def test_commit_loss_keeps_recovery_and_does_not_record_false_failure(self):
        self.repository.complete.side_effect = PersistenceUnavailable()
        with self.assertRaisesRegex(MediaOperationError, 'commit_uncertain'):
            await self.service.execute(self.identity, self.request)
        self.storage.acknowledge.assert_not_called()
        self.repository.fail.assert_not_called()
        self.renderer.render.assert_awaited_once()

    async def test_storage_uncertain_is_recorded_without_ack_or_retry(self):
        self.storage.save.side_effect = ImageUnavailable('image_storage_result_uncertain')
        with self.assertRaisesRegex(MediaOperationError, 'image_storage_result_uncertain'):
            await self.service.execute(self.identity, self.request)
        self.renderer.render.assert_awaited_once()
        self.repository.fail.assert_called_once()
        self.storage.acknowledge.assert_not_called()

    async def test_timeout_never_retries(self):
        self.renderer.render.side_effect = ImageUnavailable('image_provider_timeout')
        with self.assertRaisesRegex(MediaOperationError, 'image_provider_timeout'):
            await self.service.execute(self.identity, self.request)
        self.renderer.render.assert_awaited_once()
        self.repository.fail.assert_called_once()

    async def test_invalid_png_is_not_stored(self):
        self.renderer.render.return_value = b'corrupt'
        with self.assertRaisesRegex(MediaOperationError, 'image_provider_invalid_or_unavailable'):
            await self.service.execute(self.identity, self.request)
        self.storage.save.assert_not_called()
        self.repository.fail.assert_called_once()

    async def test_cleanup_failure_after_commit_remains_success(self):
        self.storage.acknowledge.side_effect = OSError('synthetic')
        self.assertEqual(await self.service.execute(self.identity, self.request), {"status": "ready"})

    async def test_unexpected_failure_releases_capacity_without_automatic_replay(self):
        self.renderer.render.side_effect = RuntimeError('synthetic')
        with self.assertRaises(RuntimeError):
            await self.service.execute(self.identity, self.request)
        self.assertTrue(self.capacity.acquire(blocking=False))
        self.capacity.release()
        self.repository.fail.assert_not_called()

    async def test_busy_rejects_before_repository_access(self):
        self.capacity.acquire()
        try:
            with self.assertRaisesRegex(MediaOperationError, 'capacity_busy'):
                await self.service.execute(self.identity, self.request)
            self.repository.plan.assert_not_called()
        finally:
            self.capacity.release()


    async def test_reservation_rejection_never_calls_engine(self):
        self.repository.reserve.side_effect = RunConflict()
        with self.assertRaisesRegex(MediaOperationError, 'reservation_conflict'):
            await self.service.execute(self.identity, self.request)
        self.renderer.render.assert_not_called()
        self.assertTrue(self.capacity.acquire(blocking=False))
        self.capacity.release()

    async def test_failure_record_ack_loss_is_uncertain(self):
        self.renderer.render.side_effect = ImageUnavailable('image_provider_timeout')
        self.repository.fail.side_effect = PersistenceUnavailable()
        with self.assertRaisesRegex(MediaOperationError, 'failure_uncertain'):
            await self.service.execute(self.identity, self.request)
        self.renderer.render.assert_awaited_once()
        self.storage.acknowledge.assert_not_called()

    async def test_telemetry_port_receives_only_ready_or_failed_measurements(self):
        telemetry = Mock()
        service = GenerateSceneImage(self.repository, self.renderer, self.storage,
                                     BoundedSemaphore(1), telemetry=telemetry)
        await service.execute(self.identity, self.request)
        ready = telemetry.call_args.kwargs
        self.assertEqual(ready['status'], 'ready')
        self.assertEqual(ready['byte_count'], len(PNG))
        self.assertEqual(ready['scene_id'], self.scene)
        self.renderer.render.side_effect = ImageUnavailable('image_provider_timeout')
        with self.assertRaisesRegex(MediaOperationError, 'image_provider_timeout'):
            await service.execute(self.identity, self.request)
        failed = telemetry.call_args.kwargs
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error_code'], 'image_provider_timeout')

    async def test_unconfigured_engine_never_accesses_repository(self):
        self.renderer.configured.return_value = False
        with self.assertRaisesRegex(MediaOperationError, 'provider_unconfigured'):
            await self.service.execute(self.identity, self.request)
        self.repository.plan.assert_not_called()
