from __future__ import annotations

import hashlib
import re
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Iterable
from dataclasses import dataclass, field
from email.parser import Parser
from pathlib import Path
from typing import Any

from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin

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
class SourceInfo(MultiformatSerializableMixin):
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

    def to_mapping(self) -> dict[str, Any]:
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


@dataclass(slots=True, frozen=True)
class ExtrasInfo(MultiformatSerializableMixin):
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

    @staticmethod
    def from_mapping(m: Mapping[str, list[str]]) -> ExtrasInfo:
        """
        Creates an instance of ExtrasInfo from a mapping of strings to lists of strings.

        This static method processes a given mapping and converts its values into lists,
        ensuring a consistent format. If the provided mapping is None, an empty
        dictionary is used by default.

        Args:
            m (Mapping[str, list[str]]): A mapping where keys are strings and the
                corresponding values are lists of strings.

        Returns:
            ExtrasInfo: An instance of ExtrasInfo initialized with the transformed
                `extras` dictionary.
        """
        return ExtrasInfo(extras={k: list(v) for k, v in (m or {}).items()})

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

    def to_mapping(self) -> dict[str, list[str]]:
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
class WheelInfo(MultiformatSerializableMixin):
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

    def to_mapping(self) -> dict[str, Any]:
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

    @staticmethod
    def from_mapping(filename: str, m: Mapping[str, Any]) -> WheelInfo:
        """
        Create a WheelInfo instance from a given mapping.

        This method generates a `WheelInfo` object by mapping values from a provided
        dictionary to the attributes of the `WheelInfo` instance. It handles parsing
        and defaults for absent keys in the mapping.

        Args:
            filename (str): The name of the wheel package file.
            m (Mapping[str, Any]): A dictionary containing metadata and information
                to populate the attributes of the `WheelInfo` object.

        Returns:
            WheelInfo: A fully populated instance of the `WheelInfo` class.
        """
        return WheelInfo(
            filename=filename,
            name=str(m.get("name", "")),
            version=str(m.get("version", "")),
            size=int(m.get("size", 0)),
            sha256=str(m.get("sha256", "")),
            tags=[str(x) for x in (m.get("tags") or [])],
            requires_python=(str(m["requires_python"])
                             if m.get("requires_python") else None),
            deps=[str(x) for x in (m.get("deps") or [])],
            extras=ExtrasInfo.from_mapping(m.get("extras") or {}),
            source=SourceInfo(**m["source"]) if m.get("source") else None,
            meta=dict(m.get("meta") or {}),
            wheel=dict(m.get("wheel") or {}))

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
