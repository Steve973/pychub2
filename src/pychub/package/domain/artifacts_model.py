from __future__ import annotations

import hashlib
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.parser import Parser
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Iterator

from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename, NormalizedName, BuildTag
from packaging.version import Version
from typing_extensions import Self

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin

UNORDERED: int = 1_000_000


@dataclass(frozen=True)
class WheelId(MultiformatModelMixin):
    """
    Represents an identifier for a wheel distribution package.

    This class encapsulates essential information about a wheel distribution package,
    including its normalized name, version, and tag triple, and provides functionalities
    for serializing these attributes into a dictionary for external usage.

    Attributes:
        name (str): The normalized name of the distribution.
        version (str): The normalized version of the distribution.
        tag_triple (str): A string representing the tag triple, typically in the format
            "interpreter-abi-platform" (e.g., "cp312-manylinux_2_28_x86_64").
    """
    name: str  # normalized dist name
    version: str  # normalized version
    tag_triple: str  # like "cp312-manylinux_2_28_x86_64"

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the current object properties into a dictionary mapping.

        The method creates and returns a dictionary containing selected attributes
        with their corresponding values. This is useful for scenarios where
        the object needs to be represented as a dictionary.

        Returns:
            dict[str, str]: A dictionary mapping specific object attributes to their values.
        """
        return {
            "name": self.name,
            "version": self.version,
            "tag_triple": self.tag_triple,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        return cls(
            mapping["name"],
            mapping["version"],
            mapping["tag_triple"])

    def __str__(self) -> str:
        return f"{self.name}-{self.version}-{self.tag_triple}"


class WheelSourceType(str, Enum):
    """
    Defines the WheelSourceType enumeration.

    The enumeration represents different sources from which a wheel (Python package)
    can originate. It provides clear categorization for the source of a wheel,
    either being from the local filesystem, found as a dependency of another local
    wheel, downloaded from PyPI, or locally built as an artifact.

    Attributes:
        PATH (str): Represents a wheel supplied from the local filesystem.
        PROJECT (str): Represents a wheel found as a dependency of another local wheel.
        PYPI (str): Represents a wheel downloaded from PyPI.
        BUILT (str): Represents a locally built wheel artifact.
    """
    PATH = "PATH"  # Supplied from the local filesystem
    PROJECT = "PROJECT"  # Found as a dependency of another local wheel
    PYPI = "PYPI"  # Downloaded from PyPI
    BUILT = "BUILT"  # Locally built artifact


class WheelRoleType(str, Enum):
    """Enumeration of roles a wheel can play in a Python build.

    Represents different contexts or purposes for wheels in a Python
    build process. The values indicate whether the wheel is the main
    focus, a dependency, or an intentionally included extra.

    Attributes:
        PRIMARY (str): The main subject of the build process.
        DEPENDENCY (str): A wheel that is required by the primary wheel.
        INCLUDED (str): An additional wheel intentionally bundled.
    """
    PRIMARY = "PRIMARY"  # The main subject of the build
    DEPENDENCY = "DEPENDENCY"  # Required by the primary wheel
    INCLUDED = "INCLUDED"  # Extra wheel intentionally bundled


@dataclass
class WheelArtifact(MultiformatModelMixin):
    """
    Represents a wheel artifact, including its metadata, dependencies, and other relevant details.

    This class encapsulates information about a Python wheel package including its name, version,
    tags, dependencies, source, and various attributes needed for dependency management or artifact
    serialization.

    Attributes:
        path (Path): The file path to the wheel artifact.
        name (str): The name of the wheel package.
        version (Version): The version of the wheel package.
        tags (set[Tag]): The compatibility tags for the wheel package.
        requires (list[str]): A list of package-level dependencies specified in the artifact.
        dependencies (list[WheelArtifact]): A list of dependent wheel artifacts.
        source (WheelSourceType | None): Indicates the source of the wheel artifact (e.g., file, URL).
        role (WheelRoleType | None): Denotes the role of the wheel (primary or dependency).
        order (int): The priority order assigned to the wheel in dependency resolution.
        hash (str | None): The computed hash of the artifact for integrity checks.
        metadata (dict[str, Any]): A dictionary containing additional metadata such as author, license, etc.
    """
    path: Path
    name: str
    version: Version
    tags: set[Tag]
    requires: list[str] = field(default_factory=list)
    dependencies: list["WheelArtifact"] = field(default_factory=list)
    source: WheelSourceType | None = None
    role: WheelRoleType | None = None
    order: int = UNORDERED
    hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # -------------------------------------------------------------------------
    # Factories
    # -------------------------------------------------------------------------

    @classmethod
    def from_path(
            cls,
            path: Path,
            *,
            is_primary: bool = False,
            source: WheelSourceType | str = WheelSourceType.PATH,
            order: int = UNORDERED) -> WheelArtifact:
        """
        Creates an instance of the WheelArtifact class from a specified wheel file path. This method:
            1. validates the given wheel path
            2. parses its filename to extract necessary metadata (such as name, version, and tags)
            3. computes the file's hash for reproducibility
            4. retrieves package requirements and additional metadata
            5. returns a populated instance of the class.

        Args:
            path (Path): File path pointing to the wheel file. Must be a valid existing file.
            is_primary (bool, optional): Indicates whether the artifact should be treated as the primary wheel in
                the dependency graph. Defaults to False.
            source (WheelSourceType | str, optional): Indicates the source of the wheel, such as a local path or
                other source types. Defaults to WheelSourceType.PATH.
            order (int, optional): The order/priority of the wheel artifact in dependency resolution. Defaults
                to UNORDERED.

        Returns:
            WheelArtifact: A new instance of the WheelArtifact class populated with the extracted and computed details.

        Raises:
            FileNotFoundError: If the given wheel file path does not exist or is not a file.
            ValueError: If the provided wheel filename is invalid and cannot be parsed correctly.
        """
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Wheel not found: {path}")

        # Parse filename for name/version/tags
        try:
            name, version, build, tags_set = parse_wheel_filename(path.name)
        except Exception as e:
            raise ValueError(f"Invalid wheel filename: {path.name} ({e})")

        tags = set(tags_set)

        # Compute hash for reproducibility
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        wheel_hash = sha.hexdigest()

        # Parse METADATA for requirements and extra info
        requires, metadata = cls._parse_metadata(path)

        return cls(
            path=path,
            name=name.replace("_", "-").lower(),
            version=version,
            tags=tags,
            requires=requires,
            source=WheelSourceType(source) if not isinstance(source, WheelSourceType) else source,
            role=WheelRoleType.PRIMARY if is_primary else WheelRoleType.DEPENDENCY,
            order=order,
            hash=wheel_hash,
            metadata=metadata)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_metadata(path: Path) -> tuple[list[str], dict[str, Any]]:
        """
        Parses the metadata and requirements from a ZIP archive containing package information.

        This method extracts a "METADATA" file from the given archive (if present), processes its
        contents, and retrieves dependencies listed in the "Requires-Dist" fields as well as other
        metadata such as the author, summary, homepage, and license.

        Args:
            path (Path): The path to the ZIP archive containing the package metadata.

        Returns:
            tuple[list[str], dict[str, Any]]: A tuple where the first element is a list of strings representing
                the parsed requirements (dependencies), and the second element is a dictionary containing
                the metadata with specific keys: 'author', 'summary', 'home_page', and 'license'.
        """
        requires: list[str] = []
        meta: dict[str, Any] = {}

        with zipfile.ZipFile(path) as zf:
            meta_file = next((f for f in zf.namelist() if f.endswith("METADATA")), None)
            if not meta_file:
                return requires, meta
            with zf.open(meta_file) as fh:
                for line in fh:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded.startswith("Requires-Dist:"):
                        req = decoded.split(":", 1)[1].strip()
                        try:
                            Requirement(req)  # validate
                            requires.append(req)
                        except Exception:
                            continue
                    elif ":" in decoded:
                        key, val = decoded.split(":", 1)
                        if key in {"Author", "Summary", "Home-page", "License"}:
                            meta[key.lower().replace("-", "_")] = val.strip()
        return requires, meta

    # -------------------------------------------------------------------------
    # Properties / views
    # -------------------------------------------------------------------------

    @property
    def is_universal(self) -> bool:
        """
        Indicates whether the object is considered universal.

        This property evaluates the `tags` attribute and determines whether the object
        meets the conditions to be classified as a universal package. A universal
        package is one where its tag has the interpreter set to "py3", ABI set to
        "none", and platform set to "any". If the `tags` attribute is empty, the method
        returns False.

        Returns:
            bool: True if the object fulfills the universal package conditions,
            otherwise False.
        """
        if not self.tags:
            return False
        return any(t.interpreter == "py3" and t.abi == "none" and t.platform == "any" for t in self.tags)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the object data to a dictionary representation.

        This method generates a dictionary mapping from the object's attributes.
        It ensures that proper type transformations are applied where necessary
        (e.g., converting paths to strings or sets to lists) to provide a
        consistent, serializable representation.

        Returns:
            dict[str, Any]: A dictionary with the object's attributes as keys
            and their values appropriately converted for serialization.
        """
        return {
            "path": str(self.path),
            "name": self.name,
            "version": self.version,
            "tags": list(self.tags),
            "hash": self.hash,
            "is_universal": self.is_universal,
            "requires": self.requires,
            "source": self.source,
            "role": self.role,
            "order": self.order,
            "metadata": self.metadata,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        path_str = mapping["path"]
        tag_name: NormalizedName
        tag_ver: Version
        build_tag: BuildTag
        tags_iter: frozenset[Tag]
        tag_name, tag_ver, build_tag, tags_iter = parse_wheel_filename(path_str)
        return cls(
            path=Path(mapping["path"]),
            name=str(tag_name),
            version=tag_ver,
            tags=set(tags_iter),
            hash=mapping["hash"],
            requires=mapping["requires"],
            source=mapping["source"],
            role=mapping["role"],
            order=mapping["order"],
            metadata=mapping["metadata"])

    # -------------------------------------------------------------------------
    # Methods for set/dict operations
    # -------------------------------------------------------------------------

    def __hash__(self):
        # Unique by file name only
        return hash(self.path.name)

    def __eq__(self, other):
        if isinstance(other, WheelArtifact):
            return self.path.name == other.path.name
        return NotImplemented


@dataclass
class WheelCollection(MultiformatModelMixin):
    """
    Represents a collection of wheel artifacts with features for categorization, filtering,
    and compatibility checks.

    The WheelCollection class facilitates management of a set of WheelArtifact objects,
    providing utilities for categorizing wheels by roles such as primary, dependency,
    or included wheels. It also allows filtering based on origin, compatibility checks,
    and provides serialization features for outputting mapping representations. The
    collection adheres to Python's set behavior for uniqueness.

    Attributes:
        _wheels (set[WheelArtifact]): A set containing the wheel artifacts in the collection.
    """
    _wheels: set[WheelArtifact] = field(default_factory=set)

    # ------- Properties -------

    @property
    def primary(self) -> list[WheelArtifact]:
        return [w for w in self._wheels if w.role == WheelRoleType.PRIMARY]

    @property
    def dependencies(self) -> list[WheelArtifact]:
        return [w for w in self._wheels if w.role == WheelRoleType.DEPENDENCY]

    @property
    def included(self) -> list[WheelArtifact]:
        return [w for w in self._wheels if w.role == WheelRoleType.INCLUDED]

    @property
    def sources(self) -> set:
        return {w.source for w in self._wheels if w.source is not None}

    @property
    def ordered(self):
        return sorted(
            self._wheels,
            key=lambda w: (
                UNORDERED if w.order is None
                             or w.order < 0
                else w.order,
                w.name))

    @property
    def all_tag_sets(self) -> list[set[Tag]]:
        return [w.tags for w in self._wheels]

    @property
    def supported_combos(self) -> set[Tag]:
        tag_sets = self.all_tag_sets
        if not tag_sets:
            return set()
        return set.intersection(*tag_sets)

    @property
    def is_fully_universal(self) -> bool:
        return all(w.is_universal for w in self._wheels)

    @property
    def supported_target_strings(self) -> list[str]:
        combos = self.supported_combos
        return sorted(WheelCollection._tag_to_str(t) for t in combos)

    # ------- Static / Class Methods -------

    @staticmethod
    def _tag_to_str(tag: Tag) -> str:
        """
        Converts a Tag object into its string representation.

        The method takes a Tag object and combines its internal properties (interpreter,
        abi, and platform) into a single string separated by hyphens. This string
        represents the tag in a human-readable format.

        Args:
            tag: A Tag object representing the interpreter, ABI, and platform
                combination.

        Returns:
            str: A string representation of the Tag object in the format
            "interpreter-abi-platform".
        """
        return f"{tag.interpreter}-{tag.abi}-{tag.platform}"

    @staticmethod
    def _is_universal(tag: Tag) -> bool:
        """
        Determines if a given tag is universal.

        A universal tag is defined as one with an interpreter of "py3", an
        ABI of "none", and a platform of "any".

        Args:
            tag (Tag): The tag to evaluate.

        Returns:
            bool: True if the tag is universal, otherwise False.
        """
        return tag.interpreter == "py3" and tag.abi == "none" and tag.platform == "any"

    @classmethod
    def from_iterable(cls, artifacts: Iterable[WheelArtifact]) -> WheelCollection:
        """
        Creates a WheelCollection instance from an iterable of WheelArtifact objects.

        This class method takes an iterable containing WheelArtifact objects and
        creates a WheelCollection instance containing these artifacts. It ensures
        that the collection of artifacts is stored as a set to guarantee uniqueness.

        Args:
            artifacts (Iterable[WheelArtifact]): An iterable of WheelArtifact objects
                to include in the WheelCollection.

        Returns:
            WheelCollection: A new instance containing the provided artifacts.
        """
        return cls(set(artifacts))

    # ------- Utility Methods -------

    def __contains__(self, artifact: WheelArtifact) -> bool:
        return artifact in self._wheels

    def __len__(self) -> int:
        return len(self._wheels)

    def __iter__(self) -> Iterator[WheelArtifact]:
        return iter(self._wheels)

    def add(self, artifact: WheelArtifact) -> None:
        """
        Adds a WheelArtifact into the collection of wheels.

        This method is responsible for adding an object of type WheelArtifact into the
        internal set that manages the collection of wheels. The method does not allow
        duplicate entries due to the nature of sets in Python.

        Args:
            artifact (WheelArtifact): The artifact to be added to the internal set.

        Returns:
            None
        """
        self._wheels.add(artifact)

    def extend(self, artifacts: Iterable[WheelArtifact]) -> None:
        """
        Extends the collection of wheel artifacts by adding the provided iterable of WheelArtifact.

        Args:
            artifacts (Iterable[WheelArtifact]): The iterable containing WheelArtifact objects to be added
                to the internal collection.
        """
        self._wheels.update(artifacts)

    def by_source(self, source: WheelSourceType) -> list[WheelArtifact]:
        """
        Filters and retrieves wheel artifacts based on their source type.

        This function scans through the collection of wheel artifacts and returns a
        list of wheel artifacts matching the specified source type.

        Args:
            source (WheelSourceType): The source type to filter the wheel artifacts.

        Returns:
            list[WheelArtifact]: A list of wheel artifacts that match the specified
            source type.
        """
        return [w for w in self._wheels if w.source == source]

    def find(self, name: str, version: Version | None = None) -> list[WheelArtifact]:
        """
        Finds all wheel artifacts matching the provided name and optionally a specific
        version.

        This method iterates through a collection of wheel artifacts and filters them
        based on the provided name and, if specified, the version.

        Args:
            name (str): The name of the wheel artifact to search for.
            version (Version | None): The version of the wheel artifact to match. If None,
                all versions that match the name will be returned.

        Returns:
            list[WheelArtifact]: A list of wheel artifacts matching the given
                name and optional version.
        """
        return [
            w for w in self._wheels
            if w.name == name and (version is None or w.version == version)
        ]

    def validate_buildable(self) -> None:
        """
        Validates if the object is buildable based on supported compatibility combinations.

        This method checks whether there are supported combinations of compatibility
        targets. If none are found, a ValueError is raised.

        Raises:
            ValueError: If no supported compatibility target exists across wheel artifacts.
        """
        if not self.supported_combos:
            raise ValueError("No common compatibility target across wheel artifacts.")

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the object's attributes to a dictionary representation for serialization.

        Returns:
            Mapping[str, object]: A dictionary representation of the object. The keys in
            the dictionary represent attribute names, and the values are their respective
            mappings. All wheels are converted to their respective dictionary mappings and
            grouped under the "wheels" key.
        """
        return {
            "wheels": [w.to_mapping() for w in self._wheels],
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        return cls(_wheels={WheelArtifact.from_mapping(w) for w in mapping["wheels"]})


# --------------------------------------------------------------------------
# Selectors (case-insensitive). Use "A|B" to mean "prefer A, else B".
# Keys are canonical names you want in YAML; values are header selectors.
# Mark keys that are multivalued in MULTI_FIELDS.
# --------------------------------------------------------------------------
# Selector = (alternatives, multi?)
# Each alternative may be an OR-chain like "License|License-Expression"
Selector = tuple[tuple[str, ...], bool]

METADATA_SELECTORS: dict[str, Selector] = {
    "name": (("Name",), False),
    "version": (("Version",), False),
    "summary": (("Summary",), False),
    "license": (("License|License-Expression",), False),
    "requires_python": (("Requires-Python",), False),
    "requires_dist": (("Requires-Dist",), True),
    "provides_extra": (("Provides-Extra",), True),
    "home_page": (("Home-page",), False),
}

WHEEL_SELECTORS: dict[str, Selector] = {
    "wheel_version": (("Wheel-Version",), False),
    "generator": (("Generator",), False),
    "root_is_purelib": (("Root-Is-Purelib",), False),
    "tag": (("Tag",), True),
}

_EXTR_RE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


# --------------------------------------------------------------------------

@dataclass(slots=True)
class SourceInfo(MultiformatModelMixin):
    """Represents information about the source of an item.

    This class is used to store and serialize details about a source, such as its
    type, URL, the index URL, and when it was downloaded. It supports storing
    sources of various types including local, index, version control system (VCS),
    and others.

    Attributes:
        type (str): The type of the source. Common values include "local", "index",
            "vcs", or "other".
        url (str | None): The URL of the source.
        index_url (str | None): The index URL associated with the source, if any.
        downloaded_at (str | None): The timestamp (in ISO8601 format) of when the
            source was downloaded.
    """
    type: str = "local"  # local | index | vcs | other
    url: str | None = None
    index_url: str | None = None
    downloaded_at: str | None = None  # ISO8601

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the object properties to a dictionary mapping suitable for serialization.

        Returns:
            dict[str, Any]: A dictionary representation of the object containing its
            properties. The properties include 'type', and optionally 'url',
            'index_url', and 'downloaded_at' if they are set.
        """
        m: dict[str, Any] = {"type": self.type}
        if self.url:
            m["url"] = self.url
        if self.index_url:
            m["index_url"] = self.index_url
        if self.downloaded_at:
            m["downloaded_at"] = self.downloaded_at
        return m

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        return cls(**mapping)


@dataclass(slots=True, frozen=True)
class ExtrasInfo(MultiformatModelMixin):
    """
    Represents a container for managing extras and their dependencies.

    The `ExtrasInfo` class serves as a structured data container for managing
    metadata about provided extras and associated requirements. It provides
    methods to create instances from various formats (metadata, mappings, lists)
    and utilities to access or transform the stored extras data.

    Attributes:
        extras (dict[str, list[str]]): A mapping of extras to their associated
            dependencies. Each key represents an extra, and its value is a list
            of string requirements related to that extra.
    """
    extras: dict[str, list[str]]

    # ---------- constructors ----------
    @staticmethod
    def from_metadata(meta: Mapping[str, Any]) -> ExtrasInfo:
        """
        Creates an ExtrasInfo instance from metadata.

        This static method takes a metadata dictionary and converts it into an
        ExtrasInfo instance by extracting information regarding provided extras
        and required distributions.

        Args:
            meta (Mapping[str, Any]): A dictionary containing metadata. Expect keys
                'provides_extra' and 'requires_dist' within the metadata to generate
                lists of provided extras and required distributions.

        Returns:
            ExtrasInfo: An instance of ExtrasInfo containing the extracted
            'provides' and 'requires' lists.
        """
        provides = _meta_list(meta.get("provides_extra"))
        requires = _meta_list(meta.get("requires_dist"))

        return ExtrasInfo.from_lists(provides, requires)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Constructs an instance of ExtrasInfo using a mapping of extras.

        The method takes a mapping where keys are strings and values are any type.
        It converts each value in the mapping to a list and initializes the
        extras attribute with this transformed data.

        Args:
            mapping (Mapping[str, Any]): A mapping where keys are strings and values
                of any type, representing the raw data for extras.

            **_ (Any): Variable-length keyword arguments that are unused.

        Returns:
            ExtrasInfo: An instance of the ExtrasInfo class initialized with the
            transformed extras data.
        """
        return cls(extras={k: list(v) for k, v in (mapping or {}).items()})

    @staticmethod
    def from_lists(provides_extra: Iterable[str] | None,
                   requires_dist: Iterable[str] | None) -> ExtrasInfo:
        """
        Creates an ExtrasInfo object from provided and required extras information.

        This method processes `provides_extra` and `requires_dist` inputs to construct
        a mapping of extras and their corresponding dependencies. Declared extras are
        ensured to exist in the resulting dataset, even if no dependencies are associated
        with them.

        Args:
            provides_extra (Iterable[str] | None): A collection of declared extras.
            requires_dist (Iterable[str] | None): A collection of requirements specifying
                dependencies and their corresponding extras.

        Returns:
            ExtrasInfo: An object representing the grouping of extras and their
            associated dependencies.
        """
        declared = {s.strip() for s in _meta_list(provides_extra) if s and s.strip()}
        reqs = [s.strip() for s in _meta_list(requires_dist) if s and s.strip()]

        grouped: dict[str, list[str]] = {}
        buckets: dict[str, list[str]] = defaultdict(list)

        for r in reqs:
            spec, marker = _split_req_marker(r)
            name = _extract_extra_name(marker)
            if name is None:
                # no `extra == '...':` -> base dep; ignore for the "extras" mapping
                # (if you want base deps later, track them in a separate field)
                continue
            _append_dedup(buckets[name], spec)

        # Ensure all declared extras exist (even if empty)
        for name in declared:
            buckets.setdefault(name, [])

        # Freeze into a plain dict (preserve insertion order)
        for k, v in buckets.items():
            grouped[k] = list(v)

        return ExtrasInfo(extras=grouped)

    # ---------- accessors / utils ----------
    def get(self, name: str) -> list[str]:
        """
        Retrieves the value associated with a given name as a list of strings. If the
        name does not exist in the collection, returns an empty list.

        Args:
            name (str): The key whose associated value needs to be retrieved.

        Returns:
            list[str]: A list containing the strings associated with the key, or an
            empty list if the key is not found.
        """
        return list(self.extras.get(name, []))

    def names(self) -> list[str]:
        """
        Retrieves a list of names from the keys of the `extras` dictionary.

        This method accesses the `extras` attribute, extracts its dictionary keys, and
        returns them as a list of strings.

        Returns:
            list[str]: A list of strings representing the keys from the `extras`
            dictionary.
        """
        return list(self.extras.keys())

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the extras attribute into a dictionary where each key maps to a list of strings.

        This method processes the `extras` attribute, which is assumed to be a dictionary-like
        object where the values are collections. Each collection in the values is converted
        to a list of strings, and the entire structure is returned as a new dictionary.

        Returns:
            dict[str, list[str]]: A dictionary where each key from `extras` corresponds
            to a list of strings derived from its value.
        """
        return {k: list(v) for k, v in self.extras.items()}

    def __len__(self) -> int:
        return len(self.extras)

    def __bool__(self) -> bool:
        return bool(self.extras)


@dataclass(slots=True)
class WheelInfo(MultiformatModelMixin):
    """
    Represents metadata and information about a Python wheel file.

    This class encapsulates the attributes of a Python wheel, such as its name, version,
    size, cryptographic hash, tags, and associated metadata. It provides methods to
    convert the object into a dictionary representation, create an instance from a
    mapping of attributes, and build an instance by parsing the contents of a wheel file.
    The class organizes and normalizes data obtained from wheel files, making it a
    convenient structure for handling Python wheel metadata.

    Attributes:
        filename (str): The name of the wheel package file.
        name (str): The name of the associated Python package.
        version (str): The version of the associated Python package.
        size (int): The size of the wheel file in bytes.
        sha256 (str): SHA256 hash of the wheel file for integrity verification.
        tags (list[str]): A list of tags indicating supported platforms and environments.
        requires_python (str | None): Specifies the Python version requirement, if any.
        deps (list[str]): A list of dependencies required by the package, represented as filenames.
        extras (ExtrasInfo): Metadata related to extras declared in the wheel, such as optional features.
        source (SourceInfo | None): Metadata indicating the source or origin of the wheel, if provided.
        meta (dict[str, Any]): Normalized attributes from the wheel's METADATA file.
        wheel (dict[str, Any]): Normalized attributes from the wheel's WHEEL metadata file.
    """
    filename: str
    name: str
    version: str
    size: int
    sha256: str
    tags: list[str] = field(default_factory=list)  # from WHEEL Tag
    requires_python: str | None = None
    deps: list[str] = field(default_factory=list)  # immediate deps (filenames)
    extras: ExtrasInfo = field(default_factory=lambda: ExtrasInfo(extras={}))
    source: SourceInfo | None = None
    meta: dict[str, Any] = field(default_factory=dict)  # normalized METADATA
    wheel: dict[str, Any] = field(default_factory=dict)  # normalized WHEEL

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the current object properties to a dictionary representation.

        The method aggregates the primary attributes of the object as well as additional
        optional attributes into a dictionary. It ensures that any optional attributes
        that are `None` are excluded from the final dictionary. The result is useful for
        serializing the object into a JSON-compatible format or for further processing.

        Returns:
            dict[str, Any]: A dictionary containing the serialized representation of the
            object's attributes. Primary attributes like `name`, `version`, `sha256`,
            `size`, and `tags` are always present, while optional attributes such as
            `requires_python`, `deps`, `extras`, `source`, `meta`, or `wheel` are included
            only if their values are not `None`.
        """
        out = {
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "size": self.size,
            "tags": list(self.tags)
        }
        if self.filename:
            out.update({"filename": self.filename})
        ext = {
            "requires_python": self.requires_python,
            "deps": self.deps and list(self.deps),
            "extras": self.extras and self.extras.to_mapping(),
            "source": self.source and self.source.to_mapping(),
            "meta": self.meta and dict(self.meta),
            "wheel": self.wheel and dict(self.wheel)
        }
        out.update({name: value for name, value in ext.items() if value})
        return out

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Create a WheelInfo instance from a given mapping.

        This method generates a `WheelInfo` object by mapping values from a provided
        dictionary to the attributes of the `WheelInfo` instance. It handles parsing
        and defaults for absent keys in the mapping.

        Args:
            mapping (Mapping[str, Any]): A dictionary containing metadata and information
                to populate the attributes of the `WheelInfo` object.

        Returns:
            WheelInfo: A fully populated instance of the `WheelInfo` class.
        """
        return cls(
            filename=str(mapping.get("filename", "")),
            name=str(mapping.get("name", "")),
            version=str(mapping.get("version", "")),
            size=int(mapping.get("size", 0)),
            sha256=str(mapping.get("sha256", "")),
            tags=[str(x) for x in (mapping.get("tags") or [])],
            requires_python=(str(mapping["requires_python"])
                             if mapping.get("requires_python") else None),
            deps=[str(x) for x in (mapping.get("deps") or [])],
            extras=ExtrasInfo.from_mapping(mapping.get("extras") or {}),
            source=SourceInfo(**mapping["source"]) if mapping.get("source") else None,
            meta=dict(mapping.get("meta") or {}),
            wheel=dict(mapping.get("wheel") or {}))

    @staticmethod
    def build_from_wheel(
            path: str | Path,
            *,
            deps: Iterable[str] | None = None,
            source: SourceInfo | None = None) -> WheelInfo:
        """
        Build WheelInfo from a given wheel file path, optionally resolving dependencies and source metadata.

        This static method processes the provided wheel file to extract relevant metadata from the
        METADATA and WHEEL headers. The method normalizes extracted fields, applying selectors,
        to ensure accurate metadata parsing and organization. The method raises an exception if
        critical fields like Name or Version are missing in the wheel metadata.

        Args:
            path (str | Path): Path to the wheel file to process.
            deps (Iterable[str] | None): Optional iterable containing dependency specifications as strings.
            source (SourceInfo | None): Optional source metadata related to the wheel's origin or source.

        Returns:
            WheelInfo: An object containing metadata and relevant information parsed from the wheel file.
        """
        p = Path(path)
        size = p.stat().st_size
        sha256 = _sha256_file(p)

        meta_hdrs = _read_headers_from_wheel(p, ".dist-info/METADATA")
        wheel_hdrs = _read_headers_from_wheel(p, ".dist-info/WHEEL")

        # Normalize using OR-able selectors (with multi flags baked in)
        meta = _select_fields(meta_hdrs, METADATA_SELECTORS)
        wheel = _select_fields(wheel_hdrs, WHEEL_SELECTORS)

        # Prefer selector results; hard-require Name/Version from METADATA
        name_val = meta.pop("name", None) or _select_one(meta_hdrs, ("Name",))
        version_val = meta.pop("version", None) or _select_one(meta_hdrs, ("Version",))

        if not name_val or not version_val:
            raise ValueError(f"{p.name}: METADATA missing Name/Version")

        name = str(name_val)
        version = str(version_val)

        tag_obj = wheel.get("tag")
        if isinstance(tag_obj, list):
            tags = [str(x) for x in tag_obj]
        elif tag_obj is not None:
            tags = [str(tag_obj)]
        else:
            tags = []
        rp = meta.pop("requires_python", None)
        requires_python = str(rp) if rp is not None else None
        extras = ExtrasInfo.from_metadata(meta)

        return WheelInfo(
            filename=p.name,
            name=name,
            version=version,
            size=size,
            sha256=sha256,
            tags=tags,
            requires_python=requires_python,
            deps=[str(x) for x in (deps or ())],
            extras=extras,
            source=source,
            meta=meta,
            wheel={k: v for k, v in wheel.items() if k != "tag"})


# ------------------------------- helpers ----------------------------------

def _sha256_file(path: Path, *, chunk: int = 1_048_576) -> str:
    """
    Computes the SHA-256 hash of the contents of a file.

    This function computes the SHA-256 hash of a file by reading its contents in
    chunks to avoid memory overuse with large files. The hash is returned as a
    hexadecimal string.

    Args:
        path (Path): The path to the file whose hash is to be computed.
        chunk (int, optional): The size of each chunk to read from the file in
            bytes. Defaults to 1_048_576 (1 MB).

    Returns:
        str: The computed SHA-256 hash in hexadecimal format.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _read_headers_from_wheel(
        path: Path, suffix: str) -> Mapping[str, list[str]]:
    """
    Reads and extracts headers from the specified file inside a wheel archive,
    based on a provided suffix. If the file matching the suffix does not exist,
    an empty dictionary is returned.

    Args:
        path (Path): The path to the wheel file from which headers need to be
            extracted.
        suffix (str): The suffix to identify the specific file within the wheel
            archive.

    Returns:
        Mapping[str, list[str]]: A dictionary where keys are header names and values
            are lists of header values extracted from the file. If no matching file
            is found, the dictionary will be empty.
    """
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.endswith(suffix)), None)
        if not name:
            return {}
        text = z.read(name).decode("utf-8", errors="replace")
    msg = Parser().parsestr(text)
    out: dict[str, list[str]] = {}
    for k in (msg.keys() or []):
        vals = msg.get_all(k) or []
        out.setdefault(k, []).extend(vals)
    return out


def _select_fields(
        headers: Mapping[str, list[str]],
        selectors: Mapping[str, Selector], ) -> dict[str, object]:
    """
    Select and process fields based on the provided headers and selectors.

    This function takes input headers and mapped selectors to extract and
    transform specific fields based on the specified mapping rules. It supports
    both single-value and multi-value extraction as defined in the selectors.

    Args:
        headers (Mapping[str, list[str]]): A dictionary mapping header names to
            their respective list of string values. The keys are case-insensitive.
        selectors (Mapping[str, Selector]): A mapping of canonical field names to
            selectors. Each selector contains alternative header names and a
            boolean indicating whether multiple values are allowed for that field.

    Returns:
        dict[str, object]: A dictionary where keys are canonical field names and
            values are the selected data. The values can either be a string (for
            single-value fields) or a list of strings (for multi-value fields).
    """
    ci: dict[str, list[str]] = {k.lower(): v for k, v in headers.items()}
    out: dict[str, object] = {}
    for canon, (alts, multi) in selectors.items():
        chosen: list[str] | None = None
        for sel in alts:
            for alt in (s.strip() for s in sel.split("|")):
                vals = ci.get(alt.lower())
                if vals:
                    chosen = [str(x) for x in vals]
                    break
            if chosen:
                break
        if chosen is None:
            continue
        out[canon] = chosen if multi else chosen[0]
    return out


def _select_one(headers: Mapping[str, list[str]], alts: tuple[str, ...]) -> str | None:
    """
    Selects the first matching value from the headers dictionary based on
    the specified alternatives and their case-insensitive match.

    The function searches through the provided `alts` (alternatives) to find
    a match in the headers dictionary. Each alternative can include multiple
    options separated by a pipe (`|`) character. The function returns the
    first matching value if found, or None otherwise.

    Args:
        headers (Mapping[str, list[str]]): A dictionary where keys are header
            names (case-insensitive) and values are lists of header values.
        alts (tuple[str, ...]): A tuple of alternate header names to search for,
            where each option may contain multiple alternatives separated by '|'.

    Returns:
        str | None: The first matching header value from the dictionary, or
            None if no match is found.
    """
    ci: dict[str, list[str]] = {k.lower(): v for k, v in headers.items()}
    for sel in alts:
        for alt in (s.strip() for s in sel.split("|")):
            vals = ci.get(alt.lower())
            if vals:
                return str(vals[0])
    return None


def _meta_list(v: Any) -> list[str]:
    """
    Converts the input value into a list of strings.

    This function processes the input parameter `v` and ensures it is
    transformed into a list of string representations. If the input is None,
    it returns an empty list. If the input is a list, it converts each item
    in the list to its string representation. Otherwise, it converts the
    non-list input into a single-item list containing its string
    representation.

    Args:
        v (Any): The input value to be converted into a list of strings. It
            can be None, a list, or any other type.

    Returns:
        list[str]: A list of string representations of the input value.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


def meta_str(v: Any) -> str | None:
    """
    Converts a given value to its string representation or returns None if the value is None.

    This function takes an input value and converts it to a string using Python's `str()`
    function. If the input value is `None`, the function returns `None`.

    Args:
        v (Any): The input value to be converted to a string. It can be of any type.

    Returns:
        str | None: The string representation of the input value, or None if the input value
        is None.
    """
    return None if v is None else str(v)


def _split_req_marker(req: str) -> tuple[str, str | None]:
    """
    Splits a requirement string into its specification and an optional marker.

    A requirement string may include a marker separated from the main
    specification by a semicolon. This function splits the string into its
    respective parts, stripping any leading or trailing whitespace from both.

    Args:
        req (str): The requirement string to be split, which may contain a
            specification and an optional marker separated by a semicolon.

    Returns:
        tuple[str, str | None]: A tuple where the first element is the
        main specification of the requirement as a string, and the second
        element is the marker as a string if present, or None if the
        requirement does not include a marker.
    """
    if ";" in req:
        spec, marker = req.split(";", 1)
        return spec.strip(), marker.strip()
    return req.strip(), None


def _extract_extra_name(marker: str | None) -> str | None:
    """
    Extracts the extra name from a given marker string.

    The function searches for a substring within the provided marker that matches
    a specific pattern defined by `_EXTR_RE`. If a match is found, the corresponding
    group is returned; otherwise, None is returned. If the marker itself is None
    or empty, the function returns None.

    Args:
        marker (str | None): The string containing the marker from which the extra
            name is to be extracted. Can be None.

    Returns:
        str | None: The extracted extra name if present, or None if no match is
        found or if the input string is None.
    """
    if not marker:
        return None
    m = _EXTR_RE.search(marker)
    return m.group(1) if m else None


def _append_dedup(bucket: list[str], item: str) -> None:
    """
    Adds an item to the bucket if it is not already present.

    This function checks whether an item is already present in the provided
    list. If the item is not found, it appends the item to the list. The
    operation is performed in-place.

    Args:
        bucket (list[str]): The list to which the item may be appended.
        item (str): The item to check and possibly append to the list.

    Returns:
        None
    """
    if item not in bucket:
        bucket.append(item)


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
class ScriptSpec(MultiformatModelMixin):
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

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Constructs a ScriptSpec instance from a mapping of attributes.

        This static method takes a mapping that should contain the keys `src` and
        `script_type` to initialize and return a `ScriptSpec` instance. The `src`
        should map to a valid file path and `script_type` should correspond to a
        valid `ScriptType`. If the mapping is empty, an error is raised.

        Args:
            mapping (Mapping[str, Any] | None): A mapping containing the attributes
                for constructing a ScriptSpec. It must include the `src` key
                with a valid file path and the `script_type` key with a valid
                ScriptType value.

        Returns:
            ScriptSpec: A new instance of ScriptSpec initialized with the data
                from the mapping.

        Raises:
            ValueError: If the provided mapping is empty or invalid.
        """
        if not mapping:
            raise ValueError("Empty script mapping")
        src = Path(mapping["src"])
        script_type = ScriptType(mapping["script_type"])
        return cls(src, script_type)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
class Scripts(MultiformatModelMixin):
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

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Creates and returns an instance of the Scripts class based on the given mapping.

        This static method takes an optional mapping that associates string keys to lists
        of dictionaries. If the mapping is not provided or is empty, an empty Scripts
        instance is returned. Otherwise, it processes the mapping and creates a Scripts
        instance using ScriptSpec definitions for each ScriptType.

        Args:
            mapping (Mapping[str, list[dict[str, str]]] | None): A dictionary-like object mapping
                ScriptType values (as strings) to lists of dictionaries, or None.

        Returns:
            Scripts: A new Scripts instance initialized with ScriptSpec objects derived
                from the provided mapping.
        """
        if not mapping:
            return cls()
        return cls([
            ScriptSpec.from_mapping(x)
            for t in ScriptType
            for x in (mapping.get(t.value) or [])
        ])

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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


@dataclass(slots=True, frozen=True)
class IncludeSpec(MultiformatModelMixin):
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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
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
class Includes(MultiformatModelMixin):
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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
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
