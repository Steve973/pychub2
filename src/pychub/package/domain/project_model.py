from __future__ import annotations

import re
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.helper.toml_utils import dump_toml_to_str
from pychub.package.domain.artifacts_model import Scripts


@dataclass(slots=True, frozen=True)
class ChubConfig(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents the configuration for Chub with various fields and utilities for serialization,
    deserialization, and validation.

    This data class is designed to be immutable and uses slots for efficient attribute management.
    It provides functionality to convert from and to a mapping and includes a validation method
    to ensure that configuration data conforms to expected constraints.

    Attributes:
        name (str): The name of the configuration.
        version (str): The version of the configuration.
        entrypoint (str | None): The entrypoint, if specified, as a string.
        includes (list[str]): A list of included items.
        scripts (Scripts): An instance representing scripts configuration.
        pinned_wheels (list[str]): A list of pinned dependency wheel strings in the format "name==version".
        targets (list[str]): A list of target strings.
        metadata (dict[str, Any]): Metadata associated with the configuration.
    """
    name: str
    version: str
    entrypoint: str | None = None
    includes: list[str] = field(default_factory=list)
    scripts: Scripts = field(default_factory=Scripts)
    pinned_wheels: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ChubConfig:
        """
        Creates an instance of ChubConfig from a provided mapping. The method extracts
        required fields from the given mapping to initialize a ChubConfig object. It
        also validates the created configuration before returning it.

        Args:
            mapping (Mapping[str, Any]): A dictionary-like object containing
                configuration data. It may include the following keys:
                - "name": The name of the configuration as a string.
                - "version": The version of the configuration as a string.
                - "entrypoint": An optional entrypoint destination as a string.
                - "includes": A list of strings to specify included items.
                - "scripts": Details of scripts, likely as a specific mapping.
                - "pinned_wheels": A list of pinned dependency wheel strings.
                - "targets": A list of target strings.
                - "metadata": An optional dictionary with meta-information.
            **_ (Any): Additional keyword arguments that are ignored.

        Returns:
            ChubConfig: A fully initialized and validated configuration object
            representing the provided mapping.
        """
        name = str(mapping.get("name", "")).strip()
        version = str(mapping.get("version", "")).strip()
        entrypoint = mapping.get("entrypoint")
        includes = [str(x) for x in (mapping.get("includes") or [])]
        scripts = Scripts.from_mapping(mapping.get("scripts"))
        pinned_wheels = [str(x) for x in (mapping.get("pinned_wheels") or [])]
        targets = [str(x) for x in (mapping.get("targets") or [])]
        metadata = dict(mapping.get("metadata") or {})

        cfg = ChubConfig(
            name=name,
            version=version,
            entrypoint=str(entrypoint) if entrypoint is not None else None,
            includes=includes,
            scripts=scripts,
            pinned_wheels=pinned_wheels,
            targets=targets,
            metadata=metadata)
        cfg.validate()
        return cfg

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the current object to a dictionary representation.

        The function generates a dictionary containing key-value mappings of the object's
        attributes and nested data structure transformations. It ensures that all
        collections and attributes are converted into serializable or native Python
        types wherever necessary.

        Returns:
            dict[str, Any]: A dictionary representation of the object's state,
            including its attributes and nested structures.
        """
        return {
            "name": self.name,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "scripts": self.scripts.to_mapping(),
            "includes": list(self.includes),
            "pinned_wheels": list(self.pinned_wheels),
            "targets": list(self.targets),
            "metadata": dict(self.metadata),
        }

    def validate(self) -> None:
        """
        Validates the properties of an object to ensure they conform to expected formats and constraints.

        Raises:
            ValueError: If any of the required attributes `name`, `version`, or `pinned_wheels`
                do not fulfill their expected values or formats.
        """
        if not self.name:
            raise ValueError("name is required")
        if not self.version:
            raise ValueError("version is required")
        for pinned_wheel in self.pinned_wheels:
            dep_parts = pinned_wheel.split("==")
            if len(dep_parts) != 2:
                raise ValueError(f"pinned wheel must be in the format 'name==ver': {pinned_wheel}")
        # Keep the entrypoint a single token, and actual arg parsing happens at run.
        if self.entrypoint and (" " in self.entrypoint):
            raise ValueError("entrypoint must be a single token")


def _normalize_str_list(value: Any) -> list[str]:
    """
    Converts an input value into a normalized list of strings.

    This function accepts various input types. If the input is a string,
    it wraps it in a list. If it is a collection such as a list, tuple,
    or set, it converts each element into a string and returns the
    stringified elements as a new list. If the input is `None`, an empty
    list is returned. For other types, the input is treated as a single
    item, converted to a string, and returned as a list containing
    one element.

    Args:
        value (Any): The input value to be normalized. Can be `None`,
            a string, a list, a tuple, a set, or any other type.

    Returns:
        list[str]: A list of strings derived from the input value.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    # last resort: treat it as a single item
    return [str(value)]


def _normalize_mapping(value: Any) -> dict[str, Any]:
    """
    Normalize and validate mapping input.

    This function normalizes the input value to a dictionary and validates its
    type. It ensures the provided value is either `None` or a mapping type
    and raises a TypeError for unsupported types.

    Args:
        value (Any): The input value to be normalized into a dictionary.

    Returns:
        dict[str, Any]: A validated dictionary created from the input value.

    Raises:
        TypeError: If the input value is not `None` or a dictionary type.
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    # if someone passes a list of "k=v" or something weird in a mapping context,
    # you could decide to be clever; for now just coerce to dict-ish or blow up.
    raise TypeError(f"The provided data must be a mapping, got {type(value)!r}")


def _select_package_table(doc: Mapping[str, Any], toml_name: str | None = None) -> Mapping[str, Any] | None:
    """
    Selects the appropriate package definition from a given document and its corresponding
    TOML filename. The function is designed to process data specifically from files such as
    pyproject.toml and chubproject.toml, extracting specific package configurations while
    ensuring to skip processing when the relevant conditions are not met.

    Args:
        doc (Mapping[str, Any]): The parsed content of the TOML file, represented as
            nested mappings (dictionaries).
        toml_name (str | None, optional): The name of the TOML file being processed.
            Can be None if the file name is not available.

    Returns:
        Mapping[str, Any] | None: The extracted package configuration from the document
            if it meets the required conditions, or None if the configuration is not found
            or is explicitly disabled.
    """
    # 1) if pyproject.toml, exact [tool.pychub.package] in pyproject.toml
    if toml_name == "pyproject.toml":
        pkg = doc.get("tool", {}).get("pychub", {}).get("package")
        if isinstance(pkg, Mapping):
            if pkg.get("enabled") is False:
                print("WARNING: [tool.pychub.package.enabled] is False -- skipping pychub packaging")
                return None
            else:
                print("INFO: [tool.pychub.package] is enabled -- using pychub packaging")
                return pkg
        else:
            print("WARNING: [tool.pychub.package] not found in pyproject.toml -- skipping pychub packaging")
            return None
    # 2) exact [tool.pychub.package] [pychub.package] or [package] in chubproject.toml
    elif toml_name and re.fullmatch(r".*chubproject.*\.toml", toml_name):
        pkg = doc.get("tool", doc).get("pychub", doc).get("package")
        if isinstance(pkg, Mapping):
            print(f"INFO: [pychub.package] is enabled in {toml_name} -- using pychub packaging")
            return pkg
        else:
            # 3) flat table in chubproject.toml
            print(f"INFO: flat table found in {toml_name} -- using pychub packaging")
            return doc
    else:
        print(f"WARNING: unrecognized document detected: {toml_name} -- skipping pychub packaging")
        return None


def _determine_table_path(chubproject_path: Path, table_arg: str | None) -> str | None:
    """
    Determines the table path based on the provided chubproject file path and table argument.

    This function identifies the correct table path to use, either based on a default setting
    or the provided table argument. It verifies the given chubproject file name for correctness
    and processes the table argument to derive the appropriate table path.

    Args:
        chubproject_path (Path): The path to the chubproject configuration file.
        table_arg (str | None): The table argument specifying the desired table path. If `None`,
            the default table path is used.

    Returns:
        str | None: The determined table path. Returns `None` if the table argument specifies
            "flat".

    Raises:
        ValueError: If the `chubproject_path` is invalid or if the `table_arg` is invalid.
    """
    default_table = "tool.pychub.package"

    if chubproject_path.name == "pyproject.toml":
        return default_table

    if not re.fullmatch(r"(.*[-_.])?chubproject([-_.].*)?\.toml", chubproject_path.name):
        raise ValueError(f"Invalid chubproject_path: {chubproject_path!r}")

    if table_arg is None:
        return default_table

    normalized_name = table_arg.strip().lower()

    if normalized_name == "flat":
        return None

    if re.fullmatch(r"^(tool\.)?(pychub\.)?package$", normalized_name):
        return normalized_name

    raise ValueError(f"Invalid table_arg: {table_arg!r}")


def _nest_under(table_path: str, value: dict[str, Any]) -> dict[str, Any]:
    """
    Generates a nested dictionary structure based on a dot-separated table path and a given value.

    The function takes a dot-separated string that represents the hierarchy of keys and a dictionary as the
    value. It returns a nested dictionary where each key in the path becomes a level in the dictionary, and
    the given value is placed at the deepest level of the hierarchy.

    Args:
        table_path (str): The dot-separated string defining the hierarchy of keys for the nested dictionary.
        value (dict[str, Any]): The dictionary to nest under the hierarchy defined by the table path.

    Returns:
        dict[str, Any]: A nested dictionary structure based on the provided table path and value.
    """
    keys = table_path.split(".")
    d: dict[str, Any] = value
    for k in reversed(keys):
        d = {k: d}
    return d


def _coerce_toml_value(x: Any) -> Any:
    """
    Coerces a given value to a TOML-compatible format.

    This function handles various types such as Path, dict, list, tuple, and set,
    and converts them into representations that can be serialized into TOML.
    For example, it ensures that sets are converted into sorted lists and Path
    objects are converted to their string file paths.

    Args:
        x: The value to be coerced into a TOML-compatible format. Can be of any type.

    Returns:
        The coerced value converted to a TOML-compatible format.
    """
    if isinstance(x, Path):
        return x.as_posix()
    if isinstance(x, dict):
        return {str(k): _coerce_toml_value(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_coerce_toml_value(v) for v in x]
    if isinstance(x, set):
        # stable ordering for sets
        return sorted(_coerce_toml_value(v) for v in x)
    return x


def _parse_metadata_entries(entries: list[str] | None) -> dict[str, list[str]]:
    """
    Parses a list of metadata entries into a dictionary where keys are metadata
    keys and values are lists of associated values. Handles splitting entries into
    key-value pairs, cleaning whitespace, and merging multiple occurrences of the
    same key.

    Args:
        entries (list[str] | None): A list of metadata entries as strings. Each
            entry should be in the format `<key>=<value1>,<value2>,...`. If None
            or an empty list is provided, an empty dictionary is returned.

    Returns:
        dict[str, list[str]]: A dictionary mapping metadata keys to a list of their
        associated values. Keys are strings, and values are lists of unique strings
        without duplicates.
    """
    if not entries:
        return {}

    result: dict[str, list[str]] = {}
    for raw in entries:
        raw = raw.strip()
        # Split into key and the rest once
        if "=" in raw:
            key, values_str = raw.split("=", 1)
            key = key.strip()
            values_str = values_str.strip()
        else:
            key = raw
            values_str = ""
        vals = [v.strip() for v in values_str.split(",")] if values_str else []
        # merge multiple entries for the same key
        bucket = result.setdefault(key, [])
        for v in vals:
            if v and v not in bucket:
                bucket.append(v)
    return result


class ChubProjectError(Exception):
    pass


@dataclass(kw_only=True)
class ChubProject(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents a Chub project configuration, including attributes for identity, behavior,
    dependencies, metadata, and provenance tracking.

    The ChubProject class encapsulates configuration settings and metadata for defining,
    serializing, and deserializing a Chub project. It is designed to manage project
    properties, dependencies (e.g., wheels, includes), scripts, and provenance events for
    tracking the lifecycle of the project's configuration. It supports operations such
    as merging mappings into existing instances and creating instances from mappings.

    Attributes:
        name (str | None): The name of the Chub project.
        version (str | None): The version of the Chub project.
        project_path (str | None): The root path of the project, typically "." or a specific
            directory.
        chub (str | None): Optional path to the output .chub file.
        entrypoint (str | None): The entry point script or module for this project.
        entrypoint_args (list[str]): The arguments for the entry point script or module.
        verbose (bool): A flag indicating whether verbose logging is enabled.
        analyze_compatibility (bool): A flag indicating if compatibility analysis should
            be performed.
        table (str | None): A hint for the output layout or format.
        show_version (bool): A flag to indicate if the version (-v or --version) information
            should be displayed.
        wheels (list[str]): A list of wheel (.whl) paths or package specifications.
        includes (list[str]): A list of file paths (raw FILE[::dest] strings) to include in
            the project.
        include_chubs (list[str]): A list of additional .chub files to include in the project.
        pre_scripts (list[str]): A list of scripts to be executed before certain operations.
        post_scripts (list[str]): A list of scripts to be executed after certain operations.
        metadata (dict[str, Any]): A dictionary containing extra metadata for the project.
        provenance (list[ProvenanceEvent]): A list of provenance events tracking the project's
            history and operations performed.
    """
    # identity / general
    name: str | None = None
    version: str | None = None
    project_path: str | None = None  # typically "." or a path string

    # chub behavior
    chub: str | None = None
    entrypoint: str | None = None
    entrypoint_args: list[str] = field(default_factory=list)

    verbose: bool = False
    analyze_compatibility: bool = False
    table: str | None = None  # output layout hint
    show_version: bool = False  # -v/--version

    # wheels & extra content
    wheels: list[str] = field(default_factory=list)  # .whl paths or pkg specs
    includes: list[str] = field(default_factory=list)  # raw FILE[::dest] strings
    include_chubs: list[str] = field(default_factory=list)  # other .chub files

    pre_scripts: list[str] = field(default_factory=list)
    post_scripts: list[str] = field(default_factory=list)

    # project-level compatibility overrides (merged with embedded defaults)
    compatibility_spec: dict[str, Any] = field(default_factory=dict)

    # extra metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # provenance / audit
    provenance: list[ProvenanceEvent] = field(default_factory=list)

    @classmethod
    def _preprocess_mapping(
            cls,
            mapping: Mapping[str, Any],
            *,
            fmt: str,
            path: Path | None,
            **_: Any) -> Mapping[str, Any]:
        """
        Preprocesses and validates a mapping based on the specified format and optional path input.
        If the format is "toml", it attempts to extract a specific package configuration from the given mapping.
        Raises an error if the "pychub" configuration is not found for "toml" format.

        Args:
            mapping (Mapping[str, Any]): The input configuration mapping to preprocess.
            fmt (str): The format of the configuration. If not "toml", the mapping is returned as is.
            path (Path | None): The optional file path associated with the mapping. Used to retrieve
                contextual information like the file's name (only applicable for "toml").
            **_ (Any): Additional keyword arguments that are ignored.

        Returns:
            Mapping[str, Any]: The processed configuration mapping.

        Raises:
            ChubProjectError: If the format is "toml" and no "pychub" configuration is found.
        """
        if fmt != "toml":
            return mapping

        toml_name = path.name if path is not None else None
        package_mapping = _select_package_table(mapping, toml_name)
        if package_mapping is None:
            # Keep existing behavior: fail if no pychub config was found.
            raise ChubProjectError(f"No pychub config found in {path or '<inline TOML>'}")
        return package_mapping

    @classmethod
    def from_mapping(
            cls,
            mapping: Mapping[str, Any],
            *,
            source: SourceKind | None = None,
            details: dict[str, Any] | None = None,
            **_: Any) -> ChubProject:
        """
        Creates and returns an instance of the ChubProject class from a provided
        mapping dictionary, with optional metadata and source details.

        Args:
            mapping (Mapping[str, Any]): A dictionary containing data to populate
                the ChubProject instance. Keys in the dictionary correspond to the
                attributes of the class.
            source (SourceKind | None): Optional metadata indicating the source
                provenance of the instance being created.
            details (dict[str, Any] | None): Additional details or metadata that
                provide context about the operation or source.
            **_ (Any): Additional unused keyword arguments.

        Returns:
            ChubProject: An instance of the ChubProject class with properties
                populated from the provided mapping and metadata.
        """
        data = mapping or {}

        inst = cls(
            # scalars
            name=data.get("name"),
            version=data.get("version"),
            project_path=data.get("project_path"),
            chub=data.get("chub"),
            entrypoint=data.get("entrypoint"),
            verbose=bool(data.get("verbose", False)),
            analyze_compatibility=bool(data.get("analyze_compatibility", False)),
            table=data.get("table"),
            show_version=bool(data.get("show_version", False)),

            # lists
            wheels=_normalize_str_list(data.get("wheels")),
            entrypoint_args=_normalize_str_list(data.get("entrypoint_args")),
            includes=_normalize_str_list(data.get("includes")),
            include_chubs=_normalize_str_list(data.get("include_chubs")),
            pre_scripts=_normalize_str_list(data.get("pre_scripts") or (data.get("scripts") or {}).get("pre")),
            post_scripts=_normalize_str_list(data.get("post_scripts") or (data.get("scripts") or {}).get("post")),
            # compat overrides
            compatibility_spec=_normalize_mapping(data.get("compatibility_spec")),
            # metadata
            metadata=_normalize_mapping(data.get("metadata")))

        if source is not None:
            inst.provenance.append(
                ProvenanceEvent(
                    source=source,
                    operation=OperationKind.INIT,
                    details=details or {}))

        return inst

    def merge_from_mapping(
            self,
            data: Mapping[str, Any] | None,
            *,
            source: SourceKind | None = None,
            details: dict[str, Any] | None = None) -> None:
        """
        Merges data from a provided mapping into the current instance, updating or
        extending scalar, list, and dictionary attributes accordingly, and capturing
        provenance events when applicable.

        This method supports scalar overwrites, list merging with deduplication, and
        metadata per-key merging with priority for non-list values. Legacy mappings
        for scripts are also supported for backward compatibility.

        Args:
            data (Mapping[str, Any] | None): The input mapping containing data to
                merge into this instance. If None or empty, no action is taken.
            source (SourceKind | None): The source identifier for this merge
                operation, used for tracking provenance events. Defaults to None.
            details (dict[str, Any] | None): Additional details related to the
                origin of the data, included in the provenance event. Defaults to None.

        Returns:
            None
        """
        if not data:
            return

        # ---- Scalars: incoming overrides if present ----
        scalar_fields = (
            "name",
            "version",
            "project_path",
            "chub",
            "entrypoint",
            "verbose",
            "analyze_compatibility",
            "table",
            "show_version"
        )
        for field_name in scalar_fields:
            if field_name in data:
                setattr(self, field_name, data[field_name])

        # ---- lists: union + dedupe (existing first) ----
        def _merge_list(attr: str, key: str | None = None) -> None:
            mapping_key = key or attr
            if mapping_key not in data:
                return
            existing = getattr(self, attr) or []
            incoming = _normalize_str_list(data[mapping_key])
            combined: list[str] = []
            seen = set()
            for item in existing + incoming:
                if item not in seen:
                    seen.add(item)
                    combined.append(item)
            setattr(self, attr, combined)

        list_fields = (
            "wheels",
            "entrypoint_args",
            "includes",
            "include_chubs"
        )
        for prop in list_fields:
            _merge_list(prop)

        list_fields_with_key = (
            "pre_scripts",
            "post_scripts",
        )
        for prop in list_fields_with_key:
            _merge_list(prop, key=prop)

        # Also support legacy "scripts" mapping in the incoming data
        scripts_tbl = data.get("scripts") or {}
        if scripts_tbl:
            _merge_list("pre_scripts", key=None if "pre_scripts" in data else "pre")
            _merge_list("post_scripts", key=None if "post_scripts" in data else "post")

        # ---- dict: compatibility_spec raw override ----
        if "compatibility_spec" in data:
            self.compatibility_spec = _normalize_mapping(data.get("compatibility_spec"))

        # ---- dict: metadata per-key merge ----
        incoming_meta = data.get("metadata")
        if incoming_meta is not None:
            incoming_meta = _normalize_mapping(incoming_meta)
            for k, v_in in incoming_meta.items():
                v_existing = self.metadata.get(k)
                # If either side is not a list, treat as scalar and let incoming win
                if not isinstance(v_existing, list) or not isinstance(v_in, list):
                    self.metadata[k] = v_in
                else:
                    # both lists: union + dedupe
                    combined = []
                    seen = set()
                    for item in list(v_existing) + list(v_in):
                        key = repr(item)
                        if key not in seen:
                            seen.add(key)
                            combined.append(item)
                    self.metadata[k] = combined

        # ---- provenance ----
        if source is not None:
            self.provenance.append(
                ProvenanceEvent(
                    source=source,
                    operation=OperationKind.MERGE_EXTEND,
                    details=details or {}))

    def override_from_mapping(
            self,
            data: Mapping[str, Any] | None,
            *,
            source: SourceKind | None = None,
            details: dict[str, Any] | None = None) -> None:
        """
        Overrides the attributes of the current instance based on the provided mapping. This
        method updates scalar fields, list fields, and metadata, as well as appending provenance
        information if a source is specified.

        The method supports handling the replacement of scalar fields directly, whole replacement
        of lists, and the normalization of scripts and metadata from the given mapping.

        Args:
            data (Mapping[str, Any] | None): A dictionary-like object containing the values
                to override. If `None`, no action is performed.
            source (SourceKind | None): The source kind indicating the origin of the provided
                data. Defaults to `None`.
            details (dict[str, Any] | None): Additional details about the override operation.
                Defaults to `None`.
        """
        if not data:
            return

        # Scalars: override if present
        scalar_fields = (
            "name",
            "version",
            "project_path",
            "chub",
            "entrypoint",
            "verbose",
            "analyze_compatibility",
            "table",
            "show_version",
        )
        for field_name in scalar_fields:
            if field_name in data:
                setattr(self, field_name, data[field_name])

        # lists: replace wholesale if present
        list_fields = (
            "wheels",
            "entrypoint_args",
            "includes",
            "include_chubs",
            "pre_scripts",
            "post_scripts",
        )
        for prop in list_fields:
            if prop in data:
                setattr(self, prop, _normalize_str_list(data[prop]))

        scripts_tbl = data.get("scripts") or {}
        if scripts_tbl:
            if "pre" in scripts_tbl and "pre_scripts" not in data:
                self.pre_scripts = _normalize_str_list(scripts_tbl["pre"])
            if "post" in scripts_tbl and "post_scripts" not in data:
                self.post_scripts = _normalize_str_list(scripts_tbl["post"])

        if "compatibility_spec" in data:
            self.compatibility_spec = _normalize_mapping(data.get("compatibility_spec"))

        # dict: metadata replace if present
        if "metadata" in data:
            self.metadata = _normalize_mapping(data["metadata"])

        # provenance
        if source is not None:
            self.provenance.append(
                ProvenanceEvent(
                    source=source,
                    operation=OperationKind.MERGE_OVERRIDE,
                    details=details or {}))

    def to_mapping(self) -> dict[str, Any]:
        """
        Converts the current object into a dictionary-based mapping.

        This method creates a dictionary with the object's properties and their
        corresponding values. Complex attributes like sets or other collections
        are converted to list or dictionary representations for ease of use in
        serialization or further processing.

        Returns:
            dict[str, Any]: A dictionary mapping with the object's current
            attribute values.
        """
        return {
            "name": self.name,
            "version": self.version,
            "project_path": self.project_path,
            "wheels": list(self.wheels),
            "chub": self.chub,
            "entrypoint": self.entrypoint,
            "entrypoint_args": list(self.entrypoint_args),
            "includes": list(self.includes),
            "include_chubs": list(self.include_chubs),
            "verbose": self.verbose,
            "metadata": dict(self.metadata),
            "scripts": {
                "pre": list(self.pre_scripts),
                "post": list(self.post_scripts),
            },
        }

    @staticmethod
    def cli_to_mapping(args: Namespace) -> dict[str, object]:
        """
        Converts parsed command-line arguments into a unified configuration mapping.

        This static method takes in command-line arguments parsed by the `argparse`
        module and converts them into a standardized dictionary format. The structure
        of the dictionary is suitable for use in configuring further operations.

        Args:
            args (Namespace): An argparse `Namespace` object containing the parsed
                command-line arguments.

        Returns:
            dict[str, object]: A dictionary mapping argument names to their values,
            organized into scalars, lists, and metadata.

        """
        return {
            # scalars
            "project_path": args.project_path,
            "chub": args.chub,
            "entrypoint": args.entrypoint,
            "verbose": bool(args.verbose),
            "analyze_compatibility": bool(args.analyze_compatibility),
            "show_version": bool(args.version),
            "table": args.table,

            # lists
            "wheels": args.wheel or [],
            "includes": args.include or [],
            "include_chubs": args.include_chub or [],
            "pre_scripts": args.pre_script or [],
            "post_scripts": args.post_script or [],
            "entrypoint_args": args.entrypoint_args or [],

            # metadata as a dict
            "metadata": _parse_metadata_entries(args.metadata_entry),
        }

    @staticmethod
    def save_file(
            project: ChubProject | dict[str, Any],
            path: str | Path = "chubproject.toml",
            *,
            table_arg: str | None = None,
            overwrite: bool = False,
            make_parents: bool = True) -> Path:
        """
        Saves a ChubProject or dictionary representation to a TOML file.

        This method serializes the given project as a TOML string and writes it to the
        specified file path. It ensures that any `None`-valued keys in the project
        dictionary are stripped (but preserves `False`, empty lists, or empty
        dictionaries). Optionally, the project can be nested under a specific table in
        the resulting TOML file.

        Args:
            project: A `ChubProject` instance or a dictionary that conforms to the
                `ChubProject` structure. Represents the project metadata to be saved.
            path: The file path where the TOML representation of the project should be
                saved. Defaults to "chubproject.toml".
            table_arg: An optional key indicating the TOML table path to nest the
                project under, such as "tool.chub". If `None`, the project remains at
                the root level.
            overwrite: A flag to indicate whether to overwrite the file at `path` if it
                already exists. Defaults to `False`.
            make_parents: A flag to indicate whether to create parent directories of
                `path` if they do not exist. Defaults to `True`.

        Returns:
            Path: A `Path` object pointing to the location of the saved file.
        """

        # accept either a ChubProject or a raw mapping
        if isinstance(project, ChubProject):
            obj = project.to_mapping()
        else:
            obj = ChubProject.from_mapping(project).to_mapping()

        # strip out None-valued keys, keep False/[], {}
        obj = {k: v for k, v in obj.items() if v is not None}

        p = Path(path).expanduser().resolve()
        table_path = _determine_table_path(p, table_arg)

        if table_path is not None:
            obj = _nest_under(table_path, obj)
        # else: flat mode, obj is already the root-level mapping

        if p.exists() and not overwrite:
            raise ChubProjectError(f"Refusing to overwrite without overwrite=True: {p}")
        if make_parents:
            p.parent.mkdir(parents=True, exist_ok=True)

        text = dump_toml_to_str(_coerce_toml_value(obj))
        p.write_text(text, encoding="utf-8")
        return p


class SourceKind(str, Enum):
    """
    Enumeration for the different kinds of sources.

    Represents the various sources from which operations or data may be
    derived. Useful for differentiating between input methods, testing
    scenarios, and default configurations.

    Attributes:
        CLI (str): Represents input or actions derived from a command-line interface.
        FILE (str): Represents input or actions derived from a file source.
        MAPPING (str): Represents input or actions derived from a mapping object.
        TEST (str): Represents input or actions derived from testing mechanisms.
        DEFAULT (str): Represents input or actions derived from default configurations.
    """
    CLI = "cli"
    FILE = "file"
    MAPPING = "mapping"
    TEST = "test"
    DEFAULT = "default"


class OperationKind(str, Enum):
    """
    Represents the kinds of operations as an enumeration.

    This class defines various kinds of operations that can be performed.
    Used primarily for categorization and identification of specific
    operations in the system.

    Attributes:
        INIT (str): Represents an initialization operation type.
        MERGE_EXTEND (str): Represents an operation where merging extends
            current data or configuration.
        MERGE_OVERRIDE (str): Represents an operation where merging overrides
            current data or configuration.
    """
    INIT = "init"
    MERGE_EXTEND = "merge_extend"
    MERGE_OVERRIDE = "merge_override"


@dataclass(slots=True)
class ProvenanceEvent(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents an event detailing its origin, the operation it performs, and additional related details.

    This class is designed to provide a structured representation of an event that captures its source,
    operation, and related contextual details. It supports serialization and deserialization to and from
    various formats for ease of data exchange and storage.

    Attributes:
        source (SourceKind): The origin or source of the event, categorized by its kind.
        operation (OperationKind): The type of operation or action associated with the event.
        details (dict[str, Any]): Additional contextual information or metadata related to the event.
    """
    source: SourceKind
    operation: OperationKind
    details: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> Mapping[str, Any]:
        """
        Converts an object instance into a dictionary mapping.

        The method returns a dictionary representation of the object's attributes,
        with keys representing attribute names and values as the corresponding
        attribute values. This is useful for serializing or processing the object
        data in a uniform manner.

        Returns:
            Mapping[str, Any]: A dictionary mapping of object attributes to their
            respective values.
        """
        return {
            "source": self.source.value,
            "operation": self.operation.value,
            "details": self.details,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ProvenanceEvent:
        """
        Creates an instance of ProvenanceEvent from the provided mapping and additional arguments.

        This class method validates the 'details' field in the mapping to ensure it is a dictionary.
        If the validation succeeds, it creates and returns a ProvenanceEvent instance using the provided
        mapping data.

        Args:
            mapping (Mapping[str, Any]): A mapping containing the fields required for constructing
                a ProvenanceEvent, including 'source', 'operation', and 'details'.
            **_ (Any): Additional arguments that are ignored but allowed for compatibility.

        Returns:
            ProvenanceEvent: An instance of the ProvenanceEvent class constructed using the data
            provided in the mapping.

        Raises:
            TypeError: If the 'details' field in the provided mapping is not a dictionary.
        """
        details_obj = mapping.get("details") or {}
        if not isinstance(details_obj, dict):
            raise TypeError(f"Expected 'details' to be a mapping, got {type(details_obj)!r}")
        return ProvenanceEvent(
            source=SourceKind(mapping.get("source")),
            operation=OperationKind(mapping.get("operation")),
            details=details_obj)
