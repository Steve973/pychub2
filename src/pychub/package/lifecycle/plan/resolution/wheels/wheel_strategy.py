from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Sequence, ClassVar
from urllib.parse import urlparse
from urllib.request import urlopen

from pychub.helper.strategy_loader import load_strategies_base
from pychub.package.lifecycle.plan.resolution.artifact_resolution_strategy import ArtifactResolutionStrategy
from pychub.package.lifecycle.plan.resolution.resolution_config_model import StrategyType, \
    FilesystemWheelStrategyConfig, HttpWheelStrategyConfig

ENTRYPOINT_GROUP = "pychub.wheel_resolution_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

# name -> (class object, fully qualified class name)
_WHEEL_STRATEGY_REGISTRY: dict[str, tuple[type[WheelResolutionStrategy], str]] = {}


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


@dataclass(slots=True, frozen=True, kw_only=True)
class WheelResolutionStrategy(ArtifactResolutionStrategy, ABC):
    """
    Defines a strategy for resolving wheel artifacts within the artifact resolution
    framework. This is an abstract class meant to be inherited by specific strategies
    that implement the logic for fetching wheel files.

    The class provides an interface for handling wheel artifact fetching and includes
    utility methods for mapping and initialization updates.

    Attributes:
        strategy_type (ClassVar[StrategyType]): Specifies the type of the artifact
            resolution strategy as `WHEEL_FILE`.
    """
    strategy_type: ClassVar[StrategyType] = StrategyType.WHEEL_FILE

    @abstractmethod
    def fetch_wheel(self, uri: str, dest_dir: Path) -> Path | None:
        # Must be implemented by subclasses to fetch wheel files from a given URI
        # in terms of the implementation concerns of the specific strategy.
        raise NotImplementedError

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Converts the given arguments and keyword arguments into a dictionary mapping using
        the parent class's implementation.

        Args:
            *args: Positional arguments that will be passed to the parent class method.
            **kwargs: Keyword arguments that will be passed to the parent class method.

        Returns:
            dict[str, Any]: A dictionary representation of the input arguments and keyword
            arguments as processed by the parent class's implementation.
        """
        return super().to_mapping(*args, **kwargs)


# ---------- Filesystem-based wheel strategy ----------

@dataclass(slots=True, frozen=True, kw_only=True)
class FilesystemWheelStrategy(WheelResolutionStrategy):
    """
    Represents a strategy for resolving and fetching "wheel" files from a filesystem
    that complies with specific URI schemes.

    This class includes methods for fetching wheel files from their source locations
    to a designated destination based on predefined URI schemes and conventions.
    Additionally, it provides tooling to map its own configuration and state for
    integration or serialization purposes.

    Attributes:
        name (str): The name of the wheel strategy, defaulting to "filesystem-wheel".
        precedence (int): The precedence level of this strategy when multiple
            strategies are available, defaulting to 50.
        supported_schemes (Sequence[str]): A sequence of URI schemes supported by
            this strategy, populated with default filesystem schemes.
    """
    name: str = field(default="filesystem-wheel")
    precedence: int = field(default=50)
    supported_schemes: Sequence[str] = field(default_factory=_default_fs_schemes)

    def fetch_wheel(self, uri: str, dest_dir: Path) -> Path | None:
        """
        Fetches a wheel file from the provided URI and stores it in the specified destination directory.

        The method supports URIs with the "file" scheme and verifies the existence of the
        source file before copying it to the destination. If the scheme is unsupported or
        the source file is not found, it returns None. If the file already exists at the
        destination, the method returns the existing file's path.

        Args:
            uri (str): The source URI of the wheel file.
            dest_dir (Path): The target directory where the wheel file is to be stored.

        Returns:
            Path | None: The path to the wheel file in the destination directory if the
            operation is successful, or None if the operation fails or the scheme is
            unsupported.
        """
        parsed = urlparse(uri)

        if parsed.scheme not in self.supported_schemes:
            return None

        if parsed.scheme == "file":
            src_path = Path(parsed.path)
        else:
            raise ValueError(f"Unsupported scheme for uri: {uri!r}")

        if not src_path.is_file():
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / src_path.name

        # If it's already there, just return it
        if dest_path.exists():
            return dest_path

        shutil.copy2(src_path, dest_path)
        return dest_path

    def to_mapping(self, *args, **kwargs):
        """
        Updates and returns a mapping with additional information from the instance.

        This method calls the parent class's `to_mapping` method to retrieve the
        base mapping and then updates the mapping with the `supported_schemes`
        from the current instance.

        Args:
            *args: Positional arguments passed to the parent `to_mapping` method.
            **kwargs: Keyword arguments passed to the parent `to_mapping` method.

        Returns:
            dict: A dictionary containing the updated mapping with additional
            instance-specific information.
        """
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "supported_schemes": self.supported_schemes
        })
        return mapping

    @classmethod
    def _config_from_mapping(
            cls,
            mapping: Mapping[str, Any]) -> FilesystemWheelStrategyConfig:
        return FilesystemWheelStrategyConfig.from_mapping(mapping)


# ---------- HTTP(S) / PyPI wheel strategy ----------

@dataclass(slots=True, frozen=True, kw_only=True)
class HttpWheelStrategy(WheelResolutionStrategy):
    """
    Represents a strategy for fetching and resolving wheel files over HTTP.

    This class provides methods for downloading wheel files from a given URI
    and converting the object into a dictionary format for data mapping. It extends
    the functionality of the `WheelResolutionStrategy` and is particularly suited
    for handling HTTP-based wheel resources.

    Attributes:
        name (str): The name of this strategy, defaulting to "http-wheel".
        precedence (int): The precedence of this strategy, defaulting to 40. Higher
            precedence indicates greater priority in resolution.
        supported_schemes (Sequence[str]): A sequence of supported URI schemes
            (e.g., ["http", "https"]) that this strategy can handle.
    """
    name: str = field(default="http-wheel")
    precedence: int = field(default=40)
    supported_schemes: Sequence[str] = field(default_factory=_default_http_schemes)

    def fetch_wheel(self, uri: str, dest_dir: Path) -> Path | None:
        """
        Fetches a wheel file from a given URI, saves it to the specified directory, and returns the full
        path to the saved file. If the URI is not supported or the download fails, None is returned.

        Args:
            uri (str): The URI of the wheel file to be fetched.
            dest_dir (Path): The destination directory where the wheel file will be saved.

        Returns:
            Path | None: The full path to the saved wheel file, or None if the operation fails.
        """
        parsed = urlparse(uri)
        if parsed.scheme not in self.supported_schemes:
            return None

        filename = Path(parsed.path).name
        if not filename:
            # Not a direct file URL
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        # TODO: Consider options for retry / streaming / validation (hash verification).
        #       It should go either here, or (maybe more appropriately) in the resolver
        #       itself.
        try:
            with urlopen(uri) as response, dest_path.open("wb") as out:
                shutil.copyfileobj(response, out)
        except Exception:
            # Treat network errors as "strategy couldn't handle it"
            # so that other strategies or the resolver can decide
            # what to do.
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return None

        return dest_path

    def to_mapping(self, *args, **kwargs):
        """
        Converts the instance to a mapping format and updates the mapping with
        the `supported_schemes` attribute.

        Args:
            *args: Variable length argument list passed to the superclass method.
            **kwargs: Arbitrary keyword arguments passed to the superclass method.

        Returns:
            dict: A dictionary representation of the instance, including the
            `supported_schemes` attribute.
        """
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "supported_schemes": self.supported_schemes
        })
        return mapping

    @classmethod
    def _config_from_mapping(
            cls,
            mapping: Mapping[str, Any]) -> HttpWheelStrategyConfig:
        return HttpWheelStrategyConfig.from_mapping(mapping)


def _register_wheel_strategies(strategies: Iterable[WheelResolutionStrategy]) -> None:
    """
    Populate the name->type and name->fqcn registries from concrete strategy instances.
    """
    for strategy in strategies:
        cls = type(strategy)
        name = getattr(strategy, "name", None)
        if not name:
            continue
        fqcn = f"{cls.__module__}.{cls.__qualname__}"
        _WHEEL_STRATEGY_REGISTRY[name] = (cls, fqcn)


def wheel_strategy_from_mapping(mapping: Mapping[str, Any]) -> WheelResolutionStrategy:
    return WheelResolutionStrategy.from_mapping(mapping)


def get_wheel_strategy_type(name: str) -> type[WheelResolutionStrategy] | None:
    info = _WHEEL_STRATEGY_REGISTRY.get(name)
    return info[0] if info is not None else None


def get_wheel_strategy_fqcn(name: str) -> str | None:
    info = _WHEEL_STRATEGY_REGISTRY.get(name)
    return info[1] if info is not None else None


def get_wheel_strategy_registry() -> dict[str, tuple[type[WheelResolutionStrategy], str]]:
    # shallow copy to avoid outside mutation
    return dict(_WHEEL_STRATEGY_REGISTRY)


def load_wheel_resolution_strategies(
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list[WheelResolutionStrategy]:
    """
    Load all registered wheel metadata strategies, ordered by precedence,
    optionally constrained / reordered by name or overridden precedence.
    """
    strategies = load_strategies_base(
        base=WheelResolutionStrategy,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
    _register_wheel_strategies(strategies)
    return strategies
