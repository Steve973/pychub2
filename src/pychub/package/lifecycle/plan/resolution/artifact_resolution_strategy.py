import shutil
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar
from urllib.request import Request, urlopen

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.resolution_config_model import ArtifactResolutionStrategyConfig

TConfig = TypeVar("TConfig", bound=ArtifactResolutionStrategyConfig)
TStrategy = TypeVar("TStrategy", bound="ArtifactResolutionStrategy[Any]")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def download_to_file(url: str, dest_path: Path, *, headers: dict[str, str] | None = None) -> Path | None:
    ensure_dir(dest_path.parent)
    tmp = dest_path.with_suffix(dest_path.suffix + ".tmp")

    try:
        req = Request(url, headers=headers or {})
        with urlopen(req) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
        tmp.replace(dest_path)
        return dest_path
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None

def write_bytes_atomic(dest_path: Path, data: bytes) -> Path | None:
    ensure_dir(dest_path.parent)
    tmp = dest_path.with_suffix(dest_path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest_path)
        return dest_path
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None


@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactResolutionStrategy(
    Generic[TConfig],
    ABC,
    MultiformatModelMixin):
    strategy_config: TConfig

    @property
    def fqcn(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @property
    def name(self) -> str:
        return self.strategy_config.name

    @property
    @abstractmethod
    def artifact_subdir(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def resolve(
            self,
            dest_dir: Path,
            *,
            uri: str | None = None,
            wheel_key: WheelKey | None = None) -> Path | None:
        raise NotImplementedError

    # ---------- serialization ----------

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Delegate to the config. Config already includes fqcn, name, precedence, etc.
        """
        return self.strategy_config.to_mapping(*args, **kwargs)

    @classmethod
    @abstractmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> TConfig:
        """
        Leaf strategy picks the right config type and calls the from_mapping() method.
        """
        raise NotImplementedError

    @classmethod
    def _construct_from_parts(
            cls: type[TStrategy],
            config: TConfig,
            **deps: Any) -> TStrategy:
        """
        Override if the concrete strategy adds extra ctor args (runtime deps).
        """
        return cls(strategy_config=config, **deps)

    @classmethod
    def from_mapping(
            cls: type[TStrategy],
            mapping: Mapping[str, Any],
            **deps: Any) -> TStrategy:
        """
        By default, we treat the mapping itself as the config mapping.
        If you later wrap configs (e.g. {"config": {...}}), you can adjust here.
        """
        cfg = cls._config_from_mapping(mapping)
        return cls._construct_from_parts(cfg, **deps)
