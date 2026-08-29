"""Logical storage-role routing across multiple concurrent object providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .object_provider import ObjectLocation, ObjectStorageProvider, StoragePreflight


class StorageRole(StrEnum):
    ORIGINALS = "originals"
    DERIVATIVES = "derivatives"
    METADATA = "metadata"
    RESULTS = "results"
    AUDIT = "audit"
    BACKUP = "backup"
    TEMP = "temp"


@dataclass(frozen=True)
class StorageRoute:
    role: StorageRole
    provider_id: str
    bucket: str
    prefix: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id or not self.bucket:
            raise ValueError("provider_id and bucket are required")
        prefix = self.prefix.strip("/")
        if ".." in prefix.split("/"):
            raise ValueError("Unsafe storage route prefix")
        object.__setattr__(self, "prefix", prefix)


@dataclass(frozen=True)
class ResolvedStorage:
    provider: ObjectStorageProvider
    location: ObjectLocation
    role: StorageRole


class StorageProviderRegistry:
    """Runtime registry that keeps domain code independent of storage vendors.

    A logical role maps to exactly one provider/bucket route. Different roles may point
    to different providers, enabling retained originals on one target and disposable
    derivatives/cache on another without changing media-domain code.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ObjectStorageProvider] = {}
        self._routes: dict[StorageRole, StorageRoute] = {}

    def register(self, provider: ObjectStorageProvider) -> None:
        if not provider.provider_id:
            raise ValueError("provider_id is required")
        if provider.provider_id in self._providers:
            raise ValueError(f"Duplicate storage provider: {provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def route(self, route: StorageRoute) -> None:
        if route.provider_id not in self._providers:
            raise ValueError(f"Unknown storage provider: {route.provider_id}")
        self._routes[route.role] = route

    def resolve(self, role: StorageRole, key: str) -> ResolvedStorage:
        try:
            route = self._routes[role]
        except KeyError as error:
            raise KeyError(f"No storage route configured for role {role.value}") from error
        normalized = key.strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError("Unsafe object key")
        full_key = f"{route.prefix}/{normalized}" if route.prefix else normalized
        location = ObjectLocation(
            provider_id=route.provider_id,
            bucket=route.bucket,
            key=full_key,
        )
        return ResolvedStorage(self._providers[route.provider_id], location, role)

    def provider(self, provider_id: str) -> ObjectStorageProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError(f"Unknown storage provider: {provider_id}") from error

    def health(self) -> dict[str, StoragePreflight]:
        return {
            provider_id: provider.preflight()
            for provider_id, provider in sorted(self._providers.items())
        }

    @property
    def routes(self) -> tuple[StorageRoute, ...]:
        return tuple(self._routes[role] for role in sorted(self._routes, key=lambda item: item.value))
