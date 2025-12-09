from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin

T = TypeVar("T", bound="ArtifactResolutionStrategyConfig")


def _default_request_headers() -> dict[str, str]:
    return {"Accept": "application/vnd.pypi.simple.v1+json"}


def _default_fs_schemes() -> tuple[str, ...]:
    """
    Returns a tuple containing the default file system schemes.

    This function provides the default schemes used for file systems, such
    as "file". The returned tuple can be used in determining or validating
    file-system-related operations.

    Returns:
        tuple[str, ...]: A tuple of strings representing default file system schemes.
    """
    return ("file",)


def _default_http_schemes() -> tuple[str, ...]:
    """
    Generates a tuple of default HTTP schemes.

    This function provides default HTTP schemes supported, such as "http" and
    "https". It is used in contexts where secure and non-secure HTTP protocols
    are required to be supported by default.

    Returns:
        tuple[str, ...]: A tuple containing strings representing default
        HTTP schemes.
    """
    return "http", "https"


class StrategyType(str, Enum):
    """Represents the types of strategies available for a given operation.

    This enumeration is used to define the different strategies that can be applied
    in specific operations. Each value corresponds to a particular strategy type,
    allowing for clear and consistent representation of these strategies.

    Attributes:
        DEPENDENCY_METADATA (str): Strategy for handling dependency metadata.
        CANDIDATE_METADATA (str): Strategy for handling candidate metadata.
        WHEEL_FILE (str): Strategy for handling wheel files.
        UNSPECIFIED (str): Strategy type that is not explicitly specified.
    """
    DEPENDENCY_METADATA = "DEPENDENCY_METADATA"
    CANDIDATE_METADATA = "CANDIDATE_METADATA"
    WHEEL_FILE = "WHEEL_FILE"
    UNSPECIFIED = "UNSPECIFIED"


class StrategyCriticality(Enum):
    """
    Specifies the criticality levels for a strategy.

    This class defines the varying criticality levels for strategies,
    categorizing them as either imperative, required, or optional.
    It helps classify and manage the importance associated with a given strategy.

    Attributes:
        IMPERATIVE (str): Represents the highest level of criticality,
            indicating that the strategy is essential and may not fall
            back to any other non-imperative strategies.
        REQUIRED (str): Represents a moderate level of criticality,
            indicating that the strategy is required for artifact resolution,
            but that the resolver can fall back to other strategies.
        OPTIONAL (str): Represents the lowest level of criticality,
            indicating that the strategy is not essential.
    """
    IMPERATIVE = "IMPERATIVE"
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


################################################################################
# Base strategy config class
################################################################################

@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactResolutionStrategyConfig(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    name: str = field(default_factory=str)
    fqcn: str = field(default_factory=str)
    precedence: int = field(default=50)
    fetch_timeout_s: int = field(default=20)
    criticality: StrategyCriticality = field(default=StrategyCriticality.OPTIONAL)
    strategy_type: StrategyType = field(default=StrategyType.UNSPECIFIED)
    strategy_subtype: str = field(default_factory=str)

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "name": self.name,
            "fqcn": self.fqcn,
            "precedence": self.precedence,
            "fetch_timeout_s": self.fetch_timeout_s,
            "criticality": self.criticality.value,
            "strategy_type": self.strategy_type.value,
            "strategy_subtype": self.strategy_subtype,
        }


    @classmethod
    def _base_kwargs_from_mapping(cls, mapping: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "name": mapping.get("name", cls.name),
            "fqcn": mapping.get("fqcn", cls.fqcn),
            "precedence": int(mapping.get("precedence", cls.precedence)),
            "fetch_timeout_s": int(mapping.get("fetch_timeout_s", cls.fetch_timeout_s)),
            "criticality": StrategyCriticality(mapping.get("criticality", cls.criticality.value)),
            "strategy_type": StrategyType(mapping.get("strategy_type", cls.strategy_type.value)),
            "strategy_subtype": mapping.get("strategy_subtype", cls.strategy_subtype),
        }

    @classmethod
    def from_mapping(cls: type[T], mapping: Mapping[str, Any], **_: Any) -> T:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        return cls(**base_kwargs)


################################################################################
# Metadata resolver strategy configs
################################################################################

@dataclass(slots=True, frozen=True, kw_only=True)
class Pep691SimpleApiMetadataStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="pep691-simple-api-pypi")
    precedence: int = field(default=50)
    strategy_type = StrategyType.CANDIDATE_METADATA
    strategy_subtype: str = field(default="pep691_simple_api")
    base_simple_url: str = field(default="https://pypi.org/simple")
    request_headers: dict[str, str] = field(default_factory=_default_request_headers)

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "base_simple_url": self.base_simple_url,
            "request_headers": self.request_headers
        })
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Pep691SimpleApiMetadataStrategyConfig:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["base_simple_url"] = mapping.get("base_simple_url", cls.base_simple_url)
        base_kwargs["request_headers"] = mapping.get("request_headers", cls.request_headers)
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class WheelInspectionMetadataStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="wheel-inspection-metadata")
    precedence: int = field(default=90)
    strategy_type = StrategyType.DEPENDENCY_METADATA
    strategy_subtype: str = field(default="wheel_inspection")

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().to_mapping(*args, **kwargs)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> WheelInspectionMetadataStrategyConfig:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        return cls(**base_kwargs)


################################################################################
# Wheel resolver strategy configs
################################################################################

@dataclass(slots=True, frozen=True, kw_only=True)
class FilesystemWheelStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="filesystem-wheel-local")
    precedence: int = field(default=50)
    strategy_type = StrategyType.WHEEL_FILE
    strategy_subtype: str = field(default="filesystem_wheel")
    supported_schemes: Sequence[str] = field(default_factory=_default_fs_schemes)

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping["supported_schemes"] = self.supported_schemes
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> FilesystemWheelStrategyConfig:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["supported_schemes"] = mapping.get("supported_schemes", _default_fs_schemes())
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class HttpWheelStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="http-wheel-index")
    precedence: int = field(default=40)
    strategy_type = StrategyType.WHEEL_FILE
    strategy_subtype: str = field(default="https_wheel")
    supported_schemes: Sequence[str] = field(default_factory=_default_http_schemes)

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping["supported_schemes"] = self.supported_schemes
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> HttpWheelStrategyConfig:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["supported_schemes"] = mapping.get("supported_schemes", _default_http_schemes())
        return cls(**base_kwargs)
