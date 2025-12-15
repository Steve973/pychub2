from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from operator import attrgetter
from pathlib import Path
from typing import Generic, TypeVar
from typing import Optional

from cachetools import Cache, LRUCache, TTLCache
from cachetools import cachedmethod

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.caching_model import WheelCacheIndexModel, WheelCacheModel, \
    MetadataCacheIndexModel, MetadataCacheModel
from pychub.package.lifecycle.plan.resolution.metadata.metadata_resolver import MetadataResolver
from pychub.package.lifecycle.plan.resolution.wheels.wheel_resolver import WheelResolver

K = TypeVar("K")  # key type: e.g., str | WheelKey
E = TypeVar("E")  # entry type: WheelCacheIndexModel | MetadataCacheIndexModel
M = TypeVar("M", bound=MultiformatModelMixin)  # model type: WheelCacheModel | MetadataCacheModel

_CACHE_MAX_SIZE: int = 100_000  # More than this would be A LOT
_DEFAULT_TTL_SECONDS: int = 86_400  # 24 hours


@dataclass(kw_only=True)
class BasePersistedCache(ABC, Generic[K, E, M]):
    """Base class for persisted artifact (wheel and metadata) caches.

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
        Loads and initializes the cache from a serialized model if the index path exists.

        This method reads a serialized representation of the model stored at the
        `index_path`, deserializes it using the specified format, and populates the
        cache with the entries from the deserialized model. If the `index_path` does
        not exist, the method returns without modifying the cache or performing any
        operations.
        """
        if not self.index_path.exists():
            return

        raw = self.index_path.read_text(encoding="utf-8")
        model = self.model_cls.deserialize(raw, fmt=self.fmt)
        self._cache.clear()
        self._cache.update({entry.key: entry for entry in model})

    def flush(self) -> None:
        """
        Writes the current contents of the cache to a file in the specified format.

        This method serializes the cached items by creating an instance of the
        provided model class and writing the resulting data to the file at the
        specified path. The serialization format is determined by the given
        format string.
        """
        model = self.model_cls(index=dict(self._cache.items()))
        model.to_file(self.index_path, fmt=self.fmt)

    @cachedmethod(attrgetter("_cache"), key=lambda self, key: key)
    def get(self, key: K) -> Optional[E]:
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
    def _get_entry_value(self, key: K) -> Optional[E]:
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
    resolver: WheelResolver
    maxsize: int = _CACHE_MAX_SIZE

    def _create_cache(self):
        return LRUCache(maxsize=self.maxsize)

    def _get_entry_value(self, wheel_uri: str) -> Optional[WheelCacheIndexModel]:
        return self.resolver.get_wheel_by_uri(wheel_uri)


@dataclass(kw_only=True)
class Pep658Cache(BasePersistedCache[WheelKey, MetadataCacheIndexModel, MetadataCacheModel]):
    """
    Represents a persisted cache for PEP 658 metadata with time-to-live functionality.

    This class is designed to manage and store metadata related to PEP 658 in a
    cache that has a specified maximum size and time-to-live for its entries.
    It integrates a metadata resolver for fetching the required information if
    not found in the cache.

    Attributes:
        resolver (MetadataResolver): Resolver instance for retrieving PEP 658 metadata.
        maxsize (int): Maximum number of entries in the cache. Default is 100,000.
        ttl_seconds (int): Time-to-live for cache entries, in seconds. Default is 86,400.
    """
    resolver: MetadataResolver
    maxsize: int = _CACHE_MAX_SIZE
    ttl_seconds: int = _DEFAULT_TTL_SECONDS

    def _create_cache(self):
        return TTLCache(maxsize=self.maxsize, ttl=self.ttl_seconds)

    def _get_entry_value(self, key: WheelKey) -> Optional[MetadataCacheIndexModel]:
        return self.resolver.resolve_pep658_metadata(key)


@dataclass(kw_only=True)
class Pep691Cache(BasePersistedCache[WheelKey, MetadataCacheIndexModel, MetadataCacheModel]):
    """
    Represents a cache implementation for PEP 691 metadata resolution.

    This class is a specialized cache that uses a time-to-live (TTL) mechanism to
    temporarily store resolved metadata for PEP 691 compatibility. The cache leverages
    a TTL-based storage strategy to maintain a bounded size and ensure that metadata
    does not persist beyond its usefulness. Intended for use with PEP 691-compliant
    metadata resolution workflows.

    Attributes:
        resolver (MetadataResolver): The metadata resolver responsible for resolving
            PEP 691 metadata.
        maxsize (int): Maximum number of items the cache can hold before evicting
            the least recently used items. Defaults to 100,000.
        ttl_seconds (int): Time-to-live for cache entries, in seconds. Entries are
            automatically invalidated and removed after this duration. Defaults to
            86,400 seconds (1 day).
    """
    resolver: MetadataResolver
    maxsize: int = _CACHE_MAX_SIZE
    ttl_seconds: int = _DEFAULT_TTL_SECONDS

    def _create_cache(self):
        return TTLCache(maxsize=self.maxsize, ttl=self.ttl_seconds)

    def _get_entry_value(self, key: WheelKey) -> Optional[MetadataCacheIndexModel]:
        return self.resolver.resolve_pep691_metadata(key)
