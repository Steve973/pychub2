from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator

from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename, NormalizedName, BuildTag
from packaging.version import Version

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin, T
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin

UNORDERED: int = 1_000_000


@dataclass(frozen=True)
class WheelId(MultiformatSerializableMixin):
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

    def to_mapping(self) -> dict[str, str]:
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
class WheelArtifact(MultiformatSerializableMixin, MultiformatDeserializableMixin):
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

    def to_mapping(self) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelArtifact:
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
class WheelCollection(MultiformatSerializableMixin, MultiformatDeserializableMixin):
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

    def to_mapping(self) -> Mapping[str, object]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelCollection:
        return cls(_wheels={WheelArtifact.from_mapping(w) for w in mapping["wheels"]})
