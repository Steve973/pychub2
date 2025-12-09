from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, Any

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin

TConfig = TypeVar("TConfig", bound="BaseResolverConfig")


@dataclass(slots=True, frozen=True)
class BaseResolverConfig(MultiformatSerializableMixin, MultiformatDeserializableMixin):
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

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
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
    def from_mapping(
            cls: type[TConfig],
            mapping: Mapping[str, Any],
            **kwargs: Any) -> TConfig:
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
