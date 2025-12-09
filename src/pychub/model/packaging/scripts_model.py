from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


class ScriptType(str, Enum):
    """
    Represents the types of scripts in a system.

    This Enum class is used to classify scripts based on when they are executed
    relative to a specific operation, such as before or after. The `ScriptType`
    class inherits from `str` and `Enum` to provide string-like behaviors while
    offering enumeration semantics.

    Attributes:
        PRE: Indicates a script that is executed before an operation.
        POST: Indicates a script that is executed after an operation.
    """
    PRE = "pre"
    POST = "post"


@dataclass(slots=True, frozen=True)
class ScriptSpec(MultiformatSerializableMixin):
    """
    Represents the specification for a script, including its source path and type.

    This class serves as a structured representation of a script, encapsulating
    the source path and its script type. It provides methods to resolve paths,
    construct instances from a mapping, and convert the instance back to a
    dictionary mapping.

    Attributes:
        src (Path): The source file path of the script, resolved to an absolute
            path.
        script_type (ScriptType): Specifies the type of the script.
    """
    src: Path
    script_type: ScriptType

    def __post_init__(self):
        """
        Performs post-initialization checks and processing for the class instance.

        Ensures the provided `src` path is resolved to a file and updates the
        attribute with its resolved path. If the path does not point to a file,
        a FileNotFoundError is raised.

        Raises:
            FileNotFoundError: If the resolved `src` path is not a valid file.
        """
        resolved = self.src.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Script not found: {resolved}")
        object.__setattr__(self, "src", resolved)

    @property
    def name(self) -> str:
        return self.src.name

    @staticmethod
    def from_mapping(m: Mapping[str, Any] | None) -> "ScriptSpec":
        """
        Constructs a ScriptSpec instance from a mapping of attributes.

        This static method takes a mapping that should contain the keys `src` and
        `script_type` to initialize and return a `ScriptSpec` instance. The `src`
        should map to a valid file path and `script_type` should correspond to a
        valid `ScriptType`. If the mapping is empty, an error is raised.

        Args:
            m (Mapping[str, Any] | None): A mapping containing the attributes
                for constructing a ScriptSpec. It must include the `src` key
                with a valid file path and the `script_type` key with a valid
                ScriptType value.

        Returns:
            ScriptSpec: A new instance of ScriptSpec initialized with the data
                from the mapping.

        Raises:
            ValueError: If the provided mapping is empty or invalid.
        """
        if not m:
            raise ValueError("Empty script mapping")
        src = Path(m["src"])
        script_type = ScriptType(m["script_type"])
        return ScriptSpec(src, script_type)

    def to_mapping(self) -> dict[str, str]:
        """
        Converts the object properties to a dictionary mapping of strings.

        This method transforms specific attributes of an object into a
        dictionary where the keys are fixed strings and the values are
        corresponding object properties, converted to strings. It ensures that
        the output is suitable for standardized representation or serialization.

        Returns:
            dict[str, str]: A dictionary containing the 'src' attribute as a
            string and the 'script_type' attribute as its string representation.
        """
        return {
            "src": str(self.src),
            "script_type": self.script_type.value
        }


@dataclass(slots=True, frozen=True)
class Scripts(MultiformatSerializableMixin):
    """
    Represents a collection of script specifications and provides utility
    methods for manipulation and serialization.

    The Scripts class is designed to hold and process a collection of `ScriptSpec`
    objects. It supports operations such as deduplication, merging multiple
    `Scripts` objects, and serialization to and from mappings. This class ensures
    all contained script specifications are properly categorized and managed.

    Attributes:
        _items (list[ScriptSpec]): The list of all script specifications contained
            in this instance.
    """
    _items: list[ScriptSpec] = field(default_factory=list)

    @staticmethod
    def dedup(items: list[ScriptSpec]) -> list[ScriptSpec]:
        """
        Removes duplicate script specifications based on their source and script type.

        Processes a list of ScriptSpec objects, identifies duplicates by combining their
        source and script type into a unique key, and returns a list containing only
        unique script specifications.

        Args:
            items (list[ScriptSpec]): The list of ScriptSpec objects to process.

        Returns:
            list[ScriptSpec]: A filtered list of unique ScriptSpec objects based on source
            and script type.
        """
        seen: set[tuple[str, ScriptType]] = set()
        out: list[ScriptSpec] = []
        for s in items:
            key = (str(s.src), s.script_type)
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    @classmethod
    def merged(cls, *scripts_objs: "Scripts") -> "Scripts":
        """
        Merges multiple Scripts objects into a single Scripts object, ensuring all
        items are deduplicated.

        Args:
            *scripts_objs (Scripts): One or more Scripts objects to merge.

        Returns:
            Scripts: A new Scripts object containing the combined items from all
            provided Scripts objects, with duplicates removed.
        """
        all_items: list[ScriptSpec] = []
        for s in scripts_objs:
            if s:
                all_items.extend(s.items)
        return cls(_items=cls.dedup(all_items))

    @staticmethod
    def from_mapping(m: Mapping[str, list[dict[str, str]]] | None) -> "Scripts":
        """
        Creates and returns an instance of the Scripts class based on the given mapping.

        This static method takes an optional mapping that associates string keys to lists
        of dictionaries. If the mapping is not provided or is empty, an empty Scripts
        instance is returned. Otherwise, it processes the mapping and creates a Scripts
        instance using ScriptSpec definitions for each ScriptType.

        Args:
            m (Mapping[str, list[dict[str, str]]] | None): A dictionary-like object mapping
                ScriptType values (as strings) to lists of dictionaries, or None.

        Returns:
            Scripts: A new Scripts instance initialized with ScriptSpec objects derived
                from the provided mapping.
        """
        if not m:
            return Scripts()
        return Scripts([
            ScriptSpec.from_mapping(x)
            for t in ScriptType
            for x in (m.get(t.value) or [])
        ])

    def to_mapping(self) -> dict[str, list[dict[str, str]]]:
        """
        Converts the object to a dictionary mapping.

        The method transforms the current object, including its `pre` and `post`
        attributes, into a dictionary representation. Each item in the `pre`
        and `post` lists is processed by calling its `to_mapping` method.

        Returns:
            dict[str, list[dict[str, str]]]: A dictionary with two keys, "pre" and
            "post". The values associated with these keys are lists of dictionaries
            resulting from calling `to_mapping` on each item in the `pre` and `post`
            lists, respectively.
        """
        return {
            "pre": [x.to_mapping() for x in self.pre],
            "post": [x.to_mapping() for x in self.post]
        }

    @property
    def pre(self) -> list[ScriptSpec]:
        return [i for i in self._items if i.script_type == ScriptType.PRE]

    @property
    def post(self) -> list[ScriptSpec]:
        return [i for i in self._items if i.script_type == ScriptType.POST]

    @property
    def items(self):
        return self._items
