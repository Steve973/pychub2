from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.model.caching.metadata_cache_index_model import MetadataCacheModel
from pychub.model.compatibility.compatibility_resolution_model import WheelKey
from pychub.model.compatibility.pep658_metadata_model import Pep658Metadata
from pychub.model.compatibility.pep691_metadata_model import Pep691Metadata
from pychub.model.compatibility.resolver_config_model import MetadataResolverConfig
from pychub.package.lifecycle.plan.resolution.metadata.metadata_source.base_metadata_strategy import \
    BaseMetadataStrategy

INDEX_FILENAME = ".metadata_index.json"

class MetadataResolver(MultiformatSerializableMixin, MultiformatDeserializableMixin):

    _config: MetadataResolverConfig
    _strategies: Sequence[BaseMetadataStrategy]
    _index: MetadataCacheModel
    _cache_dir: Path
    _index_path: Path

    def __init__(self, config: MetadataResolverConfig, strategies: Sequence[BaseMetadataStrategy]):
        self._config = config
        self._strategies = strategies
        self._index = MetadataCacheModel()
        self._cache_dir = config.local_cache_root \
            if config.project_isolation \
            else config.global_cache_root
        self._index_path = self._cache_dir / INDEX_FILENAME
        if self._index_path.exists():
            loaded = MetadataCacheModel.from_file(self._index_path, "json")
            self._index.update(loaded.as_dict())

    def resolve_pep658_metadata(self, wheel_key: WheelKey) -> Pep658Metadata | None:
        pass

    def resolve_pep691_metadata(self, wheel_key: WheelKey) -> Pep691Metadata | None:
        pass

    def persist_cache_index(self):
        self._index.to_file(path=self._index_path, fmt="json")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "config": self._config.to_mapping()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> MetadataResolver:
        return cls(config=MetadataResolverConfig.from_mapping(mapping["config"]))
