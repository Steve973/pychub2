from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast, Any

from pychub.helper.strategy_loader import load_strategies_base
from pychub.package.lifecycle.plan.resolution.wheels.wheel_source.wheel_resolution_strategy import \
    WheelResolutionStrategy

ENTRYPOINT_GROUP = "pychub.wheel_resolution_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

# name -> (class object, fully qualified class name)
_WHEEL_STRATEGY_REGISTRY: dict[str, tuple[type[WheelResolutionStrategy], str]] = {}


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
    return cast(list[WheelResolutionStrategy], strategies)
