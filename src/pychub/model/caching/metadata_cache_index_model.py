from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.model.caching.base_cache_index_model import BaseCacheIndexModel
from pychub.model.compatibility.artifact_resolution_strategy_config_model import StrategyType


@dataclass(slots=True)
class MetadataCacheIndexModel(BaseCacheIndexModel, MultiformatSerializableMixin, MultiformatDeserializableMixin):

    metadata_type: StrategyType

    def to_mapping(self) -> dict[str, Any]:
        base = self.to_base_mapping()
        base.update({
            "metadata_type": self.metadata_type.value
        })
        return base

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> MetadataCacheIndexModel:
        base_kwargs = cls.base_kwargs_from_mapping(mapping)
        return cls(
            **base_kwargs,
            metadata_type=StrategyType.value(mapping["metadata_type"]))


class MetadataCacheModel(MultiformatSerializableMixin, MultiformatDeserializableMixin):

    _index: dict[str, MetadataCacheIndexModel]

    def __init__(self, index: dict[str, MetadataCacheIndexModel] | None = None):
        self._index = index or {}

    def to_mapping(self) -> dict[str, Any]:
        return {
            entry.key: entry.to_mapping()
            for entry in self._index.values()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> MetadataCacheModel:
        index: dict[str, MetadataCacheIndexModel] = {
            key: MetadataCacheIndexModel.from_mapping(entry)
            for key, entry in mapping.items()
        }
        return cls(index=index)

    # ---- helpers for resolvers ----

    def __iter__(self):
        """Optional: iterate over entries."""
        return iter(self._index.values())

    def as_dict(self) -> dict[str, MetadataCacheIndexModel]:
        """Return the raw index dict (for bulk use)."""
        return self._index

    def get(self, key: str) -> MetadataCacheIndexModel | None:
        """Safe lookup for a given cache key."""
        return self._index.get(key)

    def put(self, entry: MetadataCacheIndexModel) -> None:
        """Insert or replace an entry, keyed by its .key."""
        self._index[entry.key] = entry

    def update(self, entries: dict[str, MetadataCacheIndexModel]) -> None:
        """Bulk insert or replace entries."""
        self._index.update(entries)

    def remove(self, key: str) -> MetadataCacheIndexModel | None:
        """Drop an entry if it exists."""
        return self._index.pop(key, None)

    def to_file(self, path: Path, fmt: str = "json") -> None:
        data = self.serialize(fmt=fmt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
