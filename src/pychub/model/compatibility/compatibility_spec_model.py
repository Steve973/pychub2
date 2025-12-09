from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, parse_tag
from packaging.version import Version

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.helper.toml_utils import dump_toml_to_str
from pychub.package.context_vars import current_build_plan

_MIN_PATTERN = re.compile(r"""
    ^\s*
    (?P<ver>\d+\.\d+)      # X.Y
    \s*$
""", re.VERBOSE)

_MAX_PATTERN = re.compile(r"""
    ^\s*
    (?P<op><=|<)?          # optional upper bound operator: < or <=
    \s*
    (?P<ver>\d+\.\d+)      # X.Y
    \s*$
""", re.VERBOSE)


def _normalize_str_list(value: Any) -> list[str]:
    """
    Normalizes the input value into a list of strings.

    This function ensures the provided input is converted into a list of strings. If the input is
    already a list or tuple, each element is converted to a string. If the input is a single string,
    it is returned inside a single-element list. If the input is None, an empty list is returned.
    Any other type of input is converted to a string and encapsulated in a list.

    Args:
        value (Any): The input value to normalize. Can be of any type.

    Returns:
        list[str]: A list containing string representations of the input value.
    """
    match value:
        case None:
            return []
        case str():
            return [value]
        case list() | tuple():
            return [str(v) for v in value]
        case _:
            return [str(value)]


@dataclass(slots=True)
class PythonVersionsSpec(MultiformatSerializableMixin):
    """
    Represents a specification for Python version constraints and custom selections.

    The PythonVersionsSpec class is used to define constraints and explicit selections
    for Python versions. It supports defining a minimum version, a maximum version,
    specific values, types (as a categorized list), and exclusions. This class can
    serialize and deserialize its data to and from mappings to support flexible
    interoperability.

    Attributes:
        min (str): The minimum Python version constraint.
        max (str): The maximum Python version constraint.
        types (list[str]): A categorized list of Python version types.
        accept_universal (bool): Indicates whether universal interpreter values are accepted. Defaults to True.
        specific (list[str]): Specific Python versions explicitly included.
        specific_only (bool): Indicates whether only specific versions are allowed. Defaults to False.
        excludes (list[str]): Python versions to be excluded.
    """

    min: str
    max: str
    types: list[str] = field(default_factory=list)
    accept_universal: bool = True
    specific: list[str] = field(default_factory=list)
    specific_only: bool = False
    excludes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        Validates and normalizes the 'min' and 'max' Python version attributes, ensuring
        they conform to the required syntax. The method also ensures the appropriate
        default value for 'max' is synthesized if it is not provided.

        Raises:
            ValueError: If 'min' or 'max' do not adhere to the required version syntax.
        """
        if self.min is None:
            raise ValueError("Python 'min' version must be specified")

        self.min = self.min.strip()

        # 1) Validate min and normalize it to X.Y format
        m_min = _MIN_PATTERN.match(self.min)
        if not m_min:
            raise ValueError(f"Invalid Python 'min' version syntax: {self.min!r}")

        # 2) If max is missing, synthesize the default: "<(min_major+1).0"
        if self.max is None:
            min_ver = Version(m_min.group("ver"))
            next_major = min_ver.major + 1
            self.max = f"<{next_major}.0"

        # 3) If max is present, validate its syntax
        m_max = _MAX_PATTERN.match(self.max)
        if not m_max:
            raise ValueError(f"Invalid Python 'max' version syntax: {self.max!r}")
        max_op = m_max.group("op") or "<="
        max_ver = m_max.group("ver")
        self.max = f"{max_op}{max_ver}"

    def filter_versions(self, candidates: Iterable[str]) -> list[str]:
        """
        Filters a list of version strings based on a defined minimum and maximum version.

        This method evaluates a list of version strings, comparing each version to the
        instance's minimum and maximum version constraints. Versions that do not meet
        the specified range are excluded from the resulting list. The results are
        returned in sorted order.

        Args:
            candidates (Iterable[str]): A list or iterable of version strings to be filtered.

        Returns:
            list[str]: A sorted list of version strings that fall within the defined range.
        """
        min_v = Version(self.min)

        m_max = _MAX_PATTERN.match(self.max)
        if m_max is None:
            raise ValueError(f"Invalid Python 'max' version syntax: {self.max!r}")
        op = m_max.group("op")
        max_ver_str = m_max.group("ver")
        max_v = Version(max_ver_str)

        max_inclusive = (op is None) or (op == "<=")

        result: list[str] = []
        for can in candidates:
            v = Version(can)
            if v < min_v:
                continue

            if ((max_inclusive and v > max_v) or
                    (not max_inclusive and v >= max_v)):
                continue

            result.append(str(v))

        return sorted(result, key=Version)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PythonVersionsSpec:
        """
        Constructs a PythonVersionsSpec object from a mapping of data.

        This method allows the creation of a PythonVersionsSpec object by
        extracting and normalizing values from a provided mapping. If the mapping
        is not provided or is None, default empty values are applied.

        Args:
            data (Mapping[str, Any] | None): A dictionary-like object containing
                data to populate the PythonVersionsSpec attributes. May include
                the keys "min", "max", "types", "specific", and "excludes". If not
                provided, default empty values are used.

        Returns:
            PythonVersionsSpec: An instance of PythonVersionsSpec initialized with
            the provided mapping values.
        """
        if data is None:
            raise ValueError("Mapping data must be provided to construct a PythonVersionsSpec")
        return cls(
            min=str(data.get("min")),
            max=str(data.get("max")),
            types=_normalize_str_list(data.get("types")),
            accept_universal=bool(data.get("accept_universal", True)),
            specific=_normalize_str_list(data.get("specific")),
            specific_only=bool(data.get("specific_only", False)),
            excludes=_normalize_str_list(data.get("excludes")))

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the attributes of the object into a dictionary mapping.

        This method generates a dictionary representation of the object's
        attributes, excluding those that are None or empty. It ensures that all
        included attributes are converted into the appropriate format, such as
        lists for iterable attributes.

        Returns:
            dict[str, Any]: A dictionary containing the object's attributes as
            key-value pairs. Only non-empty and non-None attributes are included.
        """
        result: dict[str, Any] = {}
        if self.min is not None:
            result["min"] = self.min
        if self.max is not None:
            result["max"] = self.max
        if self.types:
            result["types"] = list(self.types)
        if self.accept_universal:
            result["accept_universal"] = bool(self.accept_universal)
        if self.specific:
            result["specific"] = list(self.specific)
        if self.specific_only:
            result["specific_only"] = bool(self.specific_only)
        if self.excludes:
            result["excludes"] = list(self.excludes)
        return result

    @property
    def specifier_set(self):
        """
        Gets the specifier set that represents the range defined by `min` and `max` attributes.

        Returns:
            SpecifierSet: A SpecifierSet instance representing the range specified by
            `min` and `max`.
        """
        return SpecifierSet(f"{self.min},{self.max}")


@dataclass(slots=True)
class AbiValuesSpec(MultiformatSerializableMixin):
    """
    Represents the specification for AbiValues configuration.

    This class mirrors configuration details for the [AbiValues] table, typically used
    in TOML files. It provides a structured way to manage options related to debugging,
    stability, specific inclusion criteria, and exclusions for ABI values. The values
    can be serialized or deserialized via mappings for flexible usage.

    Attributes:
        include_debug (bool): Indicates whether debugging information is included. Defaults
            to False if not specified.
        include_stable (bool): Indicates whether stable ABI values are included. Defaults
            to False if not specified.
        specific (list[str]): Specific items included in the configuration, represented as
            a list of strings.
        specific_only (bool): Indicates whether only specific items are allowed. Defaults to False.
        excludes (list[str]): Items explicitly excluded from the configuration, represented
            as a list of strings.
    """

    include_debug: bool = False
    include_stable: bool = False
    specific: list[str] = field(default_factory=list)
    specific_only: bool = False
    excludes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> AbiValuesSpec:
        """
        Creates an instance of the class by mapping given data to its attributes.

        This method is a factory class method that constructs an instance of the class by
        mapping the provided dictionary to the requisite attributes of the class. If no
        mapping data is supplied, default values will be used. The mapping involves
        normalization of specific string lists for certain attributes.

        Args:
            data (Mapping[str, Any] | None): Input mapping data containing keys and raw
                values for the attributes. If None, defaults will be used to create the instance.

        Returns:
            AbiValuesSpec: A new instance of AbiValuesSpec initialized with the provided
                or default data.
        """
        data = data or {}
        return cls(
            include_debug=bool(data.get("include_debug", False)),
            include_stable=bool(data.get("include_stable", False)),
            specific=_normalize_str_list(data.get("specific")),
            specific_only=bool(data.get("specific_only", False)),
            excludes=_normalize_str_list(data.get("excludes")))

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the object's attributes into a dictionary representation.

        The method generates a dictionary containing specific attributes of the
        object, including information about optional configurations and lists
        of included or excluded items.

        Returns:
            dict[str, Any]: A dictionary representation of the object's attributes.
        """
        result: dict[str, Any] = {
            "include_debug": bool(self.include_debug),
            "include_stable": bool(self.include_stable),
        }
        if self.specific:
            result["specific"] = list(self.specific)
        if self.specific_only:
            result["specific_only"] = bool(self.specific_only)
        if self.excludes:
            result["excludes"] = list(self.excludes)
        return result


@dataclass(slots=True)
class PlatformFamilySpec(MultiformatSerializableMixin):
    """
    Represents specifications for a platform family, defining minimum and
    maximum parameters.

    This class is used to define and manipulate platform family specifications.
    It includes methods for serializing and deserializing the attributes to and
    from mappings. The `PlatformFamilySpec` class ensures that only attributes
    that are set (not None) will be included in dictionary representations.

    Attributes:
        min (str | None): Minimum value of the platform family specification.
        max (str | None): Maximum value of the platform family specification.
    """

    min: str | None = None
    max: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PlatformFamilySpec:
        data = data or {}
        return cls(
            min=data.get("min"),
            max=data.get("max"))

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the object attributes to a dictionary representation.

        This method creates a dictionary representation of the object by
        including attributes that are not None. It is mainly designed to
        serialize attributes `min` and `max` into a dictionary.

        Returns:
            dict[str, Any]: A dictionary containing the `min` and `max`
            attributes of the object if they are not None.
        """
        result: dict[str, Any] = {}
        if self.min is not None:
            result["min"] = self.min
        if self.max is not None:
            result["max"] = self.max
        return result


@dataclass(slots=True)
class PlatformOSSpec(MultiformatSerializableMixin):
    """
    Represents the specifications and configurations for an operating system platform.

    This dataclass is used to define and manipulate operating system specifications, including
    architectures, specific attributes, exclusions, and platform family details. Instances of
    this class organize such data in a structured way, allowing for serialization and deserialization
    to and from different data formats.

    Attributes:
        arches (list[str]): List of supported CPU architectures for the platform.
        specific (list[str]): List of specific attributes or tags associated with the platform.
        specific_only (bool): Indicates whether only specific attributes are allowed. Defaults to False.
        excludes (list[str]): List of exclusions or unsupported specifications for the platform.
        families (dict[str, PlatformFamilySpec]): Dictionary of platform family specifications,
            with keys representing family names and values being instances of PlatformFamilySpec.
    """

    arches: list[str] = field(default_factory=list)
    specific: list[str] = field(default_factory=list)
    specific_only: bool = False
    excludes: list[str] = field(default_factory=list)
    families: dict[str, PlatformFamilySpec] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PlatformOSSpec:
        """
        Creates an instance of PlatformOSSpec from a mapping dictionary.

        This class method processes the provided data mapping, normalizes specific fields
        such as "arches", "specific", and "excludes", and converts them into appropriate
        internal formats. Additionally, it parses and creates PlatformFamilySpec instances
        for any keys in the mapping that correspond to platform families.

        Args:
            data (Mapping[str, Any] | None): A dictionary containing configuration data.
                Keys can include "arches", "specific", "excludes", and platform family mappings.

        Returns:
            PlatformOSSpec: A constructed instance of PlatformOSSpec based on the given data.
        """
        data = data or {}
        arches = _normalize_str_list(data.get("arches"))
        specific = _normalize_str_list(data.get("specific"))
        specific_only = bool(data.get("specific_only", False))
        excludes = _normalize_str_list(data.get("excludes"))

        families: dict[str, PlatformFamilySpec] = {}
        for key, value in data.items():
            if key in ("arches", "specific", "excludes"):
                continue
            if isinstance(value, Mapping):
                families[key] = PlatformFamilySpec.from_mapping(value)

        return cls(
            arches=arches,
            specific=specific,
            specific_only=specific_only,
            excludes=excludes,
            families=families)

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the content of an object to a dictionary representation.

        This method generates a dictionary that includes the object's attributes and their
        corresponding data, ensuring that all relevant information like `arches`, `specific`,
        and `excludes` are included as lists. It also processes the `families` attribute of the
        object to include mappings for each family if applicable.

        Returns:
            dict[str, Any]: A dictionary representing the object's data, including `arches`,
            `specific`, `excludes`, and `families` (if present).
        """
        result: dict[str, Any] = {}
        if self.arches:
            result["arches"] = list(self.arches)
        if self.specific:
            result["specific"] = list(self.specific)
        if self.excludes:
            result["excludes"] = list(self.excludes)
        if self.specific_only:
            result["specific_only"] = bool(self.specific_only)
        for name, fam in self.families.items():
            fam_mapping = fam.to_mapping()
            if fam_mapping:
                result[name] = fam_mapping
        return result


@dataclass(slots=True)
class CompatibilityTagsSpec(MultiformatSerializableMixin):
    """
    Represents a specification for compatibility tags.

    This class defines compatibility tag specifications which can include specific
    tags and tags to exclude. It provides functionality to populate this
    specification from a mapping and serialize it back to a mapping. It is useful
    for managing compatibility checks by specifying allowed and excluded tags.

    Attributes:
        specific (list[str]): A list of specific tags to include in the
            compatibility specification.
        specific_only (bool): Indicates whether only specific tags are allowed.
        excludes (list[str]): A list of tags to exclude from the
            compatibility specification.
    """

    specific: list[str] = field(default_factory=list)
    specific_only: bool = False
    excludes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> CompatibilityTagsSpec:
        """
        Creates an instance of CompatibilityTagsSpec from a mapping of data.

        This method is a class-level factory for creating instances of the
        CompatibilityTagsSpec class using the provided mapping. If no data mapping
        is provided, it initializes with default empty values.

        Args:
            data (Mapping[str, Any] | None): The mapping containing the keys
                "specific" and "excludes", each paired with values to be normalized
                into string lists. If None is passed, empty values will be used.

        Returns:
            CompatibilityTagsSpec: An instance of the CompatibilityTagsSpec class
            initialized with the normalized "specific" and "excludes" data.
        """
        data = data or {}
        return cls(
            specific=_normalize_str_list(data.get("specific")),
            specific_only=bool(data.get("specific_only", False)),
            excludes=_normalize_str_list(data.get("excludes")))

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the current instance attributes to a dictionary mapping.

        This method creates a dictionary representing the instance state. It includes
        specific attributes if they exist and excludes attributes if they are defined.
        The method ensures values are converted into lists.

        Returns:
            dict[str, Any]: A dictionary containing the mapping of specific and excludes
            attributes, if available. Keys will only be present if the respective attributes
            are set.
        """
        result: dict[str, Any] = {}
        if self.specific:
            result["specific"] = list(self.specific)
        if self.specific_only:
            result["specific_only"] = bool(self.specific_only)
        if self.excludes:
            result["excludes"] = list(self.excludes)
        return result


@dataclass(slots=True)
class CompatibilitySpec(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents compatibility specifications and their serialization/deserialization.

    This class is a data model designed to hold and process compatibility-related
    information, including Python versions, ABI values, platform-specific values,
    and compatibility tags. It provides methods for creating instances from various
    mappings or files and for serializing the data back to mappings or files.

    Attributes:
        python_versions_spec (PythonVersionsSpec): Information about compatible Python versions.
        source_description (str): A description of the source from which the CompatibilitySpec
            was loaded.
        abi_values (AbiValuesSpec): Information about compatible ABI values.
        platform_values (dict[str, PlatformOSSpec]): Mapping of platform-specific compatibility
            specifications, structured by operating system names.
        compatibility_tags (dict[str, CompatibilityTagsSpec]): Mapping of compatibility tags
            defining specific compatibility profiles (OS family, e.g., "linux").
    """

    python_versions_spec: PythonVersionsSpec
    source_description: str = field(default="")
    abi_values: AbiValuesSpec = field(default_factory=AbiValuesSpec)
    platform_values: dict[str, PlatformOSSpec] = field(default_factory=dict)
    compatibility_tags: dict[str, CompatibilityTagsSpec] = field(default_factory=dict)

    # lazy / cached backing fields
    _tags: set[Tag] = field(default_factory=set, repr=False)
    _exclude_tags: set[Tag] = field(default_factory=set, repr=False)
    _py_bounds: SpecifierSet | None = field(init=False, default=None, repr=False)
    _tags_specific_only: bool = field(default=False, repr=False)
    _tags_whitelist: set[Tag] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        build_plan = current_build_plan.get()
        spec_str = ",".join(f"=={v}" for v in build_plan.resolved_python_versions)
        self._py_bounds = SpecifierSet(spec_str)
        # Precompute explicit tag profiles from CompatibilityTagsSpec
        for profile in self.compatibility_tags.values():
            parsed_specific: set[Tag] = set()
            for s in profile.specific:
                parsed_specific.update(parse_tag(s))
            self._tags.update(parsed_specific)

            if profile.specific_only:
                self._tags_specific_only = True

                self._tags_whitelist.update(parsed_specific)

            if profile.excludes:
                for s in profile.excludes:
                    self._exclude_tags.update(parse_tag(s))

    @property
    def exclude_tags(self) -> set[Tag]:
        """
        Gets the set of excluded tags. This set has the final say in determining
        the set of allowed tags.

        This property retrieves the tags that are excluded, if any. If no tags
        are specified for exclusion, an empty set is returned.

        Returns:
            set[Tag]: The set of excluded tags or an empty set if none.
        """
        return self._exclude_tags or set()

    @property
    def resolved_python_version_range(self) -> SpecifierSet | None:
        """
        Gets the resolved Python version range based on internal constraints.

        If internal constraints for Python version bounds are defined, this property
        returns the corresponding SpecifierSet. Otherwise, it returns None.

        Returns:
            SpecifierSet | None: The Python version range as a SpecifierSet if bounds
                are defined, otherwise None.
        """
        return self._py_bounds or None

    @property
    def tags(self) -> set[Tag]:
        """
        Gets the tags associated with the current instance. These are all
        tags that have been generated from the compatibility spec parameters.

        Returns:
            set[Tag]: A set of Tag objects representing the associated tags.
        """
        return self._tags or set()

    @property
    def tags_specific_only(self) -> bool:
        """
        Determines whether to use only the tags from the whitelist.

        This property checks if the `_tags_specific_only` attribute is set and returns its value.
        If the attribute is not set or evaluated to `False`, the property defaults to `False`.

        Returns:
            bool: `True` if tags are specific-only; otherwise, `False`.
        """
        return self._tags_specific_only or False

    @property
    def tags_whitelist(self) -> set[Tag]:
        """
        Gets the whitelist of tags.

        The whitelist defines a set of tags that are permitted. This property
        provides access to the list of tags that are explicitly allowed. Note
        that it is possible for the tags in this list to be:
            1. a subset of the general tags, or
            2. supplemental to the general tags.

        Returns:
            set[Tag]: A set containing the whitelisted tags. If no tags are
            whitelisted, an empty set is returned.
        """
        return self._tags_whitelist or set()

    @property
    def allowed_tags(self) -> set[Tag]:
        """
        Returns the set of allowed tags based on specific conditions.

        The allowed tags are computed by considering the whitelist of tags if
        'specific only' is True. Otherwise, it includes the union of general
        tags and the whitelist. Tags in the exclusion list are deducted from
        the resulting set.

        Returns:
            set[Tag]: The final set of allowed tags after applying the conditions.
        """
        base = self.tags_whitelist if self.tags_specific_only else self.tags.union(self.tags_whitelist)
        return base - self.exclude_tags

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the instance data into a dictionary representation.

        This method creates a dictionary that includes mappings for Python versions, ABI values,
        platform values, and compatibility tags (if they exist). Each of these components is
        represented as a sub-dictionary, reflecting their respective mappings.

        Returns:
            dict[str, Any]: A dictionary containing the mappings for the instance's attributes.
        """
        result: dict[str, Any] = {}

        pv_mapping = self.python_versions_spec.to_mapping()
        if pv_mapping:
            result["PythonVersions"] = pv_mapping

        abi_mapping = self.abi_values.to_mapping()
        if abi_mapping:
            result["AbiValues"] = abi_mapping

        if self.platform_values:
            platform_block: dict[str, Any] = {}
            for os_name, os_spec in self.platform_values.items():
                os_mapping = os_spec.to_mapping()
                if os_mapping:
                    platform_block[os_name] = os_mapping
            if platform_block:
                result["PlatformValues"] = platform_block

        if self.compatibility_tags:
            tags_block: dict[str, Any] = {}
            for profile_name, profile_spec in self.compatibility_tags.items():
                profile_mapping = profile_spec.to_mapping()
                if profile_mapping:
                    tags_block[profile_name] = profile_mapping
            if tags_block:
                result["CompatibilityTags"] = tags_block

        return result

    @classmethod
    def from_mapping(
            cls,
            mapping: Mapping[str, Any],
            *,
            source_description: str = "",
            **_: Any) -> CompatibilitySpec:
        """
        Creates an instance of CompatibilitySpec from a given mapping. This method is a factory method
        that parses the provided data mapping for compatibility-related information such as Python versions,
        ABI values, platform values, and compatibility tags. It converts these mappings into their corresponding
        specification objects and initializes a new CompatibilitySpec instance.

        Args:
            source_description: (str): A description of the source from which the CompatibilitySpec was loaded.
            mapping (Mapping[str, Any]): A mapping containing compatibility specification data.
                This data may include mappings for Python versions, ABI values, platform values,
                and compatibility tags.
            **_ (Any): Additional keyword arguments that are ignored.

        Returns:
            CompatibilitySpec: An instance initialized with the parsed compatibility data.
        """
        data = mapping or {}

        python_versions = PythonVersionsSpec.from_mapping(data.get("PythonVersions"))
        abi_values = AbiValuesSpec.from_mapping(data.get("AbiValues"))

        platform_values: dict[str, PlatformOSSpec] = {}
        platform_block = data.get("PlatformValues") or {}
        if isinstance(platform_block, Mapping):
            for os_name, os_mapping in platform_block.items():
                if isinstance(os_mapping, Mapping):
                    platform_values[os_name] = PlatformOSSpec.from_mapping(os_mapping)

        compatibility_tags: dict[str, CompatibilityTagsSpec] = {}
        tags_block = data.get("CompatibilityTags") or {}
        if isinstance(tags_block, Mapping):
            for profile_name, profile_mapping in tags_block.items():
                if isinstance(profile_mapping, Mapping):
                    compatibility_tags[profile_name] = CompatibilityTagsSpec.from_mapping(profile_mapping)

        return cls(
            source_description=source_description,
            python_versions_spec=python_versions,
            abi_values=abi_values,
            platform_values=platform_values,
            compatibility_tags=compatibility_tags)

    def to_toml_file(
            self,
            path: Path,
            *,
            overwrite: bool = False,
            make_parents: bool = False) -> Path:
        """
        Serializes the current object's data to a TOML file at the specified path.

        This method converts the object into a mapping, serializes it to a
        TOML-formatted string, and writes it to the file system. It offers
        options to overwrite the file if it already exists, and to create
        parent directories if they do not already exist.

        Args:
            path (Path): The file path where the TOML content will be written.
            overwrite (bool): Whether to overwrite the file if it already exists.
                Defaults to False.
            make_parents (bool): Whether to create parent directories if they
                do not exist. Defaults to False.

        Returns:
            Path: The path to the file where the TOML content was written.

        Raises:
            FileExistsError: If the target file exists and `overwrite` is False.
        """
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists and overwrite=False")
        if not path.parent.exists() and make_parents:
            path.parent.mkdir(parents=True, exist_ok=True)

        mapping = self.to_mapping()
        text = dump_toml_to_str(mapping)
        path.write_text(text, encoding="utf-8")
        return path
