from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin


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
