from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any, Iterable


def _builtin_strategy_classes(base: type, package_name: str) -> list[type]:
    """
    Discovers and returns a list of classes in a specified package that are subclasses of a given
    base class but do not equal the base class itself.

    Args:
        base (type): The base class to check against.
        package_name (str): The name of the package to search for subclasses.

    Returns:
        list[type]: A list of discovered classes that are subclasses of the base class.
    """
    package = importlib.import_module(package_name)
    classes: list[type] = []

    for _finder, mod_name, _ispkg in pkgutil.walk_packages(
            package.__path__, package.__name__ + "."):
        module = importlib.import_module(mod_name)

        for obj in vars(module).values():
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, base):
                continue
            if obj is base:
                continue
            classes.append(obj)

    return classes


def _entrypoint_strategy_classes(base: type, group: str) -> list[type]:
    """
    Discovers and loads classes from entry points that are subclasses of a specified base class.

    This function iterates through entry points belonging to a specified group, checks
    if the objects loaded from these entry points are classes, and ensures they are
    subclasses of the provided base class. Valid subclasses are appended to a list
    which is then returned.

    Args:
        base (type): The base class that the discovered classes must be a subclass of.
        group (str): The name of the entry point group to search within.

    Returns:
        list[type]: A list of classes found in the entry points that subclass the base class.
    """
    classes: list[type] = []

    for ep in entry_points().select(group=group):
        obj = ep.load()
        if not inspect.isclass(obj) or not issubclass(obj, base):
            continue
        classes.append(obj)

    return classes


def load_strategies_base(
        *,
        base: type,
        package_name: str,
        entrypoint_group: str,
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list[Any]:
    """
    Loads and prioritizes strategies based on explicit order or precedence.

    This function is responsible for dynamically loading strategy classes from
    the provided package or entry point group. It allows for customizing the
    order of strategies through a specified explicit order or precedence
    values. The function will return a list of strategy class instances,
    sorted according to the provided conditions.

    Args:
        base: The base type that all strategy classes must inherit from.
        package_name: The name of the package to search for built-in strategies.
        entrypoint_group: The entry point group to search for dynamically-loaded strategies.
        ordered_names: An optional iterable specifying a strict order of strategy names to be loaded
            first. If provided, only these strategies are loaded in the specified order, followed
            by strategies not explicitly listed but sorted by precedence.
        precedence_overrides: An optional mapping that overrides the precedence values of certain
            strategy classes. Strategies with lower precedence values are prioritized.

    Returns:
        A list of instances of strategy classes, sorted based on the provided explicit order or
        precedence rules.
    """
    classes: list[type] = (
            _builtin_strategy_classes(base, package_name) +
            _entrypoint_strategy_classes(base, entrypoint_group))

    # map name -> class
    by_name: dict[str, type] = {}
    for cls in classes:
        name = getattr(cls, "name", cls.__name__)
        by_name[name] = cls

    # explicit order mode
    if ordered_names is not None:
        instances: list[Any] = []

        for name in ordered_names:
            selected = by_name.get(name)
            if selected is not None:
                instances.append(selected())
                del by_name[name]

        remaining: list[tuple[int, str, Any]] = []
        for name, cls in by_name.items():
            prec = getattr(cls, "precedence", 100)
            if precedence_overrides and name in precedence_overrides:
                prec = precedence_overrides[name]
            remaining.append((prec, name, cls()))

        remaining.sort(key=lambda t: (t[0], t[1]))
        instances.extend(inst for _p, _n, inst in remaining)

        return instances

    # precedence-only mode
    ranked: list[tuple[int, str, Any]] = []
    for cls in classes:
        name = getattr(cls, "name", cls.__name__)
        prec = getattr(cls, "precedence", 100)
        if precedence_overrides and name in precedence_overrides:
            prec = precedence_overrides[name]
        ranked.append((prec, name, cls()))

    ranked.sort(key=lambda t: (t[0], t[1]))
    return [inst for _p, _n, inst in ranked]
