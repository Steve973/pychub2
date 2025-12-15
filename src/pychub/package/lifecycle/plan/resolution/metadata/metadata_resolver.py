from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.domain.compatibility_model import WheelKey, Pep658Metadata, Pep691Metadata
from pychub.package.lifecycle.plan.resolution.caching_model import MetadataCacheModel, MetadataCacheIndexModel
from pychub.package.lifecycle.plan.resolution.metadata.metadata_strategy import \
    BaseMetadataStrategy
from pychub.package.lifecycle.plan.resolution.resolution_config_model import MetadataResolverConfig, StrategyType

INDEX_FILENAME_PEP658 = ".pep658_index.json"
INDEX_FILENAME_PEP691 = ".pep691_index.json"

class MetadataResolver(MultiformatModelMixin):

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
        cache_key = f"pep658:{wheel_key.name}=={wheel_key.version}"
        entry = self._index.get(cache_key)

        if entry and entry.path.exists():
            try:
                return Pep658Metadata.from_mapping(self._load_json(entry.path))
            except Exception:
                pass

        ordered = sorted(self._strategies, key=lambda s: getattr(s, "precedence", 50))
        for strat in ordered:
            if getattr(strat, "strategy_type", None) not in (StrategyType.DEPENDENCY_METADATA, None):
                continue
            meta = strat.get_dependency_metadata(wheel_key)
            if meta is None:
                continue

            # Pep658Metadata is not MultiformatSerializableMixin right now, so write a simple mapping.
            payload = {
                "name": meta.name,
                "version": meta.version,
                "requires_python": meta.requires_python,
                "requires_dist": sorted(meta.requires_dist),
            }
            out_path = self._metadata_dir() / _safe_filename(cache_key)
            self._write_json(out_path, payload)

            now = datetime.now().replace(microsecond=0)
            self._index.put(MetadataCacheIndexModel(
                key=cache_key,
                path=out_path,
                origin_uri=f"strategy:{getattr(strat, 'name', type(strat).__name__)}",
                timestamp=now,
                expiration=now.replace(minute=now.minute + 1440),
                metadata_type=StrategyType.DEPENDENCY_METADATA))
            return meta

        return None

    def resolve_pep691_metadata(self, wheel_key: WheelKey) -> Pep691Metadata | None:
        cache_key = f"pep691:{wheel_key.name}"
        entry = self._index.get(cache_key)

        if entry and entry.path.exists():
            try:
                return Pep691Metadata.from_mapping(self._load_json(entry.path))
            except Exception:
                # Cache is corrupt or schema changed. Fall through and refresh.
                pass

        # Try strategies in precedence order (lowest number wins, matching your other patterns)
        ordered = sorted(self._strategies, key=lambda s: getattr(s, "precedence", 50))
        for strat in ordered:
            if getattr(strat, "strategy_type", None) not in (StrategyType.CANDIDATE_METADATA, None):
                continue
            meta = strat.get_candidate_metadata(wheel_key)
            if meta is None:
                continue

            payload = meta.to_mapping()
            out_path = self._metadata_dir() / _safe_filename(cache_key)
            self._write_json(out_path, payload)

            now = datetime.now().replace(microsecond=0)
            self._index.put(MetadataCacheIndexModel(
                key=cache_key,
                path=out_path,
                origin_uri=f"strategy:{getattr(strat, 'name', type(strat).__name__)}",
                timestamp=now,
                expiration=now.replace(minute=now.minute + 1440),
                metadata_type=StrategyType.CANDIDATE_METADATA))
            return meta

        return None

    def persist_cache_index(self):
        self._index.to_file(path=self._index_path, fmt="json")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "config": self._config.to_mapping()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> MetadataResolver:
        return cls(config=MetadataResolverConfig.from_mapping(mapping["config"]), strategies=[])
