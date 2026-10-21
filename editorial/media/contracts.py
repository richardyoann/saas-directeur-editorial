"""Framework-free image use-case ports and immutable request context."""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class Identity:
    tenant: UUID
    actor: UUID


@dataclass(frozen=True)
class ImageRequest:
    run_id: UUID
    scene_number: int


@dataclass(frozen=True)
class StoredAsset:
    reference: dict | None
    recovery: object | None  # Opaque adapter-owned handle; never exposed by the API.


class RunConflict(Exception):
    pass


class RunMissing(Exception):
    pass


class PersistenceUnavailable(Exception):
    pass


class MediaOperationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MediaRepository(Protocol):
    def plan(self, identity: Identity, run_id: UUID) -> dict: ...
    def reserve(self, identity: Identity, request: ImageRequest, scene_id: UUID,
                prompt: str) -> tuple[UUID, UUID]: ...
    def complete(self, identity: Identity, request: ImageRequest, scene_id: UUID, **metadata) -> dict: ...
    def fail(self, identity: Identity, request: ImageRequest, scene_id: UUID,
             code: str, duration: float) -> None: ...

    def catalog(self, identity: Identity, run_id: UUID) -> list[dict]: ...
    def asset(self, identity: Identity, run_id: UUID, scene_number: int) -> tuple[UUID, dict | None]: ...
    def audit_counts(self, identity: Identity, run_id: UUID) -> dict[str, int]: ...


class ImageRenderer(Protocol):
    def configured(self) -> bool: ...
    async def render(self, prompt: str) -> bytes: ...


class MediaStorage(Protocol):
    def preflight(self, tenant: UUID, run_id: UUID, scene_id: UUID) -> None: ...
    def save(self, tenant: UUID, run_id: UUID, scene_id: UUID, data: bytes) -> StoredAsset: ...
    def load(self, tenant: UUID, run_id: UUID, scene_id: UUID, reference: dict | None = None) -> bytes: ...
    def acknowledge(self, receipt: StoredAsset) -> None: ...


class MediaCapacity(Protocol):
    def acquire(self, blocking: bool = False) -> bool: ...
    def release(self) -> None: ...
