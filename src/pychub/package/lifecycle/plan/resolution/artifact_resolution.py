from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Generic, TypeVar

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.helper.wheel_tag_utils import choose_wheel_tag
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.caching_model import (
    WheelCacheModel,
    WheelCacheIndexModel,
    MetadataCacheModel,
    MetadataCacheIndexModel,
    BaseCacheIndexModel, wheel_cache_key, metadata_cache_key, get_uri_info,
)
from pychub.package.lifecycle.plan.resolution.resolution_config_model import (
    BaseResolverConfig,
    WheelResolverConfig,
    MetadataResolverConfig, StrategyType,
)

# Your existing result object stays the same shape.
HASH_ALGORITHM = "sha256"


def compute_hash_and_size(path: Path) -> tuple[str, int]:
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
    id: str
    path: Path
    origin_uri: str
    hash_algorithm: str
    hash: str
    size_bytes: int
    timestamp: datetime

    def to_mapping(self) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ArtifactResolutionResult:
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
    Coordinator that:
      - computes a deterministic cache key
      - checks cache
      - on miss, runs strategies
      - records cache index entry
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

        entry = self._cache_put(resolved=resolved, wheel_key=wheel_key, uri=uri)
        return entry


# -------------------------------------------------------------------
# Wheel coordinator
# -------------------------------------------------------------------

def _wheel_filename_from_uri(uri: str) -> str:
    # minimal, consistent with your existing wheel_strategy helpers
    return Path(uri.split("?", 1)[0]).name


class WheelArtifactResolver(ArtifactResolver[WheelResolverConfig, Any, str, WheelCacheIndexModel]):
    """
    Ref is a URI (string). Your higher layer can resolve WheelKey->URI using Pep691Metadata,
    then call into here. Keeps this resolver dumb and focused.
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
        parsed_filename = _wheel_filename_from_uri(uri)
        if wheel_key is None:
            _, _, _, wheel_key, _ = get_uri_info(uri=uri)
        tag = choose_wheel_tag(parsed_filename, wheel_key.name, wheel_key.version)
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

    def _run_strategies(self, *, wheel_key: WheelKey | None, uri: str | None) -> tuple[Path, str] | None:
        if uri is None:
            return None
        for strat in sorted(self.strategies, key=lambda s: s.strategy_config.precedence):
            # follows your new base strategy shape: resolve(dest_dir, **kwargs)
            try:
                p = strat.resolve(dest_dir=self.cache_root, uri=uri)
            except Exception:
                continue

            if p is not None:
                return p, uri

        return None


# -------------------------------------------------------------------
# Metadata coordinator (downloads metadata to file, then caches it)
# -------------------------------------------------------------------

class MetadataArtifactResolver(ArtifactResolver[MetadataResolverConfig, Any, WheelKey, MetadataCacheIndexModel]):
    _index: MetadataCacheModel

    def __init__(self, config: MetadataResolverConfig, strategies: Sequence[Any], destination_dir: Path):
        super().__init__(config=config, strategies=strategies, destination_dir=destination_dir)
        self._index = MetadataCacheModel()

    def _cache_key_for(self, *, wheel_key: WheelKey | None, uri: str | None) -> str:
        if wheel_key is None:
            raise ValueError("Cannot compute cache key for metadata resolver without wheel key")
        return metadata_cache_key(wheel_key=wheel_key)

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
        cache_key = metadata_cache_key(wheel_key=wheel_key)
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
                p = strat.resolve(dest_dir=self.cache_root, wheel_key=wheel_key, uri=uri)
            except Exception:
                continue

            if p is not None:
                # provenance should be real. strategies should pass it back if they can.
                origin_uri = getattr(strat, "last_origin_uri", None) or f"strategy:{strat.name}"
                return p, origin_uri

        return None
