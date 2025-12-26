from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Generic, TypeVar

from typing_extensions import Self

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.caching_model import (
    WheelCacheModel,
    WheelCacheIndexModel,
    MetadataCacheModel,
    MetadataCacheIndexModel,
    BaseCacheIndexModel,
    wheel_cache_key,
    project_cache_key,
    metadata_cache_key,
)
from pychub.package.lifecycle.plan.resolution.resolution_config_model import (
    BaseResolverConfig,
    WheelResolverConfig,
    MetadataResolverConfig,
    StrategyType,
)

# Your existing result object stays the same shape.
HASH_ALGORITHM = "sha256"


def compute_hash_and_size(path: Path) -> tuple[str, int]:
    """
    Computes the SHA-256 hash and the size of a file specified by the given path.

    This function reads the file in chunks, calculates its SHA-256 hash,
    and determines its total size in bytes. It is designed to work for
    large files by reading them in manageable-sized blocks.

    Args:
        path (Path): The path to the file for which the hash and size
            are to be computed.

    Returns:
        tuple[str, int]: A tuple containing the SHA-256 hash as a string
            and the size of the file in bytes as an integer.
    """
    h = sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


@dataclass(kw_only=True, frozen=True)
class ArtifactResolutionResult(MultiformatModelMixin):
    """
    Represents the result of resolving an artifact in a computing or data processing
    context.

    The class encapsulates the details of an artifact such as its unique identifier,
    location in the filesystem, origin, integrity details, and metadata related to
    its size and timestamp. It provides mechanisms to serialize and deserialize
    the artifact information into dictionary-based mappings, supporting seamless
    interoperability with external systems.

    Attributes:
        id (str): A unique identifier for the artifact.
        path (Path): The filesystem path where the artifact is stored.
        origin_uri (str): The URI describing the origin or source of the artifact.
        hash_algorithm (str): The algorithm used to compute the artifact's hash.
        hash (str): The hash value of the artifact, used for verifying integrity.
        size_bytes (int): The size of the artifact in bytes.
        timestamp (datetime): The timestamp indicating when the artifact was resolved.
    """
    id: str
    path: Path
    origin_uri: str
    hash_algorithm: str
    hash: str
    size_bytes: int
    timestamp: datetime

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": str(self.path),
            "origin_uri": self.origin_uri,
            "hash_algorithm": self.hash_algorithm,
            "hash": self.hash,
            "size_bytes": self.size_bytes,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        return cls(
            id=mapping["id"],
            path=Path(mapping["path"]),
            origin_uri=mapping["origin_uri"],
            hash_algorithm=mapping["hash_algorithm"],
            hash=mapping["hash"],
            size_bytes=int(mapping["size_bytes"]),
            timestamp=datetime.fromisoformat(mapping["timestamp"]))


TConfig = TypeVar("TConfig", bound=BaseResolverConfig)
TStrategy = TypeVar("TStrategy")
TRef = TypeVar("TRef")
TCache = TypeVar("TCache")
TEntry = TypeVar("TEntry", bound=BaseCacheIndexModel)


class ArtifactResolver(ABC, Generic[TConfig, TStrategy, TRef, TEntry]):
    """
    ArtifactResolver is an abstract base class that provides a framework
    for resolving, caching, and managing artifacts using configurable strategies.

    This class is designed to support the resolution of artifacts through
    different strategies while leveraging caching mechanisms for efficiency.
    It enforces the implementation of specific cache and resolution methods
    in concrete subclasses to support various use cases. The coordinator flow
    method, `resolve`, is a comprehensive implementation that ties all the
    steps together to manage artifact resolution seamlessly.

    Attributes:
        config (TConfig): Configuration object defining properties and settings
            related to artifact resolution and caching behavior.
        strategies (Sequence[TStrategy]): Collection of strategies used
            to resolve artifacts.
        destination_dir (Path): Path to the directory where resolved artifacts
            are stored.
    """

    config: TConfig
    strategies: Sequence[TStrategy]
    destination_dir: Path

    def __init__(self, config: TConfig, strategies: Sequence[TStrategy], destination_dir: Path):
        self.config = config
        self.strategies = strategies
        self.destination_dir = destination_dir

    @property
    def cache_root(self) -> Path:
        return self.config.local_cache_root if self.config.project_isolation else self.config.global_cache_root

    @property
    def expiration_delta(self) -> timedelta:
        return timedelta(minutes=int(self.config.update_interval))

    # ----- cache hooks (implemented by concrete resolvers) -----

    @abstractmethod
    def _cache_get(self, cache_key: str) -> TEntry | None:
        raise NotImplementedError

    @abstractmethod
    def _cache_put(
            self,
            *,
            resolved: tuple[Path, str],
            wheel_key: WheelKey | None,
            uri: str | None) -> TEntry:
        raise NotImplementedError

    @abstractmethod
    def _cache_key_for(self, *, wheel_key: WheelKey | None, uri: str | None) -> str:
        raise NotImplementedError

    @abstractmethod
    def _run_strategies(self, *, wheel_key: WheelKey | None, uri: str | None) -> tuple[Path, str] | None:
        raise NotImplementedError

    # ----- the common coordinator flow -----

    def resolve(
            self,
            *,
            wheel_key: WheelKey | None = None,
            uri: str | None = None,
            force_refresh: bool = False) -> TEntry | None:
        cache_key = self._cache_key_for(wheel_key=wheel_key, uri=uri)

        if not force_refresh:
            entry = self._cache_get(cache_key)
            if entry is not None and entry.path.exists():
                exp = getattr(entry, "expiration", None)
                if exp is None or exp > datetime.now().replace(microsecond=0):
                    return entry

        resolved = self._run_strategies(wheel_key=wheel_key, uri=uri)
        if resolved is None:
            return None

        resolved_path, origin_uri = resolved

        entry = self._cache_put(resolved=resolved, wheel_key=wheel_key, uri=origin_uri)
        return entry


# -------------------------------------------------------------------
# Wheel coordinator
# -------------------------------------------------------------------

def _wheel_filename_from_uri(uri: str) -> str:
    # minimal, consistent with your existing wheel_strategy helpers
    return Path(uri.split("?", 1)[0]).name


class WheelArtifactResolver(ArtifactResolver[WheelResolverConfig, Any, str, WheelCacheIndexModel]):
    """
    Resolves and manages wheel artifacts within a caching system.

    This class is responsible for handling wheel artifacts, including caching
    wheel files, computing cache keys, and managing expiration policies. It
    leverages strategies for resolving wheel artifacts, ensuring compatibility
    with specific configurations, and efficiently storing relevant metadata in
    a cache index.

    Attributes:
        config (WheelResolverConfig): The configuration used to define behavior
            and constraints for resolving wheel artifacts.

        strategies (Sequence[Any]): A list of resolution strategies to apply when
            retrieving wheel artifacts.

        destination_dir (Path): The directory where resolved artifacts will
            ultimately be stored.
    """

    _index: WheelCacheModel

    def __init__(self, config: WheelResolverConfig, strategies: Sequence[Any], destination_dir: Path):
        super().__init__(config=config, strategies=strategies, destination_dir=destination_dir)
        self._index = WheelCacheModel()

    def _artifact_dir(self) -> Path:
        d = self.cache_root / "wheels"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _cache_key_for(self, *, wheel_key: WheelKey | None, uri: str | None) -> str:
        if uri is None:
            raise ValueError("Cannot compute cache key for wheel resolver without URI")
        return wheel_cache_key(uri=uri)

    def _cache_get(self, cache_key: str) -> WheelCacheIndexModel | None:
        return self._index.get(cache_key)

    def _cache_put(
            self,
            *,
            resolved: tuple[Path, str],
            wheel_key: WheelKey | None,
            uri: str | None) -> WheelCacheIndexModel:
        if uri is None:
            raise ValueError("Cannot cache wheel without URI")
        cache_key = wheel_cache_key(uri=uri)
        now = datetime.now().replace(microsecond=0)
        exp = now + self.expiration_delta
        if wheel_key is None:
            wheel_key = WheelKey.from_uri(uri=uri)
        if wheel_key.metadata is None:
            raise ValueError("Cannot cache wheel without metadata")
        tag = wheel_key.metadata.actual_tag
        file_hash, size_bytes = compute_hash_and_size(resolved[0])

        model = WheelCacheIndexModel(
            key=cache_key,
            path=resolved[0],
            origin_uri=uri,
            wheel_key=wheel_key,
            compatibility_tag=tag,
            hash_algorithm=HASH_ALGORITHM,
            hash=file_hash,
            size_bytes=size_bytes,
            timestamp=now,
            expiration=exp)

        self._index.put(model)
        return model

    def _run_strategies(
            self,
            *,
            wheel_key: WheelKey | None,
            uri: str | None) -> tuple[Path, str] | None:
        if uri is None:
            return None
        for strat in sorted(self.strategies, key=lambda s: s.strategy_config.precedence):
            # follows your new base strategy shape: resolve(dest_dir, **kwargs)
            try:
                p = strat.resolve(dest_dir=self._artifact_dir(), uri=uri)
            except Exception:
                continue

            if p is not None:
                return p, uri

        return None


# -------------------------------------------------------------------
# Metadata coordinator (downloads metadata to file, then caches it)
# -------------------------------------------------------------------

class MetadataArtifactResolver(ArtifactResolver[MetadataResolverConfig, Any, WheelKey, MetadataCacheIndexModel]):
    """
    Provides an artifact resolver specifically for resolving metadata artifacts.

    This class supports caching and execution of strategies to resolve metadata
    artifacts. It manages a metadata cache with expiration capabilities and uses
    a set of strategies to fetch and process metadata based on the configuration
    and a wheel key.

    Attributes:
        config (MetadataResolverConfig): Resolver configuration used to define
            the behavior of strategies and cache.
        strategies (Sequence[Any]): A sequence of strategies to be executed to
            resolve metadata artifacts, prioritized by their defined precedence.
        destination_dir (Path): Path to the directory where resolved artifacts
            are stored.
    """
    _index: MetadataCacheModel

    def __init__(self, config: MetadataResolverConfig, strategies: Sequence[Any], destination_dir: Path):
        super().__init__(config=config, strategies=strategies, destination_dir=destination_dir)
        self._index = MetadataCacheModel()

    def _artifact_dir(self) -> Path:
        d = self.cache_root / "metadata"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _cache_key_for(self, *, wheel_key: WheelKey | None, uri: str | None) -> str:
        if wheel_key is None:
            raise ValueError("Cannot compute cache key for metadata resolver without wheel key")
        metadata_type: StrategyType = getattr(self.config, "strategy_type", StrategyType.UNSPECIFIED)
        if metadata_type == StrategyType.DEPENDENCY_METADATA:
            return metadata_cache_key(wheel_key)
        return project_cache_key(wheel_key)

    def _cache_get(self, cache_key: str) -> MetadataCacheIndexModel | None:
        return self._index.get(cache_key)

    def _cache_put(
            self,
            *,
            resolved: tuple[Path, str],
            wheel_key: WheelKey | None,
            uri: str | None) -> MetadataCacheIndexModel:
        if wheel_key is None:
            raise ValueError("Cannot cache metadata without wheel key")
        cache_key = self._cache_key_for(wheel_key=wheel_key, uri=uri)
        now = datetime.now().replace(microsecond=0)
        exp = now + self.expiration_delta
        file_hash, size_bytes = compute_hash_and_size(resolved[0])
        metadata_type: StrategyType = getattr(self.config, "strategy_type", StrategyType.UNSPECIFIED)

        model = MetadataCacheIndexModel(
            key=cache_key,
            path=resolved[0],
            origin_uri=uri or "unspecified",
            hash_algorithm=HASH_ALGORITHM,
            hash=file_hash,
            size_bytes=size_bytes,
            timestamp=now,
            expiration=exp,
            metadata_type=metadata_type)

        self._index.put(model)
        return model

    def _run_strategies(self, *, wheel_key: WheelKey | None, uri: str | None) -> tuple[Path, str] | None:
        for strat in sorted(self.strategies, key=lambda s: s.strategy_config.precedence):
            try:
                p = strat.resolve(dest_dir=self._artifact_dir(), wheel_key=wheel_key, uri=uri)
            except Exception:
                continue

            if p is not None:
                # provenance should be real. strategies should pass it back if they can.
                origin_uri = getattr(strat, "last_origin_uri", None) or f"strategy:{strat.name}"
                return p, origin_uri

        return None
