from __future__ import annotations

from collections.abc import Iterable

from packaging.version import Version

from pychub.package.domain.compatibility_model import WheelKey, CompatibilitySpec
from pychub.package.domain.project_model import ChubProject
from pychub.package.lifecycle.plan.compatibility.compatibility_spec_loader import load_compatibility_spec
from pychub.package.lifecycle.plan.resolution.resolution_context_vars import ResolutionContext
from pychub.package.packaging_context_vars import current_packaging_context

_OS_PREFIX_TO_FAMILY: dict[str, str] = {
    "manylinux": "linux",
    "musllinux": "linux",
    "linux": "linux",
    "win": "windows",
    "macosx": "macos",
}

_IMPL_PREFIX_TO_NAME: dict[str, str] = {
    "cp": "cpython",
    "pp": "pypy",
    # "py" intentionally omitted: doesn't encode implementation
}

_ANY_PLATFORM = "any"


def _first_prefix_match(value: str, prefix_map: dict[str, str]) -> str | None:
    for prefix in sorted(prefix_map.keys(), key=len, reverse=True):
        if value.startswith(prefix):
            return prefix_map[prefix]
    return None


def _os_family_from_platform(platform: str) -> str | None:
    if platform == _ANY_PLATFORM:
        return None
    return _first_prefix_match(platform, _OS_PREFIX_TO_FAMILY)


def _arch_from_platform(platform: str) -> str | None:
    if platform == _ANY_PLATFORM:
        return None
    parts = platform.split("_")
    return parts[-1] if parts else None


def _impl_from_interpreter(interpreter: str) -> str | None:
    if len(interpreter) < 2:
        return None
    return _IMPL_PREFIX_TO_NAME.get(interpreter[:2])


def _parse_interpreter_major_minor(interpreter: str) -> tuple[int | None, int | None] | None:
    """
    Returns (major, minor) where minor may be None when only major is implied.

    Examples:
      cp311 -> (3, 11)
      cp310 -> (3, 10)
      cp39  -> (3, 9)
      py3   -> (3, None)
      py311 -> (3, 11)
      pp39  -> (3, 9)
    """
    if len(interpreter) < 3:
        return None

    prefix = interpreter[:2]
    digits = interpreter[2:]
    if not digits.isdigit():
        return None

    # general: the first digit is major, and the remainder is minor
    major = int(digits[0])
    minor = int(digits[1:]) if len(digits) >= 2 else None
    return major, minor


def _filter_versions_for_interpreter(interpreter: str, versions: list[Version]) -> list[Version]:
    parsed = _parse_interpreter_major_minor(interpreter)
    if parsed is None:
        return versions

    major, minor = parsed
    if major is None:
        return versions
    if minor is None:
        return [v for v in versions if v.major == major]
    return [v for v in versions if v.major == major and v.minor == minor]


# ----------------------------
# Main expansion
# ----------------------------

def build_resolution_contexts(
        compat_spec: CompatibilitySpec,
        *,
        os_families: Iterable[str] | None = None,
        default_python_implementations: Iterable[str] = ("cpython",)) -> list[ResolutionContext]:
    """
    Expand a *fully populated* CompatibilitySpec into ResolutionContext instances,
    using a tag-first strategy.

    - Start from explicit allowed tags.
    - For each tag, expand only the dimensions it doesn't encode (platform=any, interpreter=py3, etc.).
    - Filter to realized python versions from compat_spec.resolved_python_version_list.
    - Filter arches via compat_spec.platform_values[os_family].arches where possible.
    """
    allowed_tags = sorted(compat_spec.allowed_tags, key=str)

    realized_versions = [Version(v) for v in compat_spec.resolved_python_version_list]
    realized_versions.sort()

    selected_os_families = (
        list(os_families) if os_families is not None else list(compat_spec.platform_values.keys())
    )
    selected_os_families = [osf for osf in selected_os_families if osf in compat_spec.platform_values]

    impl_defaults = list(default_python_implementations)

    out: list[ResolutionContext] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add_ctx(ctx: ResolutionContext) -> None:
        key = (ctx.os_family, ctx.arch, ctx.python_implementation, str(ctx.python_version), str(ctx.tag))
        if key not in seen:
            seen.add(key)
            out.append(ctx)

    for tag in allowed_tags:
        candidate_versions = _filter_versions_for_interpreter(tag.interpreter, realized_versions)
        if not candidate_versions:
            continue

        impl_implied = _impl_from_interpreter(tag.interpreter)

        # Platform-specific tag: use the tag to infer os_family + arch, then validate against spec.
        if tag.platform != _ANY_PLATFORM:
            os_family = _os_family_from_platform(tag.platform)
            if os_family is None or os_family not in selected_os_families:
                continue

            arch = _arch_from_platform(tag.platform)
            if arch is None:
                continue

            # Validate arch is allowed for that OS family (if arches list is provided)
            os_spec = compat_spec.platform_values[os_family]
            if os_spec.arches and arch not in os_spec.arches:
                continue

            impl = impl_implied or impl_defaults[0]

            for v in candidate_versions:
                add_ctx(
                    ResolutionContext(
                        arch=arch,
                        os_family=os_family,
                        python_implementation=impl,
                        python_version=v,
                        tag=tag))
            continue

        # Universal platform tag ("any"): expand across OS family x arch.
        # Also expand implementation if interpreter doesn't imply it.
        impls = [impl_implied] if impl_implied is not None else impl_defaults

        for os_family in selected_os_families:
            os_spec = compat_spec.platform_values[os_family]
            arches = os_spec.arches or []
            if not arches:
                # If you ever want "unknown" arch, do it explicitly; skipping keeps contexts meaningful.
                continue

            for arch in arches:
                for impl in impls:
                    for v in candidate_versions:
                        add_ctx(
                            ResolutionContext(
                                arch=arch,
                                os_family=os_family,
                                python_implementation=impl,
                                python_version=v,
                                tag=tag))

    out.sort(
        key=lambda c: (
            c.os_family,
            c.arch,
            c.python_implementation,
            str(c.python_version),
            str(c.tag)))
    return out


def build_dependency_metadata_tree() -> None:
    """
    Builds the initial tree of resolved wheel nodes by processing the wheel queue.

    This method iterates through the queue of wheels to resolve their dependencies.
    Each wheel is processed to extract metadata and determine its dependencies. These
    dependencies are then resolved and appended to the queue for further processing,
    if not already processed or present. Finally, wheel nodes are created and added
    to the internal nodes data structure.

    Raises:
        ValueError: Raised if a dependency version cannot be determined due
            to an unspecified behavior in `_select_initial_version_for_requirement`.
    """
    processed: set[WheelKey] = set()
    #
    # while self._wheel_queue:
    #     wheel = self._wheel_queue.popleft()
    #
    #     if wheel in processed:
    #         continue
    #     processed.add(wheel)
    #
    #     meta: Pep658Metadata = resolve_pep658_metadata(wheel)
    #     dep_keys: set[WheelKey] = set()
    #
    #     for req_str in meta.requires_dist:
    #         # not sure what to do here with resolvelib
    #         # or if this is how it would work, but this
    #         # whole function is a placeholder
    #         print(f"Resolving dependency {req_str} for {wheel} with resolvelib, somehow!")
    #
    #     node = ResolvedWheelNode(
    #         name=meta.name,
    #         version=meta.version,
    #         requires_python=meta.requires_python or "",
    #         requires_dist=meta.requires_dist,
    #         dependencies=frozenset(dep_keys),
    #         tag_urls=None)
    #
    #     self._nodes[wheel] = node


def init_compatibility_for_plan() -> CompatibilitySpec:
    """
    Initializes and evaluates compatibility for the current build plan.

    This function retrieves the current build plan, loads the compatibility
    specification for the associated chubproject, and creates a compatibility
    evaluator. The evaluator is then assigned to the build plan for later
    use. Finally, the compatibility specification is returned.

    Returns:
        CompatibilitySpec: The compatibility specification corresponding to the
        current build plan's project.
    """
    build_plan = current_packaging_context.get().build_plan
    chubproject: ChubProject = build_plan.project
    spec: CompatibilitySpec = load_compatibility_spec(chubproject)
    spec.realize_python_versions()
    build_plan.compatibility_spec = spec
    resolution_contexts = build_resolution_contexts(spec)
    build_plan.resolution_contexts = resolution_contexts
    return spec


def resolve_compatibility():
    build_plan = current_packaging_context.get().build_plan
    spec = init_compatibility_for_plan()
