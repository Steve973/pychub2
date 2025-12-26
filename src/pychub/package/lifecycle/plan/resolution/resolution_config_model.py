from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypeVar, Any

from typing_extensions import Self

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin

TConfig = TypeVar("TConfig", bound="BaseResolverConfig")
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
class ArtifactResolutionStrategyConfig(MultiformatModelMixin):
    name: str = field(default_factory=str)
    fqcn: str = field(default_factory=str)
    precedence: int = field(default=50)
    fetch_timeout_s: int = field(default=20)
    criticality: StrategyCriticality = field(default=StrategyCriticality.OPTIONAL)
    strategy_type: StrategyType = field(default=StrategyType.UNSPECIFIED)
    strategy_subtype: str = field(default_factory=str)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
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
    def from_mapping(cls: type[Self], mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        return cls(**base_kwargs)


################################################################################
# Metadata resolver strategy configs
################################################################################

@dataclass(slots=True, frozen=True, kw_only=True)
class Pep691SimpleApiMetadataStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="pep691-simple-api-pypi")
    precedence: int = field(default=50)
    strategy_type: StrategyType = field(default=StrategyType.CANDIDATE_METADATA)
    strategy_subtype: str = field(default="pep691_simple_api")
    base_simple_url: str = field(default="https://pypi.org/simple")
    request_headers: dict[str, str] = field(default_factory=_default_request_headers)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "base_simple_url": self.base_simple_url,
            "request_headers": self.request_headers
        })
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["base_simple_url"] = mapping.get("base_simple_url", cls.base_simple_url)
        base_kwargs["request_headers"] = mapping.get("request_headers", cls.request_headers)
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class Pep658SidecarMetadataStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="pep658-sidecar-metadata")
    precedence: int = field(default=90)
    strategy_type: StrategyType = field(default=StrategyType.DEPENDENCY_METADATA)  # <-- fix
    strategy_subtype: str = field(default="pep658_sidecar")

    base_simple_url: str = field(default="https://pypi.org/simple")
    request_headers: dict[str, str] = field(default_factory=_default_request_headers)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "base_simple_url": self.base_simple_url,
            "request_headers": self.request_headers,
        })
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["base_simple_url"] = mapping.get("base_simple_url", cls.base_simple_url)
        base_kwargs["request_headers"] = mapping.get("request_headers", cls.request_headers)
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class WheelInspectionMetadataStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="wheel-inspection-metadata")
    precedence: int = field(default=90)
    strategy_type: StrategyType = field(default=StrategyType.DEPENDENCY_METADATA)
    strategy_subtype: str = field(default="wheel_inspection")

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        return super().to_mapping(*args, **kwargs)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        return cls(**base_kwargs)


################################################################################
# Wheel resolver strategy configs
################################################################################

@dataclass(slots=True, frozen=True, kw_only=True)
class FilesystemWheelStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="filesystem-wheel-local")
    precedence: int = field(default=50)
    strategy_type: StrategyType = field(default=StrategyType.WHEEL_FILE)
    strategy_subtype: str = field(default="filesystem_wheel")
    supported_schemes: Sequence[str] = field(default_factory=_default_fs_schemes)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping["supported_schemes"] = self.supported_schemes
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["supported_schemes"] = mapping.get("supported_schemes", _default_fs_schemes())
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class HttpWheelStrategyConfig(ArtifactResolutionStrategyConfig):
    name: str = field(default="http-wheel-index")
    precedence: int = field(default=40)
    strategy_type: StrategyType = field(default=StrategyType.WHEEL_FILE)
    strategy_subtype: str = field(default="https_wheel")
    supported_schemes: Sequence[str] = field(default_factory=_default_http_schemes)

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        mapping = super().to_mapping(*args, **kwargs)
        mapping["supported_schemes"] = self.supported_schemes
        return mapping

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        base_kwargs = cls._base_kwargs_from_mapping(mapping)
        base_kwargs["supported_schemes"] = mapping.get("supported_schemes", _default_http_schemes())
        return cls(**base_kwargs)


@dataclass(slots=True, frozen=True)
class BaseResolverConfig(MultiformatModelMixin):
    # Local root directory where all artifact cache state lives.
    local_cache_root: Path

    # Global root directory where all artifact cache state lives.
    global_cache_root: Path

    # Interval (in minutes) for refreshing cache entries.
    update_interval: int = 1440

    # Whether to isolate artifact resolution from the global cache.
    project_isolation: bool = True

    # Whether to clear the *local* artifact cache on startup.
    clear_on_startup: bool = False

    # ---------- Serialization ----------

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Base serialization: common config fields and strategy mappings.
        Subclasses can override if they need extra fields, but this should
        be enough for most resolver configs.
        """
        return {
            "local_cache_root": str(self.local_cache_root),
            "global_cache_root": str(self.global_cache_root),
            "update_interval": self.update_interval,
            "project_isolation": self.project_isolation,
            "clear_on_startup": self.clear_on_startup,
        }

    @classmethod
    def _update_init_kwargs(
            cls,
            init_kwargs: dict[str, Any],
            mapping: Mapping[str, Any],
            **_: Any) -> None:
        """
        Updates initialization keyword arguments using a provided mapping.

        This method updates the `init_kwargs` dictionary based on values
        present in the `mapping`. Certain keys in the `mapping` are
        converted to proper data types (e.g., `Path` for paths) before
        being added to `init_kwargs`. Default values are set for missing
        keys based on class-level attributes if they are not present in
        `init_kwargs` or `mapping`.

        NOTE:
            This method is intended to be overridden by subclasses, where
            the subclasses will handle their own resolution strategies.

        Args:
            init_kwargs (dict[str, Any]): A dictionary of initialization arguments to
                be updated.
            mapping (Mapping[str, Any]): A mapping containing key-value pairs to be
                used for updating `init_kwargs`.
            **_ (Any): Additional arguments, ignored by this method.

        Returns:
            None
        """
        if "local_cache_root" in mapping:
            init_kwargs.setdefault("local_cache_root", Path(mapping["local_cache_root"]))
        if "global_cache_root" in mapping:
            init_kwargs.setdefault("global_cache_root", Path(mapping["global_cache_root"]))

        init_kwargs.setdefault("update_interval", int(mapping.get("update_interval", cls.update_interval)))
        init_kwargs.setdefault("project_isolation", bool(mapping.get("project_isolation", cls.project_isolation)))
        init_kwargs.setdefault("clear_on_startup", bool(mapping.get("clear_on_startup", cls.clear_on_startup)))

    @classmethod
    def from_mapping(cls: type[Self], mapping: Mapping[str, Any], **kwargs: Any) -> Self:
        """
        Creates an instance of the class using the provided mapping and additional keyword
        arguments. This method processes the mapping and combines it with class-specific
        initialization rules to construct the final keyword arguments used to create an
        instance of the class.

        The method is a factory method that can handle custom mapping updates defined in
        subclasses by overriding the `_update_init_kwargs` method.

        Args:
            mapping (Mapping[str, Any]): Input mapping from which configuration values
                are extracted and processed.
            **kwargs (Any): Additional keyword arguments to be merged with the processed
                mapping values.

        Returns:
            TConfig: An instance of the class created using the processed arguments.
        """
        init_kwargs: dict[str, Any] = {}
        init_kwargs.update(kwargs)

        for base in reversed(cls.mro()):
            if not issubclass(base, BaseResolverConfig):
                continue
            update = getattr(base, "_update_init_kwargs", None)
            if update is not None:
                update(init_kwargs, mapping)

        return cls(**init_kwargs)


@dataclass(slots=True, frozen=True)
class MetadataResolverConfig(BaseResolverConfig):
    pass


@dataclass(slots=True, frozen=True)
class WheelResolverConfig(BaseResolverConfig):
    # A value of zero disables refreshing, since wheels are immutable.
    update_interval: int = 0
