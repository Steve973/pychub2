from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.model.caching.base_cache_index_model import BaseCacheIndexModel
from pychub.model.compatibility.compatibility_resolution_model import WheelKey


def create_key(wheel_key: WheelKey, compatibility_tag: str) -> str:
    return f"{wheel_key.name}-{wheel_key.version}-{compatibility_tag}"


@dataclass(slots=True)
class WheelCacheIndexModel(BaseCacheIndexModel, MultiformatSerializableMixin, MultiformatDeserializableMixin):

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


class WheelCacheModel(MultiformatSerializableMixin, MultiformatDeserializableMixin):

    _index: dict[str, WheelCacheIndexModel]

    def __init__(self, index: dict[str, WheelCacheIndexModel] | None = None):
        self._index = index or {}

    def to_mapping(self) -> dict[str, Any]:
        return {
            entry.key: entry.to_mapping()
            for entry in self._index.values()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelCacheModel:
        index: dict[str, WheelCacheIndexModel] = {
            key: WheelCacheIndexModel.from_mapping(entry)
            for key, entry in mapping.items()
        }
        return cls(index=index)

    # ---- helpers for resolvers ----

    def __iter__(self):
        """Optional: iterate over entries."""
        return iter(self._index.values())

    def as_dict(self) -> dict[str, WheelCacheIndexModel]:
        """Return the raw index dict (for bulk use)."""
        return self._index

    def get(self, key: str) -> WheelCacheIndexModel | None:
        """Safe lookup for a given cache key."""
        return self._index.get(key)

    def put(self, entry: WheelCacheIndexModel) -> None:
        """Insert or replace an entry, keyed by its .key."""
        self._index[entry.key] = entry

    def update(self, entries: dict[str, WheelCacheIndexModel]) -> None:
        """Bulk insert or replace entries."""
        self._index.update(entries)

    def remove(self, key: str) -> WheelCacheIndexModel | None:
        """Drop an entry if it exists."""
        return self._index.pop(key, None)

    def to_file(self, path: Path, fmt: str = "json") -> None:
        data = self.serialize(fmt=fmt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
