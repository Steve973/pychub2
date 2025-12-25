from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from operator import attrgetter
from pathlib import Path
from typing import Generic, TypeVar, Any

from cachetools import Cache, TLRUCache, LRUCache
from cachetools import cachedmethod

from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.artifact_resolution import MetadataArtifactResolver
from pychub.package.lifecycle.plan.resolution.artifact_resolution import WheelArtifactResolver
from pychub.package.lifecycle.plan.resolution.caching_model import WheelCacheIndexModel, WheelCacheModel, \
    MetadataCacheIndexModel, MetadataCacheModel, BaseCacheIndexModel, wheel_cache_key, \
    BaseCacheModel, project_cache_key, metadata_cache_key

K = TypeVar("K")  # key type: e.g., str | WheelKey
E = TypeVar("E", bound=BaseCacheIndexModel)  # entry type: WheelCacheIndexModel | MetadataCacheIndexModel
M = TypeVar("M", bound=BaseCacheModel)  # model type: WheelCacheModel | MetadataCacheModel

_CACHE_MAX_SIZE: int = 100_000  # More than this would be A LOT


def _timer() -> float:
    """
    Gets the current timestamp as a floating-point number.

    This function returns the current time in seconds since the Unix
    epoch as a floating-point number. The precision includes fractions
    of a second.

    Returns:
        float: The current timestamp with fractional seconds precision.
    """
    return datetime.now().timestamp()


def _ttu(_key: str, value: Any, now: float) -> float:
    """
    Calculates the expiration time-to-use (TTU) for a given object based on its
    expiration attribute. If the object does not have an expiration attribute, the
    current time is returned. Supports both `datetime` and numerical expiration
    values.

    Args:
        _key (str): A key identifier (not used directly in this function).
        value (Any): The input object whose expiration is being evaluated.
        now (float): The current time represented as a UNIX timestamp.

    Returns:
        float: The expiration time-to-use timestamp. If no expiration is set on
        the input object, it returns the value of `now`.
    """
    exp = getattr(value, "expiration", None)
    if exp is None:
        return now
    if isinstance(exp, datetime):
        return exp.timestamp()
    return float(exp)


@dataclass(kw_only=True)
class BasePersistedCache(ABC, Generic[K, E, M]):
    """
    Base class for persisted artifact (wheel and metadata) caches.

    This abstract base class provides a structure for a persisted cache, allowing for
    custom implementations of the underlying cache mechanism and handling of stored
    entries. It uses a caching library for efficient retrieval and storage and persists
    the cache data to disk.

    Attributes:
        model_cls (type): The class type of the model used for serialization and
            deserialization of cache data.
        index_path (Path): The file system path where the cache data will be stored.
        fmt (str): The format used for serialization and deserialization. Defaults to "json".
    """
    model_cls: type[M]
    index_path: Path
    fmt: str = "json"

    _cache: Cache = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache = self._create_cache()

    @abstractmethod
    def _cache_key(self, key: K) -> str:
        raise NotImplementedError

    @abstractmethod
    def _create_cache(self) -> Cache:
        """
        Abstract method for creating a cache instance to be implemented by subclasses.

        This method is a placeholder that must be overridden in derived classes. It defines
        a contract for how cache instances should be created. Subclasses implementing this
        method should ensure the proper instantiation and configuration of the `Cache` object.

        Raises:
            NotImplementedError: In subclasses that have not implemented this method.

        Returns:
            Cache: The cache instance created by the subclass implementation.
        """
        raise NotImplementedError

    def load(self) -> None:
        """
        Loads the data from the specified index path and initializes the cache
        with deserialized model entries if the index file exists.

        This method checks for the existence of the index file at the provided
        path. If it exists, the content of the file is deserialized into the
        specified model format. The cache is cleared to ensure it contains only
        the latest entries, and it is then updated with the deserialized model
        entries. If the cache has an expiration mechanism, it will also trigger
        that mechanism.
        """
        if not self.index_path.exists():
            return

        raw = self.index_path.read_text(encoding="utf-8")
        model = self.model_cls.deserialize(raw, fmt=self.fmt)
        self._cache.clear()
        self._cache.update({entry.key: entry for entry in model})

        expire = getattr(self._cache, "expire", None)
        if callable(expire):
            expire()

    def flush(self) -> None:
        """
        Flushes the internal cache and writes the indexed model to a file.

        This method clears the cached data by invoking an expiration function if it
        exists, then creates a model using the cached items, then serializes it to a file.
        """
        expire = getattr(self._cache, "expire", None)
        if callable(expire):
            expire()

        model = self.model_cls(index=dict(self._cache.items()))
        model.to_file(self.index_path, fmt=self.fmt)

    @cachedmethod(attrgetter("_cache"), key=lambda self, key: self._cache_key(key))
    def get(self, key: K) -> E | None:
        """
        Retrieves the value associated with the specified key from the cache.

        The method attempts to retrieve the value corresponding to the given key using
        the internal cache mechanism. If the key exists, the associated value is
        returned; otherwise, None is returned.

        Args:
            key: The key used to retrieve the associated value.

        Returns:
            Optional[E]: The value associated with the provided key if it exists;
            otherwise, None.
        """
        return self._get_entry_value(key)

    @abstractmethod
    def _get_entry_value(self, key: K) -> E | None:
        """
        Abstract method to retrieve the value of an entry identified by the given key. This method
        must be implemented by subclasses to define the mechanism for fetching the corresponding
        value for a specific key from the data source.

        Args:
            key: The key of type K used to identify the associated entry in the underlying data
                 structure.

        Returns:
            Optional[E]: The value of the entry associated with the provided key if found, otherwise
                         None.
        """
        raise NotImplementedError


@dataclass(kw_only=True)
class WheelCache(BasePersistedCache[str, WheelCacheIndexModel, WheelCacheModel]):
    """
    Represents a caching system for wheels with a fixed maximum size and resolution mechanism.

    This class is a specialized implementation of a persisted cache system designed to store
    and manage wheel-related data. It uses a resolver to fetch wheel entries by their URI
    and manages cached entries through an LRU (Least Recently Used) caching policy. The cache
    is initialized with a specified maximum size, which limits the number of entries stored at
    any given time.

    Attributes:
        resolver (WheelResolver): Component responsible for resolving and fetching wheel data
            based on a unique URI.
        maxsize (int): Maximum number of entries the cache can hold. Defaults to 100,000.
    """
    resolver: WheelArtifactResolver
    maxsize: int = _CACHE_MAX_SIZE

    def _cache_key(self, uri: str) -> str:
        return wheel_cache_key(uri=uri)

    def _create_cache(self):
        return LRUCache(maxsize=self.maxsize)

    def _get_entry_value(self, wheel_uri: str) -> WheelCacheIndexModel | None:
        return self.resolver.resolve(uri=wheel_uri)


@dataclass(kw_only=True)
class BaseMetadataCache(BasePersistedCache[WheelKey, MetadataCacheIndexModel, MetadataCacheModel], ABC):
    """
    Manages metadata caching with a limited size and time-to-use eviction policy.

    Provides functionality for resolving metadata associated with a `WheelKey`
    using a `MetadataArtifactResolver`. Implements a caching mechanism to store
    and retrieve metadata efficiently. The cache is backed by a time-limited
    LRU (Least Recently Used) cache.

    Attributes:
        resolver (MetadataArtifactResolver): The resolver used to fetch metadata
            associated with a given `WheelKey`.
        maxsize (int): The maximum number of entries allowed in the cache.
    """
    resolver: MetadataArtifactResolver
    maxsize: int = _CACHE_MAX_SIZE

    @abstractmethod
    def _cache_key(self, key: WheelKey) -> str:
        raise NotImplementedError

    def _create_cache(self):
        return TLRUCache(maxsize=self.maxsize, ttu=_ttu, timer=_timer)

    def _get_entry_value(self, key: WheelKey) -> MetadataCacheIndexModel | None:
        return self.resolver.resolve(wheel_key=key)


@dataclass(kw_only=True)
class Pep658Cache(BaseMetadataCache):
    """
    Represents a PEP 658 metadata cache.

    This class serves as a specific implementation of a metadata cache to
    hold information about downloaded PEP 658 metadata files.
    """

    def _cache_key(self, key: WheelKey) -> str:
        return metadata_cache_key(wheel_key=key)


@dataclass(kw_only=True)
class Pep691Cache(BaseMetadataCache):
    """
    Represents a PEP 691 metadata cache.

    This class serves as a specific implementation of a metadata cache to
    hold information about downloaded PEP 619 metadata files.
    """

    def _cache_key(self, key: WheelKey) -> str:
        return project_cache_key(key)
