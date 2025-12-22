from __future__ import annotations

from abc import ABC
from collections.abc import Mapping, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, Generic

from packaging.utils import canonicalize_name, parse_wheel_filename

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.helper.wheel_tag_utils import choose_wheel_tag
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.artifact_resolution import _wheel_filename_from_uri
from pychub.package.lifecycle.plan.resolution.resolution_config_model import StrategyType
from pychub.package.lifecycle.plan.resolution.resolution_context_vars import current_resolution_context

_EXPIRATION_MINUTES = 1440
E = TypeVar("E", bound=MultiformatModelMixin)  # Cache entry model type


def get_uri_info(uri: str) -> tuple[str, str, str, WheelKey, str | None]:
    filename = _wheel_filename_from_uri(uri)
    name, version, _, tagset = parse_wheel_filename(filename)
    wheel_key = WheelKey(str(name), str(version))
    chosen_tag = choose_wheel_tag(filename=filename, name=str(name), version=str(version))
    return filename, str(name), str(version), wheel_key, chosen_tag


def wheel_cache_key(uri: str) -> str:
    filename, name, version, wheel_key, chosen_tag = get_uri_info(uri)
    if chosen_tag is None:
        raise ValueError(f"Could not choose wheel tag for {wheel_key} from {uri}")
    return f"{canonicalize_name(wheel_key.name)}-{wheel_key.version}-{chosen_tag}"


def metadata_cache_key(wheel_key: WheelKey) -> str:
    try:
        context_tag = str(current_resolution_context.get().tag)
        return f"{canonicalize_name(wheel_key.name)}-{wheel_key.version}-{context_tag}"
    except LookupError:
        raise ValueError("The current resolution context must be set before creating a metadata cache key")


def project_cache_key(wheel_key: WheelKey) -> str:
    return f"{canonicalize_name(wheel_key.name)}"


@dataclass(kw_only=True)
class BaseCacheIndexModel(ABC):
    key: str
    path: Path
    origin_uri: str
    timestamp: datetime
    expiration: datetime

    def to_base_mapping(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": str(self.path),
            "origin_uri": self.origin_uri,
            "timestamp": self.timestamp.isoformat(),
            "expiration": self.expiration.isoformat(),
        }

    @classmethod
    def base_kwargs_from_mapping(cls, mapping: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "key": mapping["key"],
            "path": Path(mapping["path"]),
            "origin_uri": mapping["origin_uri"],
            "timestamp": datetime.fromisoformat(mapping["timestamp"]),
            "expiration": datetime.fromisoformat(mapping["expiration"])
        }


class BaseCacheModel(ABC, Generic[E], MultiformatModelMixin):
    _index: dict[str, E]

    def __init__(self, index: dict[str, E] | None = None):
        self._index = index or {}

    # ---- required hooks (each subclass supplies the entry mapper) ----

    @classmethod
    def _entry_from_mapping(cls, mapping: Mapping[str, Any]) -> E:
        raise NotImplementedError

    @staticmethod
    def _entry_key(entry: E) -> str:
        return str(getattr(entry, "key"))

    # ---- common serialization ----

    def to_mapping(self) -> dict[str, Any]:
        return {
            self._entry_key(entry): entry.to_mapping()  # relies on entry having to_mapping()
            for entry in self._index.values()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> BaseCacheModel[E]:
        index: dict[str, E] = {
            key: cls._entry_from_mapping(entry)
            for key, entry in mapping.items()
        }
        return cls(index=index)

    # ---- common helpers for resolvers ----

    def __iter__(self) -> Iterator[E]:
        return iter(self._index.values())

    def as_dict(self) -> dict[str, E]:
        return self._index

    def get(self, key: str) -> E | None:
        return self._index.get(key)

    def put(self, entry: E) -> None:
        self._index[self._entry_key(entry)] = entry

    def update(self, entries: dict[str, E]) -> None:
        self._index.update(entries)

    def remove(self, key: str) -> E | None:
        return self._index.pop(key, None)

    def to_file(self, path: Path, fmt: str = "json") -> None:
        data = self.serialize(fmt=fmt)
        path.write_text(data, encoding="utf-8")


@dataclass(slots=True)
class MetadataCacheIndexModel(BaseCacheIndexModel, MultiformatModelMixin):
    metadata_type: StrategyType
    hash_algorithm: str = "sha256"
    hash: str = ""
    size_bytes: int = 0

    def to_mapping(self) -> dict[str, Any]:
        base = self.to_base_mapping()
        base.update({
            "metadata_type": self.metadata_type.value
        })
        return base

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> MetadataCacheIndexModel:
        base_kwargs = cls.base_kwargs_from_mapping(mapping)
        mt_raw = mapping["metadata_type"]
        if isinstance(mt_raw, StrategyType):
            metadata_type = mt_raw
        elif isinstance(mt_raw, str):
            try:
                metadata_type = StrategyType(mt_raw)
            except ValueError:
                raise ValueError(f"Unknown strategy type: {mt_raw!r}")
        else:
            raise TypeError(f"metadata_type must be a string or StrategyType, not {type(mt_raw)!r}")

        return cls(**base_kwargs, metadata_type=metadata_type)


@dataclass(slots=True)
class WheelCacheIndexModel(BaseCacheIndexModel, MultiformatModelMixin):
    wheel_key: WheelKey
    compatibility_tag: str
    hash_algorithm: str = "sha256"
    hash: str = ""
    size_bytes: int = 0

    def to_mapping(self) -> dict[str, Any]:
        base = self.to_base_mapping()
        base.update({
            "wheel_key": self.wheel_key.to_mapping(),
            "compatibility_tag": self.compatibility_tag,
            "hash_algorithm": self.hash_algorithm,
            "hash": self.hash,
            "size_bytes": self.size_bytes
        })
        return base

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelCacheIndexModel:
        base_kwargs = cls.base_kwargs_from_mapping(mapping)
        return cls(
            **base_kwargs,
            wheel_key=WheelKey.from_mapping(mapping["wheel_key"]),
            compatibility_tag=mapping["compatibility_tag"],
            hash_algorithm=mapping["hash_algorithm"],
            hash=mapping["hash"],
            size_bytes=mapping["size_bytes"])


class MetadataCacheModel(BaseCacheModel[MetadataCacheIndexModel]):
    @classmethod
    def _entry_from_mapping(cls, mapping: Mapping[str, Any]) -> MetadataCacheIndexModel:
        return MetadataCacheIndexModel.from_mapping(mapping)


class WheelCacheModel(BaseCacheModel[WheelCacheIndexModel]):
    @classmethod
    def _entry_from_mapping(cls, mapping: Mapping[str, Any]) -> WheelCacheIndexModel:
        return WheelCacheIndexModel.from_mapping(mapping)
