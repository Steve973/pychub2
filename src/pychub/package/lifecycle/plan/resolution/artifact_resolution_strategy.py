from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.lifecycle.plan.resolution.resolution_config_model import ArtifactResolutionStrategyConfig

TConfig = TypeVar("TConfig", bound=ArtifactResolutionStrategyConfig)
TStrategy = TypeVar("TStrategy", bound="ArtifactResolutionStrategy[Any]")


@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactResolutionStrategy(
    Generic[TConfig],
    ABC,
    MultiformatModelMixin):
    strategy_config: TConfig

    # Runtime convenience: "what class is this instance actually?"
    @property
    def fqcn(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @property
    def name(self) -> str:
        return self.strategy_config.name

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
        By default we treat the mapping itself as the config mapping.
        If you later wrap configs (e.g. {"config": {...}}), you can adjust here.
        """
        cfg = cls._config_from_mapping(mapping)
        return cls._construct_from_parts(cfg, **deps)
