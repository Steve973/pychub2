from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from urllib.parse import urlparse

from pychub.helper.strategy_loader import load_strategies_base
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.artifact_resolution_strategy import ArtifactResolutionStrategy, \
    download_to_file
from pychub.package.lifecycle.plan.resolution.resolution_config_model import (
    StrategyType,
    StrategyCriticality,
    FilesystemWheelStrategyConfig,
    HttpWheelStrategyConfig,
)

ENTRYPOINT_GROUP = "pychub.wheel_resolution_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

_WHEEL_STRATEGY_REGISTRY: dict[str, tuple[type["BaseWheelResolutionStrategy"], str]] = {}

TWheelCfg = TypeVar("TWheelCfg", FilesystemWheelStrategyConfig, HttpWheelStrategyConfig)


def _register_wheel_strategies(strategies: Iterable["BaseWheelResolutionStrategy"]) -> None:
    for strategy in strategies:
        name = strategy.name
        if not name:
            continue
        cls = type(strategy)
        fqcn = f"{cls.__module__}.{cls.__qualname__}"
        _WHEEL_STRATEGY_REGISTRY[name] = (cls, fqcn)


def wheel_strategy_from_mapping(mapping: Mapping[str, Any]) -> "BaseWheelResolutionStrategy":
    return BaseWheelResolutionStrategy.from_mapping(mapping)


def load_wheel_resolution_strategies(
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list["BaseWheelResolutionStrategy"]:
    strategies = load_strategies_base(
        base=BaseWheelResolutionStrategy,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
    _register_wheel_strategies(strategies)
    return strategies


@dataclass(slots=True, frozen=True, kw_only=True)
class BaseWheelResolutionStrategy(ArtifactResolutionStrategy[TWheelCfg], ABC):
    strategy_type: ClassVar[StrategyType] = StrategyType.WHEEL_FILE

    @property
    def artifact_subdir(self) -> str:
        return "wheels"

    def resolve(
            self,
            dest_dir: Path,
            uri: str | None = None,
            wheel_key: WheelKey | None = None) -> Path | None:
        if uri is None:
            return None
        return self.fetch_wheel(uri=uri, dest_dir=dest_dir)

    @abstractmethod
    def fetch_wheel(self, *, uri: str, dest_dir: Path) -> Path | None:
        raise NotImplementedError


@dataclass(slots=True, frozen=True, kw_only=True)
class FilesystemWheelStrategy(BaseWheelResolutionStrategy[FilesystemWheelStrategyConfig]):
    def fetch_wheel(self, *, uri: str, dest_dir: Path) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme not in self.strategy_config.supported_schemes:
            return None

        src = Path(parsed.path)
        if not src.exists() or not src.is_file():
            return None

        dest_path = dest_dir / src.name
        tmp = dest_path.with_suffix(dest_path.suffix + ".tmp")
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(src, tmp)
            tmp.replace(dest_path)
            return dest_path
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            if self.strategy_config.criticality == StrategyCriticality.IMPERATIVE:
                raise
            return None

    @classmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> FilesystemWheelStrategyConfig:
        return FilesystemWheelStrategyConfig.from_mapping(mapping)


@dataclass(slots=True, frozen=True, kw_only=True)
class HttpWheelStrategy(BaseWheelResolutionStrategy[HttpWheelStrategyConfig]):
    def fetch_wheel(self, *, uri: str, dest_dir: Path) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme not in self.strategy_config.supported_schemes:
            return None

        filename = Path(parsed.path).name
        if not filename:
            return None

        dest_path = dest_dir / filename
        return download_to_file(uri, dest_path)

    @classmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> HttpWheelStrategyConfig:
        return HttpWheelStrategyConfig.from_mapping(mapping)
