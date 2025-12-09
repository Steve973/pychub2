from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import total_ordering
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version, InvalidVersion

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


@total_ordering
@dataclass(slots=True, frozen=True)
class WheelKey(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents a unique identifying key for a wheel (a type of Python package distribution).

    This class encapsulates the information required to uniquely identify and compare a wheel
    using its normalized name and version. It supports serialization, deserialization, and
    various convenience methods to work seamlessly with tuples and comparisons.

    Attributes:
        name (str): The normalized name of the wheel.
        version (str): The version of the wheel, normalized if valid.
    """
    name: str
    version: str

    # --------------------------------------------------------------------- #
    # Normalization
    # --------------------------------------------------------------------- #
    def __post_init__(self) -> None:
        """
        Normalizes and validates the name and version attributes upon initialization.

        This method is invoked automatically after the instance initialization to ensure
        that the `name` attribute follows a canonical format and the `version`
        attribute is validated as per versioning standards. If the version is invalid,
        the method retains the original version string without raising an error.

        Raises:
            InvalidVersion: If the `version` attribute cannot be converted into a valid version string.

        Returns:
            None
        """
        norm_name = canonicalize_name(self.name)
        try:
            norm_version = str(Version(self.version))
        except InvalidVersion:
            # Don't explode on unexpected local versions; keep the original string.
            norm_version = self.version

        object.__setattr__(self, "name", norm_name)
        object.__setattr__(self, "version", norm_version)

    # --------------------------------------------------------------------- #
    # Convenience
    # --------------------------------------------------------------------- #
    def as_tuple(self) -> tuple[str, str]:
        """
        Returns the name and version of an object as a tuple.

        This method retrieves the 'name' and 'version' attributes of the
        object and returns them as a tuple.

        Returns:
            tuple[str, str]: A tuple containing two strings: the name and
            version of the object.
        """
        return self.name, self.version

    def __iter__(self):
        """
        Allows iteration over specified attributes of an object, providing a mechanism to yield
        attribute values sequentially.

        Yields:
            str: The value of the `name` attribute.
            str: The value of the `version` attribute.
        """
        yield self.name
        yield self.version

    def __len__(self) -> int:
        # So code that does `len(wheel_key)` doesn't freak out.
        return 2

    def __getitem__(self, index: int) -> str:
        """
        Gets the value at the specified index. The method supports retrieval of the
        `name` and `version` attributes based on the index provided. If the index
        is 0, it retrieves the `name`. If the index is 1, it retrieves the `version`.
        If the index is outside this range, an IndexError is raised.

        Args:
            index (int): The index indicating which value to retrieve.

        Returns:
            str: The value at the specified index, either `name` or `version`.

        Raises:
            IndexError: If the provided index is not 0 or 1.
        """
        if index == 0:
            return self.name
        if index == 1:
            return self.version
        raise IndexError(index)

    def __str__(self) -> str:
        return f"{self.name}-{self.version}"

    @property
    def requirement_str(self) -> str:
        return f"{self.name}=={self.version}"

    # --------------------------------------------------------------------- #
    # (De)serialization helpers
    # --------------------------------------------------------------------- #
    def to_mapping(self) -> Mapping[str, Any]:
        """
        Converts the attributes of an instance into a mapping.

        The method creates a dictionary containing key-value pairs of the
        instance's attributes defined in the method.

        Returns:
            Mapping[str, Any]: A dictionary with the instance's attribute names
            as keys and their values as corresponding values.
        """
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelKey:
        """
        Creates an instance of `WheelKey` from a mapping of attributes.

        This class method takes a mapping with specific keys to construct and return
        a new instance of the `WheelKey` class. The required keys in the mapping
        include 'name' and 'version'. Additional arguments are accepted but ignored.

        Args:
            mapping (Mapping[str, Any]): The mapping containing the attributes
                required for creating an instance. Must include 'name' and 'version'.
            **_ (Any): Additional arguments that are ignored.

        Returns:
            WheelKey: A new instance of the class with attributes set as specified
                in the mapping.
        """
        return cls(name=mapping["name"], version=mapping["version"])


    # --------------------------------------------------------------------- #
    # ---- comparison logic ----------------------------------------------- #
    # --------------------------------------------------------------------- #

    def __eq__(self, other: object) -> bool:
        """
        Compares the current WheelKey object with another for equality.

        This method overrides the equality operator (==) to compare
        two WheelKey instances by checking their `name` and `version`
        attributes. The comparison is deterministic and based solely
        on these attributes.

        Args:
            other (object): Another object to compare with the current WheelKey
                instance.

        Returns:
            bool: True if `other` is a WheelKey instance and has the same `name`
                and `version` as the current instance. False otherwise.

        Raises:
            NotImplemented: If `other` is not an instance of the WheelKey class.
        """
        if not isinstance(other, WheelKey):
            return NotImplemented
        # equality on normalized strings is deterministic
        return (self.name, self.version) == (other.name, other.version)

    def __lt__(self, other: "WheelKey") -> bool:
        """
        Determines if the current WheelKey instance is less than another.

        This method compares the current instance with another WheelKey instance
        based on their tuple representations, obtained via the `as_tuple` method.
        If the `other` object is not an instance of `WheelKey`, the method returns
        `NotImplemented`.

        Args:
            other (WheelKey): Another WheelKey instance to compare against.

        Returns:
            bool: True if the current instance is less than the `other` instance,
            otherwise False.
        """
        if not isinstance(other, WheelKey):
            return NotImplemented
        return self.as_tuple() < other.as_tuple()


@dataclass(slots=True, frozen=True)
class ResolvedWheelNode(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents minimal compatibility and download information for a resolved
    package (name, version) along with its dependencies.

    The class contains information about:
        - The package's identity (name and version).
        - Dependencies on other packages.
        - Mapping of compatibility tags to download URLs.

    Attributes:
        name (str): The name of the resolved package.
        version (str): The version of the resolved package.
        requires_python (str): The Python version requirement string for the package.
        requires_dist (frozenset of str): A frozenset of package expressions
        dependencies (frozenset of WheelKey): A frozenset of dependencies where
            each WheelKey represents another package (name, version).
        tag_urls (Mapping[str, str] or None): An optional mapping of
            compatibility tags to their associated download URLs (key: compat_tag,
            value: full URL).
    """
    name: str
    version: str
    requires_python: str
    requires_dist: frozenset[str]
    dependencies: frozenset[WheelKey]  # other nodes (name, version)
    tag_urls: Mapping[str, str] | None = None  # compat_tag -> full URL (optional)

    @property
    def key(self) -> WheelKey:
        """
        Gets the `key` property, which represents the unique identifier of the wheel.

        Returns:
            WheelKey: A unique key object comprising the `name` and `version` attributes
            that represents the wheel uniquely.
        """
        return WheelKey(self.name, self.version)

    @property
    def compatible_tags(self) -> list[str]:
        """
        Returns a sorted list of compatible tags.

        The method retrieves the compatible tags, sorts them, and returns them as a
        list. It ensures the returned list is in a consistent order.

        Returns:
            list[str]: A sorted list of compatible tags.
        """
        return sorted(list(self.tag_urls.keys() if self.tag_urls else []))

    def to_mapping(self, *args, **kwargs) -> Mapping[str, Any]:
        """
        Converts the current object to a mapping representation.

        This method creates a dictionary representation of the object's attributes,
        allowing for structured access to its key properties and data. The format of
        the mapping includes information about the name, version, dependencies, and
        tag URLs.

        Returns:
            Mapping[str, Any]: A dictionary containing the mapping representation of
            the current object.

        """
        return {
            "name": self.name,
            "version": self.version,
            "requires_python": self.requires_python,
            "requires_dist": sorted(self.requires_dist),
            "dependencies": [dep.to_mapping for dep in sorted(self.dependencies)],
            "tag_urls": dict(self.tag_urls) if self.tag_urls is not None else None,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolvedWheelNode:
        """
        Create a ResolvedWheelNode instance from a provided mapping.

        This method is used to create an instance of the ResolvedWheelNode
        class by interpreting a dictionary-like mapping. The mapping is
        expected to include keys for the name, version, and optionally
        dependencies, compatible tags, and tag URLs.

        Args:
            mapping (Mapping[str, Any]): The input dictionary-like mapping
                containing data required for initializing the class instance.
                Expected keys include:
                - "name": A string representing the name of the node.
                - "version": A string representing the version of the node.
                - "requires_python": A string representing the Python version.
                - "requires_dist": An optional list of strings representing the
                  required package expressions
                - "dependencies": An optional list of dictionaries, each containing
                  "name" and "version" fields, representing the dependencies of
                  the node.
                - "tag_urls": An optional dictionary mapping tags to their
                  corresponding URLs.

            **_ (Any): Additional arguments that are ignored in this method.

        Returns:
            ResolvedWheelNode: A newly created instance of the ResolvedWheelNode
            class, populated based on the provided mapping.
        """
        deps_iter = mapping.get("dependencies") or []
        deps = frozenset(WheelKey.from_mapping(d) for d in deps_iter)
        requires_dist = mapping.get("requires_dist") or frozenset()
        tag_urls_raw = mapping.get("tag_urls")
        tag_urls = dict(tag_urls_raw) if tag_urls_raw is not None else None
        return cls(
            name=str(mapping["name"]),
            version=str(mapping["version"]),
            requires_python=str(mapping["requires_python"]),
            requires_dist=requires_dist,
            dependencies=deps,
            tag_urls=tag_urls)


@dataclass(slots=True)
class CompatibilityResolution(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Result of resolving a chub's dependency tree against a CompatibilitySpec.

    This class represents the result of resolving a dependency tree for a chub
    package against a provided compatibility specification. It includes the
    starting points of resolution (roots) and the resulting mapping of nodes.
    The nodes detail connections and dependencies within the tree. The purpose
    of this class is to validate whether all root nodes and dependency
    relationships are fully resolved as part of the initialization process.

    Attributes:
        supported_python_band (SpecifierSet): The Python version band supported by this graph.
        _roots (set[WheelKey]): The starting (name, version) nodes representing
            the chub's dependencies as requested by the user.
        nodes (dict[WheelKey, ResolvedWheelNode]): A canonical mapping from
            (name, version) pairs to ResolvedWheelNodes representing resolved
            dependencies and their metadata.
    """
    supported_python_band: SpecifierSet
    _roots: set[WheelKey]
    nodes: dict[WheelKey, ResolvedWheelNode]

    def __post_init__(self) -> None:
        """
        Validates the topology of nodes and dependencies after initialization.

        This method performs two key checks:
        1. Ensures that all root nodes specified in the `_roots` attribute exist within the `nodes` dictionary.
        2. Verifies that all dependencies mentioned in each node's `dependencies` list are present as keys
           in the `nodes` dictionary.

        Raises:
            ValueError: If any root nodes specified in `_roots` are missing from the keys of `nodes`.
            ValueError: If dependencies in any node's `dependencies` list reference missing keys within `nodes`.

        """
        node_keys = set(self.nodes.keys())

        # All roots must exist
        missing_roots = self._roots - node_keys
        if missing_roots:
            raise ValueError(f"Root nodes without metadata: {missing_roots}")

        # All dependencies must exist
        missing_deps: set[WheelKey] = set()
        for node in self.nodes.values():
            for dep_key in node.dependencies:
                if dep_key not in node_keys:
                    missing_deps.add(dep_key)

        if missing_deps:
            raise ValueError(f"Dependencies refer to missing nodes: {missing_deps}")

    @property
    def roots(self) -> list[WheelKey]:
        """
        Gets the roots of the wheel keys.

        The roots represent a sorted list extracted from the internal data structure,
        which contains the foundational wheel keys.

        Returns:
            list[WheelKey]: A sorted list of wheel keys that are considered roots.
        """
        return sorted(list(self._roots))

    def to_mapping(self) -> Mapping[str, Any]:
        """
        Converts the internal representation of the instance into a mapping (dictionary-like
        structure) format.

        This method serializes the object's data into a structured mapping suitable for
        further processing, such as serialization to JSON or other formats.

        Returns:
            Mapping[str, Any]: A dictionary-like structure containing the serialized data of the
            object. It includes the supported Python band, a list of roots with their names
            and versions, and a mapping of nodes with their identifier in the format
            "name==version" to their respective serialized mappings.
        """
        return {
            "supported_python_band": str(self.supported_python_band),
            "roots": [r.to_mapping() for r in self.roots],
            "nodes": {
                kw.requirement_str: node.to_mapping() for kw, node in self.nodes.items()
            },
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> CompatibilityResolution:
        """
        Creates an instance of `CompatibilityResolution` from a mapping data structure.

        This factory method initializes a `CompatibilityResolution` object using data
        provided in a mapping format. It extracts the supported Python version band,
        root elements, and dependency nodes from the mapping and uses them to construct
        the object.

        Args:
            mapping (Mapping[str, Any]): The input mapping containing necessary details
                such as supported Python band, root elements, and dependency nodes.
            **_ (Any): Additional keyword arguments, which are ignored in this method.

        Returns:
            CompatibilityResolution: A newly created instance of `CompatibilityResolution`.
        """
        supported_python_band = SpecifierSet(mapping["supported_python_band"])
        root_items = mapping.get("roots") or []
        roots: set[WheelKey] = {WheelKey(r["name"], r["version"]) for r in root_items}
        raw_nodes = mapping.get("nodes") or {}
        nodes: dict[WheelKey, ResolvedWheelNode] = {}
        for _, node_mapping in raw_nodes.items():
            node = ResolvedWheelNode.from_mapping(node_mapping)
            nodes[node.key] = node
        return cls(supported_python_band=supported_python_band, _roots=roots, nodes=nodes)
