from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field
from email.parser import Parser
from functools import total_ordering
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, parse_tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version, InvalidVersion
from typing_extensions import Self

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.helper.toml_utils import dump_toml_to_str
from pychub.helper.wheel_tag_utils import choose_wheel_tag
from pychub.package.lifecycle.plan.compatibility.python_version_discovery import list_available_python_versions_for_spec
from pychub.package.lifecycle.plan.resolution.artifact_resolution import _wheel_filename_from_uri

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
class PythonVersionsSpec(MultiformatModelMixin):
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Constructs a PythonVersionsSpec object from a mapping of data.

        This method allows the creation of a PythonVersionsSpec object by
        extracting and normalizing values from a provided mapping. If the mapping
        is not provided or is None, default empty values are applied.

        Args:
            mapping (Mapping[str, Any] | None): A dictionary-like object containing
                data to populate the PythonVersionsSpec attributes. May include
                the keys "min", "max", "types", "specific", and "excludes". If not
                provided, default empty values are used.

        Returns:
            PythonVersionsSpec: An instance of PythonVersionsSpec initialized with
            the provided mapping values.
        """
        if mapping is None:
            raise ValueError("Mapping data must be provided")
        return cls(
            min=str(mapping.get("min")),
            max=str(mapping.get("max")),
            types=_normalize_str_list(mapping.get("types")),
            accept_universal=bool(mapping.get("accept_universal", True)),
            specific=_normalize_str_list(mapping.get("specific")),
            specific_only=bool(mapping.get("specific_only", False)),
            excludes=_normalize_str_list(mapping.get("excludes")))

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
class AbiValuesSpec(MultiformatModelMixin):
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Creates an instance of the class by mapping given data to its attributes.

        This method is a factory class method that constructs an instance of the class by
        mapping the provided dictionary to the requisite attributes of the class. If no
        mapping data is supplied, default values will be used. The mapping involves
        normalization of specific string lists for certain attributes.

        Args:
            mapping (Mapping[str, Any] | None): Input mapping data containing keys and raw
                values for the attributes. If None, defaults will be used to create the instance.

        Returns:
            AbiValuesSpec: A new instance of AbiValuesSpec initialized with the provided
                or default data.
        """
        data = mapping or {}
        return cls(
            include_debug=bool(data.get("include_debug", False)),
            include_stable=bool(data.get("include_stable", False)),
            specific=_normalize_str_list(data.get("specific")),
            specific_only=bool(data.get("specific_only", False)),
            excludes=_normalize_str_list(data.get("excludes")))

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
class PlatformFamilySpec(MultiformatModelMixin):
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        data = mapping or {}
        return cls(
            min=data.get("min"),
            max=data.get("max"))

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
class PlatformOSSpec(MultiformatModelMixin):
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Creates an instance of PlatformOSSpec from a mapping dictionary.

        This class method processes the provided data mapping, normalizes specific fields
        such as "arches", "specific", and "excludes", and converts them into appropriate
        internal formats. Additionally, it parses and creates PlatformFamilySpec instances
        for any keys in the mapping that correspond to platform families.

        Args:
            mapping (Mapping[str, Any] | None): A dictionary containing configuration data.
                Keys can include "arches", "specific", "excludes", and platform family mappings.

        Returns:
            PlatformOSSpec: A constructed instance of PlatformOSSpec based on the given data.
        """
        data = mapping or {}
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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
class CompatibilityTagsSpec(MultiformatModelMixin):
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Creates an instance of CompatibilityTagsSpec from a mapping of data.

        This method is a class-level factory for creating instances of the
        CompatibilityTagsSpec class using the provided mapping. If no data mapping
        is provided, it initializes with default empty values.

        Args:
            mapping (Mapping[str, Any] | None): The mapping containing the keys
                "specific" and "excludes", each paired with values to be normalized
                into string lists. If None is passed, empty values will be used.

        Returns:
            CompatibilityTagsSpec: An instance of the CompatibilityTagsSpec class
            initialized with the normalized "specific" and "excludes" data.
        """
        data = mapping or {}
        return cls(
            specific=_normalize_str_list(data.get("specific")),
            specific_only=bool(data.get("specific_only", False)),
            excludes=_normalize_str_list(data.get("excludes")))

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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


@dataclass(kw_only=True)
class CompatibilitySpec(MultiformatModelMixin):
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
    _realized: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
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

    def realize_python_versions(self):
        available_python_versions = list_available_python_versions_for_spec(self.python_versions_spec)
        filtered_versions = self.python_versions_spec.filter_versions(available_python_versions)
        spec_str = ",".join(f"=={v}" for v in filtered_versions)
        self._py_bounds = SpecifierSet(spec_str)
        self._realized = self._py_bounds is not None

    def check_initialized(self):
        if not self._realized:
            raise ValueError("CompatibilitySpec must be realized before use.")

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
        self.check_initialized()
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
        self.check_initialized()
        return self._py_bounds or None

    @property
    def accepted_python_major_versions(self) -> frozenset[str]:
        """
        Returns a set of accepted Python major version numbers.

        This property computes the set of major version numbers based on the
        resolved Python version range available for the object instance. Each
        version in this set corresponds to a distinct major version derived
        from the resolved version range.

        Returns:
            frozenset[str]: A set of major version numbers as strings.
        """
        if self.resolved_python_version_range is None:
            return frozenset()
        return frozenset(str(Version(spec.version).major) for spec in self.resolved_python_version_range)

    @property
    def resolved_python_version_list(self) -> list[str]:
        """
        Resolves and returns a list of Python versions based on version specifications.

        This property retrieves a list of Python versions from the provided version
        specifications by extracting the `version` attribute from each element in the
        internal list of Python version bounds.

        Returns:
            list[str]: A list of resolved Python version strings.
        """
        return [spec_set.version for spec_set in self._py_bounds] if self._py_bounds else []

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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the instance data into a dictionary representation.

        This method creates a dictionary that includes mappings for Python versions, ABI values,
        platform values, and compatibility tags (if they exist). Each of these components is
        represented as a sub-dictionary, reflecting their respective mappings.

        Returns:
            dict[str, Any]: A dictionary containing the mappings for the instance's attributes.
        """
        self.check_initialized()
        result: dict[str, Any] = {}

        pv_mapping = self.python_versions_spec.to_mapping()
        if pv_mapping:
            result["python_versions"] = pv_mapping

        abi_mapping = self.abi_values.to_mapping()
        if abi_mapping:
            result["abi_values"] = abi_mapping

        if self.platform_values:
            platform_block: dict[str, Any] = {}
            for os_name, os_spec in self.platform_values.items():
                os_mapping = os_spec.to_mapping()
                if os_mapping:
                    platform_block[os_name] = os_mapping
            if platform_block:
                result["platform_values"] = platform_block

        if self.compatibility_tags:
            tags_block: dict[str, Any] = {}
            for profile_name, profile_spec in self.compatibility_tags.items():
                profile_mapping = profile_spec.to_mapping()
                if profile_mapping:
                    tags_block[profile_name] = profile_mapping
            if tags_block:
                result["compatibility_tags"] = tags_block

        return result

    @classmethod
    def from_mapping(
            cls,
            mapping: Mapping[str, Any],
            *,
            source_description: str = "",
            **_: Any) -> Self:
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
        python_versions_mapping: Mapping[str, Any] = mapping.get("python_versions") or {}
        python_versions = PythonVersionsSpec.from_mapping(python_versions_mapping)
        abi_values_mapping: Mapping[str, Any] = mapping.get("abi_values") or {}
        abi_values = AbiValuesSpec.from_mapping(abi_values_mapping)

        platform_values: dict[str, PlatformOSSpec] = {}
        platform_block = mapping.get("platform_values") or {}
        if isinstance(platform_block, Mapping):
            for os_name, os_mapping in platform_block.items():
                if isinstance(os_mapping, Mapping):
                    platform_values[os_name] = PlatformOSSpec.from_mapping(os_mapping)

        compatibility_tags: dict[str, CompatibilityTagsSpec] = {}
        tags_block = mapping.get("compatibility_tags") or {}
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
        self.check_initialized()
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} already exists and overwrite=False")
        if not path.parent.exists() and make_parents:
            path.parent.mkdir(parents=True, exist_ok=True)

        mapping = self.to_mapping()
        text = dump_toml_to_str(mapping)
        path.write_text(text, encoding="utf-8")
        return path


@dataclass(slots=True, kw_only=True)
class WheelKeyMetadata(MultiformatModelMixin):
    actual_tag: str
    satisfied_tags: frozenset[str] = frozenset()
    origin_uri: str | None = None

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        mapping = {
            "actual_tag": self.actual_tag,
            "satisfied_tags": sorted(self.satisfied_tags)
        }
        if self.origin_uri:
            mapping.update({"origin_uri": self.origin_uri})
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        return cls(
            actual_tag=mapping["actual_tag"],
            satisfied_tags=frozenset(mapping.get("satisfied_tags", [])),
            origin_uri=mapping.get("origin_uri"))


@total_ordering
@dataclass(slots=True, frozen=True)
class WheelKey(MultiformatModelMixin):
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
    metadata: WheelKeyMetadata | None = field(default=None, compare=False, hash=False, repr=False)

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

    def __iter__(self) -> Iterator[str]:
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

    @property
    def tagged_name(self) -> str:
        if self.metadata is None:
            raise ValueError("Cannot get tagged name without metadata")
        return f"{self}-{self.metadata.actual_tag}"

    def set_metadata(self, metadata: WheelKeyMetadata) -> None:
        if self.metadata is None:
            if metadata.actual_tag not in metadata.satisfied_tags:
                raise ValueError("WheelKeyMetadata invariant violated: actual_tag not in satisfied_tags")
            object.__setattr__(self, "metadata", metadata)
        else:
            raise ValueError("WheelKey.metadata is already set")

    # --------------------------------------------------------------------- #
    # (De)serialization helpers
    # --------------------------------------------------------------------- #
    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the attributes of an instance into a mapping.

        The method creates a dictionary containing key-value pairs of the
        instance's attributes defined in the method.

        Returns:
            Mapping[str, Any]: A dictionary with the instance's attribute names
            as keys and their values as corresponding values.
        """
        mapping: dict[str, Any] = {"name": self.name, "version": self.version}
        if self.metadata:
            mapping.update({"metadata": self.metadata.to_mapping()})
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
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
        metadata_mapping = mapping.get("metadata") or None
        metadata = WheelKeyMetadata.from_mapping(metadata_mapping) if metadata_mapping else None
        return cls(
            name=mapping["name"],
            version=mapping["version"],
            metadata=metadata)

    @classmethod
    def from_uri(cls, uri: str) -> WheelKey:
        filename = _wheel_filename_from_uri(uri)
        name, version, _, tagset = parse_wheel_filename(filename)
        chosen_tag = choose_wheel_tag(filename=filename, name=str(name), version=str(version))
        if chosen_tag is None:
            raise ValueError(
                "Cannot determine wheel tag from URI: "
                f"filename={filename}, name={name}, version={version}")
        tag_list = [str(t) for t in tagset]
        return cls(
            str(name),
            str(version),
            WheelKeyMetadata(
                actual_tag=chosen_tag,
                satisfied_tags=frozenset(tag_list),
                origin_uri=uri))

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

    def __hash__(self) -> int:
        return hash((self.name, self.version))

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
class ResolvedWheelNode(MultiformatModelMixin):
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
    dependencies: frozenset[WheelKey] = field(default_factory=frozenset)
    tag_urls: Mapping[str, str] = field(default_factory=dict)

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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
            "dependencies": [dep.to_mapping() for dep in sorted(self.dependencies)],
            "tag_urls": dict(self.tag_urls) if self.tag_urls is not None else None,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
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
        requires_dist_raw = mapping.get("requires_dist", [])
        requires_dist = frozenset(str(rd) for rd in requires_dist_raw) or frozenset()
        tag_urls_raw = mapping.get("tag_urls")
        tag_urls = dict(tag_urls_raw) if tag_urls_raw is not None else {}
        return cls(
            name=str(mapping["name"]),
            version=str(mapping["version"]),
            requires_python=str(mapping["requires_python"]),
            requires_dist=requires_dist,
            dependencies=deps,
            tag_urls=tag_urls)


@dataclass(slots=True)
class CompatibilityResolution(MultiformatModelMixin):
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

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
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


@dataclass(slots=True, frozen=True)
class Pep658Metadata(MultiformatModelMixin):
    """
    Represents metadata conforming to the PEP 658 standard.

    Pep658Metadata encapsulates the details of a package's metadata as described
    by PEP 658. It provides mechanisms for constructing such metadata either from
    a mapping or from the core metadata text. This class is immutable and optimized
    for memory efficiency with `dataclass` slots enabled.

    Attributes:
        name (str): The name of the package.
        version (str): The version of the package.
        requires_python (str | None): The Python version requirement if specified,
            or None otherwise.
        requires_dist (frozenset[str]): A frozen set of dependencies required by
            the package.
    """
    name: str
    version: str
    requires_python: str | None
    requires_dist: frozenset[str]

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "requires-python": self.requires_python,
            "dependencies": list(self.requires_dist),
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Create an instance of the class from a mapping object.

        This class method initializes a new object of the class by extracting
        values from the provided mapping object and converting them to the
        appropriate format for the class attributes.

        Args:
            mapping (Mapping[str, Any]): A dictionary-like object that should
                contain the necessary attributes such as 'name', 'version',
                'requires_python', and 'requires_dist' to create the instance.
            **_ (Any): Additional unused keyword arguments that are permitted
                but discarded during the instance creation process.

        Returns:
            Pep658Metadata: An instance of the class populated with the extracted
            and formatted values from the input mapping.
        """
        return cls(
            name=str(mapping["name"]),
            version=str(mapping["version"]),
            requires_python=(mapping.get("requires_python") or None),
            requires_dist=frozenset(mapping.get("requires_dist") or []))

    @classmethod
    def from_core_metadata_text(cls, text: str) -> Pep658Metadata:
        """
        Creates an instance of Pep658Metadata from a PEP 658 core metadata text.

        The method parses the provided metadata text and extracts relevant information,
        such as the package name, version, Python version requirements, and distribution
        dependencies. The extracted information is then used to form a new instance
        of the Pep658Metadata class.

        Args:
            text (str): A string containing the PEP 658 core metadata.

        Returns:
            Pep658Metadata: An instance of the Pep658Metadata class populated with
            the parsed metadata.
        """
        msg = Parser().parsestr(text)

        name = (msg.get("Name") or "").strip()
        version = (msg.get("Version") or "").strip()
        rp_raw = msg.get("Requires-Python")
        requires_python = rp_raw.strip() if rp_raw else None
        rd_headers = msg.get_all("Requires-Dist") or []
        requires_dist = [h.strip() for h in rd_headers if h.strip()]

        return cls.from_mapping({
            "name": name,
            "version": version,
            "requires_python": requires_python,
            "requires_dist": requires_dist,
        })


def _coerce_field(value: Any) -> bool | Mapping[str, str]:
    # If it's a dict, keep it as-is
    if isinstance(value, Mapping):
        return dict(value)
    # Spec says it can be a boolean; anything else → False
    if isinstance(value, bool):
        return value
    return False


@dataclass(slots=True, frozen=True)
class Pep691FileMetadata(MultiformatModelMixin):
    filename: str
    url: str
    hashes: Mapping[str, str]
    requires_python: str | None
    yanked: bool
    core_metadata: bool | Mapping[str, str]
    data_dist_info_metadata: bool | Mapping[str, str]

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        core_metadata: bool | Mapping[str, str] = _coerce_field(mapping.get("core-metadata"))
        data_dist_info_metadata: bool | Mapping[str, str] = _coerce_field(mapping.get("data-dist-info-metadata"))
        return cls(
            filename=mapping["filename"],
            url=mapping["url"],
            hashes=mapping["hashes"],
            requires_python=mapping.get("requires_python"),
            yanked=mapping["yanked"],
            core_metadata=core_metadata,
            data_dist_info_metadata=data_dist_info_metadata)


@dataclass(slots=True, frozen=True)
class Pep691Metadata(MultiformatModelMixin):
    name: str
    files: Sequence[Pep691FileMetadata]
    last_serial: int | None = None

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        return {
            "name": self.name,
            "files": [f.to_mapping() for f in self.files],
            "last_serial": self.last_serial
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        files = [
            Pep691FileMetadata.from_mapping(f)
            for f in mapping["files"]
            if isinstance(f, Mapping)
        ]
        last_serial = mapping.get("last_serial")
        return cls(
            name=mapping["name"],
            files=files,
            last_serial=int(last_serial) if last_serial is not None else None)
