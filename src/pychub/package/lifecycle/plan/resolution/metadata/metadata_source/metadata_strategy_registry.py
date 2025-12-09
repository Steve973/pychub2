from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast, Any

from pychub.helper.strategy_loader import load_strategies_base

from pychub.package.lifecycle.plan.resolution.metadata.metadata_source.base_metadata_strategy import \
    BaseMetadataStrategy

ENTRYPOINT_GROUP = "pychub.wheel_metadata_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

# name | fqcn -> class object
_METADATA_STRATEGY_REGISTRY: dict[str, tuple[type[BaseMetadataStrategy], str]] = {}


def _register_metadata_strategies(strategies: Iterable[BaseMetadataStrategy]) -> None:
    """
    Populate the name->type and name->fqcn registries from concrete strategy instances.
    """
    for strategy in strategies:
        cls = type(strategy)
        name = getattr(strategy, "name", None)
        if not name:
            continue
        fqcn = f"{cls.__module__}.{cls.__qualname__}"
        _METADATA_STRATEGY_REGISTRY[name] = cls, fqcn
        _METADATA_STRATEGY_REGISTRY[fqcn] = cls, fqcn


def metadata_strategy_from_mapping(mapping: Mapping[str, Any]) -> BaseMetadataStrategy:
    """
    Given a serialized strategy mapping, pick the right concrete class
    and delegate to its from_mapping.
    """
    fqcn = mapping.get("fqcn")
    name = mapping.get("name")

    cls: type[BaseMetadataStrategy] | None = None

    for val in (fqcn, name):
        if val is not None and val in _METADATA_STRATEGY_REGISTRY:
            cls, _ = _METADATA_STRATEGY_REGISTRY[val]
            break

    if cls is None:
        raise ValueError(f"Unknown metadata strategy for mapping: {mapping!r}")

    return cls.from_mapping(mapping)


def lookup_metadata_strategy(name: str) -> tuple[type[BaseMetadataStrategy], str] | None:
    return _METADATA_STRATEGY_REGISTRY.get(name)


def get_metadata_strategy_type(name: str) -> type[BaseMetadataStrategy] | None:
    info = lookup_metadata_strategy(name)
    return info[0] if info is not None else None


def get_metadata_strategy_fqcn(name: str) -> str | None:
    info = lookup_metadata_strategy(name)
    return info[1] if info is not None else None


def get_metadata_strategy_registry() -> dict[str, tuple[type[BaseMetadataStrategy], str]]:
    # shallow copy to avoid outside mutation
    return dict(_METADATA_STRATEGY_REGISTRY)


def load_wheel_metadata_strategies(
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list[BaseMetadataStrategy]:
    """
    Load all registered wheel metadata strategies, ordered by precedence,
    optionally constrained / reordered by name or overridden precedence.
    """
    strategies = load_strategies_base(
        base=BaseMetadataStrategy,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
    _register_metadata_strategies(strategies)
    return cast(list[BaseMetadataStrategy], strategies)
