from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


@dataclass(slots=True, frozen=True)
class IncludeSpec(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents a specification for including a file, detailing its source path and optional destination path.

    This class is designed to manage the inclusion of files with a specified source and optional destination. It ensures
    that the source file exists and provides functionality to parse and deduplicate inclusion specifications, as well as
    convert them into a dictionary or resolve destination paths.

    Attributes:
        src (Path): The absolute path to the source file to include.
        dest (str | None): The bundle-relative target destination, such as "docs/" or "etc/file.txt". Defaults to None.
    """
    src: Path  # absolute
    dest: str | None = None  # bundle-relative target (e.g., "docs/", "etc/file.txt")

    def __post_init__(self):
        """
        Validates and processes the source file path after initialization.

        Post-initialization method for ensuring that the provided source path
        exists as a file and updates the object's `src` attribute to its absolute
        and resolved path.

        Raises:
            FileNotFoundError: If the resolved path does not point to a valid file.
        """
        resolved = self.src.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Included file not found: {resolved}")
        object.__setattr__(self, "src", resolved)

    @property
    def name(self) -> str:
        return self.dest or self.src.name

    @staticmethod
    def parse(item: str | Mapping[str, Any], *, base_dir: Path = Path.cwd()) -> IncludeSpec:
        """
        Parses an item and constructs an IncludeSpec object.

        This static method takes an item which could either be a string or a mapping,
        and interprets it to resolve the source path and destination. It handles path
        resolution and ensures the source file exists. If the file doesn't exist,
        a FileNotFoundError is raised.

        Args:
            item (str | Mapping[str, Any]): The input item containing the source and
                optional destination information. If it's a string, it should follow
                the format "src_path::dest_path" where `dest_path` is optional.
            base_dir (Path, optional): The base directory for resolving relative
                source paths. Defaults to Path.cwd().

        Returns:
            IncludeSpec: An instance of IncludeSpec containing the parsed source
                and destination.

        Raises:
            FileNotFoundError: If the resolved source file does not exist.
        """
        if isinstance(item, str):
            if "::" in item:
                s, d = item.split("::", 1)
                src_raw, dest = s.strip(), (d.strip() or None)
            else:
                src_raw, dest = item.strip(), None
        else:
            src_raw = str(item["src"]).strip()
            dest = (None if item.get("dest") in (None, "") else str(item["dest"]))
        src = Path(src_raw)
        src = src if src.is_absolute() else (base_dir / src).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Included file not found: {src}")
        return IncludeSpec(src=src, dest=dest)

    @staticmethod
    def dedup(a: list[IncludeSpec], b: list[IncludeSpec]) -> list[IncludeSpec]:
        """
        Deduplicates and merges two lists of IncludeSpec objects, ensuring unique elements based on the combination
        of `src` and `dest` attributes.

        Args:
            a (list[IncludeSpec]): The first list of IncludeSpec objects to deduplicate.
            b (list[IncludeSpec]): The second list of IncludeSpec objects to deduplicate.

        Returns:
            list[IncludeSpec]: A list of IncludeSpec objects with duplicates removed based on their `src` and `dest`
            properties.
        """
        seen: set[tuple[str, str | None]] = set()
        out: list[IncludeSpec] = []
        for spec in [*(a or []), *(b or [])]:
            key = (str(spec.src), spec.dest)
            if key not in seen:
                seen.add(key)
                out.append(spec)
        return out

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the object's source and destination attributes into a dictionary mapping.

        Returns:
            dict[str, Any]: A dictionary containing the mapped "src" and "dest" attributes
            of the object. The "src" key maps to the string representation of the source
            attribute, while the "dest" key maps to the destination value if defined;
            otherwise, it maps to the name of the source attribute.
        """
        return {
            "src": str(self.src),
            "dest": self.dest if self.dest else self.src.name,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> IncludeSpec:
        return cls(src=Path(mapping["src"]), dest=mapping.get("dest", None))

    def __str__(self) -> str:
        return f"{self.src}::{self.dest}" if self.dest else str(self.src)

    def resolved_dest(self, includes_dir: Path) -> Path:
        """
        Resolves the destination path by combining the includes directory with the file name.

        Args:
            includes_dir (Path): The base directory where the file is located.

        Returns:
            Path: The resolved path combining the includes directory and the file name.
        """
        return includes_dir / self.name


@dataclass(slots=True, frozen=True)
class Includes(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents a collection of include specifications, with capabilities for
    serialization to various formats and parsing from TOML-compatible structures.

    This class acts as a container for include specifications and provides methods
    to serialize the data into formats such as TOML inline format, or to convert
    the data into JSON/YAML-compatible mappings. It also supports parsing the
    includes from a sequence of items.

    Attributes:
        _items (list[IncludeSpec]): A list of include specifications stored in the
            instance. These include details about what is being included and how
            it should be processed.
    """
    _items: list[IncludeSpec] = field(default_factory=list)

    def to_toml_inline(self) -> list[str]:
        """
        Converts the internal list of items to a list of strings in TOML inline format.

        The method iterates over the collection of items and converts each
        item to its string representation. This is useful for serializing
        the objects into a format compatible with TOML's inline list syntax.

        Returns:
            list[str]: A list of string representations of the items.
        """
        return [str(i) for i in self._items]

    def to_mapping(self) -> dict[str, Any]:
        """
        Returns a list of mappings derived from the items in the current object. Each
        item is converted to a dictionary representation using its `to_mapping` method.
        The result is suitable for usage in JSON or YAML formats.

        Returns:
            list[dict[str, Any]]: A list of dictionary representations for the
            items in the current object.
        """
        # JSON/YAML-friendly (fully explicit)
        return {
            "items": [i.to_mapping() for i in self._items]
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Includes:
        return cls(
            _items=[IncludeSpec(i) for i in mapping.get("items", [])])

    @property
    def paths(self) -> list[Path]:
        return [i.src for i in self._items]

    def resolved_dests(self, includes_dir: Path) -> list[Path]:
        return [i.resolved_dest(includes_dir) for i in self._items]

    @property
    def items(self):
        return self._items
