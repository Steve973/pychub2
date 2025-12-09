from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pychub.model.packaging.scripts_model import Scripts
from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


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
