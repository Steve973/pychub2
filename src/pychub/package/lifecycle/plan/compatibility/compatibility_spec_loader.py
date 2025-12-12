from __future__ import annotations

from collections.abc import Mapping as Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from pychub.helper.toml_utils import load_toml_text
from pychub.package.context_vars import current_build_plan
from pychub.package.domain.compatibility_model import CompatibilitySpec
from pychub.package.domain.project_model import ChubProject
from pychub.package.lifecycle.audit.build_event_model import BuildEvent, StageType, EventType, LevelType

_DEFAULT_SPEC_RESOURCE_PACKAGE = "pychub.package.lifecycle.plan.compatibility"
_DEFAULT_SPEC_RESOURCE_NAME = "compatibility_spec.toml"


def _spec_override(
        base: Mapping[str, Any],
        override: Mapping[str, Any]) -> dict[str, Any]:
    """
    Recursively merges two mappings, overriding values in the base mapping with
    those from the override mapping. If both values corresponding to the same key
    are mappings, their values are also recursively merged.

    Args:
        base: The base mapping to be merged.
        override: The mapping containing values that will override those in the
            base mapping.

    Returns:
        A dictionary representing the result of merging the base and override
        mappings.
    """
    result: dict[str, Any] = dict(base)
    for key, o_val in override.items():
        b_val = result.get(key)
        if isinstance(b_val, Mapping) and isinstance(o_val, Mapping):
            result[key] = _spec_override(b_val, o_val)
        else:
            result[key] = o_val
    return result


def _spec_merge(
        base: Mapping[str, Any],
        override: Mapping[str, Any]) -> dict[str, Any]:
    """
    Merges two mappings recursively, combining values from both mappings based
    on specific rules. The merging prioritizes the `override` mapping over the
    `base` mapping.

    Lists in the mappings are merged with items from the `override` mapping
    appended to the list of the `base` mapping, avoiding duplication. Nested
    mappings are recursively merged.

    Args:
        base (Mapping[str, Any]): The base mapping to be merged into.
        override (Mapping[str, Any]): The mapping whose values will override or
            supplement the base mapping.

    Returns:
        dict[str, Any]: A new dictionary obtained by merging the two input mappings.
    """
    result: dict[str, Any] = dict(base)
    for key, o_val in override.items():
        b_val = result.get(key)

        if isinstance(b_val, Mapping) and isinstance(o_val, Mapping):
            result[key] = _spec_merge(b_val, o_val)
        elif isinstance(b_val, list) and isinstance(o_val, list):
            # defaults first, then any file items not already present
            result[key] = b_val + [x for x in o_val if x not in b_val]
        else:
            result[key] = o_val

    return result


def _load_default_spec_mapping() -> Mapping[str, Any]:
    """
    Loads the default specification mapping from a predefined resource.

    This function reads a TOML file from the specified resource package and parses
    its contents to generate a mapping of specifications. The function is
    responsible for ensuring that the resource file is read in UTF-8 encoding.

    Returns:
        Mapping[str, Any]: A mapping representing the parsed specifications from
        the TOML resource.
    """
    text = (
        resources.files(_DEFAULT_SPEC_RESOURCE_PACKAGE)
        .joinpath(_DEFAULT_SPEC_RESOURCE_NAME)
        .read_text(encoding="utf-8")
    )
    return load_toml_text(text)


def _load_file_spec_mapping(path: Path) -> Mapping[str, Any]:
    """
    Loads a TOML file and returns its contents as a mapping. This function
    ensures the file exists before reading and parsing its contents.

    Args:
        path (Path): The file path to the TOML file to be loaded.

    Returns:
        Mapping[str, Any]: The parsed contents of the TOML file.

    Raises:
        FileNotFoundError: If the specified file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Compatibility spec file not found: {path}")
    return load_toml_text(path.read_text(encoding="utf-8"))


def _load_effective_compatibility_spec(
    *,
    strategy_name: str,
    user_spec_path: Path | None,
    inline_overrides: Mapping[str, Any] | None) -> CompatibilitySpec:
    """
    Loads the effective compatibility specification by overlaying default settings,
    user-provided file configurations, and potential inline overrides in a specific
    precedence order.

    This function combines three sources to create an effective compatibility
    specification: embedded defaults, an optional user specification file, and
    optional inline overrides. Inline overrides always take the highest precedence,
    followed by the user specification file, and then the embedded defaults. It
    ensures that the resulting specification takes all these sources into account
    and is enriched with a clear source description.

    Args:
        strategy_name (str): Strategy for merging the specifications. Can either
            be "override" or "merge". If an invalid strategy is given, it should
            already be normalized by the caller.
        user_spec_path (Path | None): Path to the user specification file. If
            None, this step will be skipped.
        inline_overrides (Mapping[str, Any] | None): Inline overrides to apply
            on top of the specifications. These overrides always take the highest
            precedence.

    Returns:
        CompatibilitySpec: The resulting compatibility specification object
        created by merging the given sources.
    """
    # 1) Start from embedded defaults
    default_map = _load_default_spec_mapping()
    merged_map: dict[str, Any] = dict(default_map)

    source_parts: list[str] = [
        f"embedded:{_DEFAULT_SPEC_RESOURCE_PACKAGE}/{_DEFAULT_SPEC_RESOURCE_NAME}"
    ]

    # 2) Overlay file spec, if present
    if user_spec_path is not None:
        file_map = _load_file_spec_mapping(user_spec_path)

        if strategy_name == "override":
            merged_map = _spec_override(merged_map, file_map)
            source_parts.append(f"file:{user_spec_path} (override)")
        else:
            # "merge" (or anything invalid that you already normalized in the caller)
            merged_map = _spec_merge(merged_map, file_map)
            source_parts.append(f"file:{user_spec_path} (merge)")

    # 3) Apply inline overrides (the highest precedence, always full override semantics)
    if inline_overrides:
        merged_map = _spec_override(merged_map, inline_overrides)
        source_parts.append("inline:project_toml")

    # 4) Build the spec object
    spec = CompatibilitySpec.from_mapping(merged_map)

    # Let this override whatever fmt:path the mixin might have guessed
    try:
        spec.source_description = " + ".join(source_parts)
    except AttributeError:
        pass

    return spec


def load_compatibility_spec(chubproject: ChubProject | None) -> CompatibilitySpec:
    """
    Loads the compatibility specification from a given project TOML file, if present. The
    function extracts settings such as the combination strategy, user-specified file, and
    any inline overrides. If no project TOML file is provided, default values are used.

    Args:
        chubproject (ChubProject | None): The Chub project instance to load the specification.

    Returns:
        CompatibilitySpec: A compatibility specification combining inputs from the project
        TOML file, specified user file, and inline overrides.

    Raises:
        ValueError: If the combination strategy specified in the TOML file is invalid.
    """
    build_plan = current_build_plan.get()
    combine_strategy: str = "merge"
    user_spec_path: Path | None = None
    inline_overrides: Mapping[str, Any] | None = None

    # Read the compatibility block from the project toml, if present
    if chubproject is not None:
        compat_block: dict[str, Any] = dict(chubproject.compatibility_spec or {})
        # Get the specified strategy or default to "merge"
        raw_strategy = compat_block.pop("strategy", "merge")
        if raw_strategy not in ("merge", "override"):
            build_plan.audit_log.append(
                BuildEvent.make(
                    StageType.PLAN,
                    EventType.RESOLVE,
                    LevelType.WARN,
                    message=(
                        f"CompatibilitySpec combination strategy '{raw_strategy}' must be "
                        "'merge' or 'override'; defaulting to 'merge'.")))
        else:
            combine_strategy = raw_strategy

        # A specified file has higher priority than the defaults
        raw_file = compat_block.pop("file", None)
        if isinstance(raw_file, str) and raw_file.strip():
            candidate = Path(raw_file)
            if not candidate.is_absolute():
                candidate = build_plan.project_dir / candidate
            user_spec_path = candidate

        # The highest precedence is from inline overrides
        inline_overrides = dict(compat_block) or None

    return _load_effective_compatibility_spec(
        strategy_name=combine_strategy,
        user_spec_path=user_spec_path,
        inline_overrides=inline_overrides)
