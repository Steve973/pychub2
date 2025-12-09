from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


def _coerce_field(value: Any) -> bool | Mapping[str, str]:
    # If it's a dict, keep it as-is
    if isinstance(value, Mapping):
        return dict(value)
    # Spec says it can be a boolean; anything else → False
    if isinstance(value, bool):
        return value
    return False


@dataclass(slots=True, frozen=True)
class Pep691FileMetadata(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    filename: str
    url: str
    hashes: Mapping[str, str]
    requires_python: str | None
    yanked: bool
    core_metadata: bool | Mapping[str, str]
    data_dist_info_metadata: bool | Mapping[str, str]

    def to_mapping(self, *args, **kwargs) -> Mapping[str, Any]:
        return {
            "filename": self.filename,
            "url": self.url,
            "hashes": dict(self.hashes),
            "requires_python": self.requires_python,
            "yanked": self.yanked,
            "core-metadata": self.core_metadata,
            "data-dist-info-metadata": self.data_dist_info_metadata,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Pep691FileMetadata:
        core_metadata: bool | Mapping[str, str] = _coerce_field(mapping.get("core-metadata"))
        data_dist_info_metadata: bool | Mapping[str, str] = _coerce_field(mapping.get("data-dist-info-metadata"))
        return Pep691FileMetadata(
            filename=mapping["filename"],
            url=mapping["url"],
            hashes=mapping["hashes"],
            requires_python=mapping.get("requires_python"),
            yanked=mapping["yanked"],
            core_metadata=core_metadata,
            data_dist_info_metadata=data_dist_info_metadata)


@dataclass(slots=True, frozen=True)
class Pep691Metadata(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    name: str
    files: Sequence[Pep691FileMetadata]
    last_serial: int | None = None

    def to_mapping(self, *args, **kwargs) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "files": [f.to_mapping() for f in self.files],
            "last_serial": self.last_serial
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Pep691Metadata:
        files = [
            Pep691FileMetadata.from_mapping(f)
            for f in mapping["files"]
            if isinstance(f, Mapping)
        ]
        last_serial = mapping.get("last_serial")
        return Pep691Metadata(
            name=mapping["name"],
            files=files,
            last_serial=int(last_serial) if last_serial is not None else None)
