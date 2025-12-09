from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from email.parser import Parser
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin


@dataclass(slots=True, frozen=True)
class Pep658Metadata(MultiformatDeserializableMixin):
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

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Pep658Metadata:
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
