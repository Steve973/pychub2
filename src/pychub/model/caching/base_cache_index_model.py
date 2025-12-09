from __future__ import annotations

from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BaseCacheIndexModel(ABC):
    key: str
    path: Path
    origin_uri: str
    timestamp: datetime

    def __post_init__(self):
        self.timestamp = self.timestamp.replace(microsecond=0)

    def to_base_mapping(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": str(self.path),
            "origin_uri": self.origin_uri,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def base_kwargs_from_mapping(cls, mapping: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "key": mapping["key"],
            "path": Path(mapping["path"]),
            "origin_uri": mapping["origin_uri"],
            "timestamp": datetime.fromisoformat(mapping["timestamp"]),
        }
