from __future__ import annotations

from collections.abc import Mapping, Collection, Iterator, Sequence
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Any, Iterable

from packaging.requirements import Requirement as PkgRequirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from resolvelib import Resolver, ResolutionImpossible, BaseReporter
from resolvelib.providers import AbstractProvider, Preference
from resolvelib.resolvers import Criterion
from resolvelib.structs import RequirementInformation, State, Matches

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.helper.wheel_tag_utils import choose_wheel_tag
from pychub.package.domain.compatibility_model import CompatibilitySpec, WheelKeyMetadata
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.domain.project_model import ChubProject
from pychub.package.lifecycle.audit.build_event_model import BuildEvent, EventType, StageType, LevelType
from pychub.package.lifecycle.plan.compatibility.compatibility_spec_loader import load_compatibility_spec
from pychub.package.lifecycle.plan.resolution.artifact_resolution import _wheel_filename_from_uri
from pychub.package.lifecycle.plan.resolution.resolution_context_vars import ResolutionContext, \
    current_resolution_context
from pychub.package.packaging_context_vars import current_packaging_context


@dataclass(frozen=True, slots=True)
class OsMarkerProfile:
    """
    Represents a profile containing OS marker data following PEP 508 specifications.

    This class is a data structure designed to store platform-specific information
    used for identifying or matching operating systems. The attributes in this class
    align with the fields defined in the PEP 508 environment markers, such as
    `sys_platform`, `platform_system`, and `os_name`.

    Attributes:
        sys_platform (str): Represents the `sys_platform` value from PEP 508,
            typically identifying the platform (e.g., 'win32', 'linux').
        platform_system (str): Represents the `platform_system` value from PEP 508,
            typically identifying the operating system name (e.g., 'Windows', 'Linux').
        os_name (str): Represents the `os_name` value from PEP 508,
            typically aligning with the `os.name` field in Python (e.g., 'posix', 'nt').
    """
    sys_platform: str  # PEP 508: sys_platform
    platform_system: str  # PEP 508: platform_system
    os_name: str  # PEP 508: os_name


@dataclass(frozen=True, slots=True)
class ImplMarkerProfile:
    """
    Represents a marker profile containing implementation details.

    This class is designed to encapsulate specific implementation details compliant with
    PEP 508. It provides information about the implementation name and the Python
    platform implementation in a structured and immutable format due to its frozen
    nature.

    Attributes:
        implementation_name (str): The name of the Python implementation in
            lowercase as per PEP 508 (e.g., "cpython").
        platform_python_implementation (str): The human-readable name of the Python
            platform implementation as per PEP 508 (e.g., "CPython").
    """
    implementation_name: str  # PEP 508: implementation_name (lowercase)
    platform_python_implementation: str  # PEP 508: platform_python_implementation (pretty)


_OS_PREFIX_TO_FAMILY: dict[str, str | None] = {
    "any": None,
    "linux": "linux",
    "macosx": "macos",
    "manylinux": "linux",
    "musllinux": "linux",
    "win": "windows",
}

_IMPL_PREFIX_TO_NAME: dict[str, str] = {
    "cp": "cpython",
    "pp": "pypy",
    # "py" intentionally omitted: doesn't encode implementation
}

OS_FAMILY_MARKER_PROFILES: dict[str, OsMarkerProfile] = {
    "linux": OsMarkerProfile(sys_platform="linux", platform_system="Linux", os_name="posix"),
    "windows": OsMarkerProfile(sys_platform="win32", platform_system="Windows", os_name="nt"),
    "macos": OsMarkerProfile(sys_platform="darwin", platform_system="Darwin", os_name="posix"),
}

DEFAULT_OS_MARKER_PROFILE = OsMarkerProfile(sys_platform="unknown", platform_system="Unknown", os_name="posix")

IMPL_MARKER_PROFILES: dict[str, ImplMarkerProfile] = {
    "cp": ImplMarkerProfile("cpython", "CPython"),
    "cpython": ImplMarkerProfile("cpython", "CPython"),
    "pp": ImplMarkerProfile("pypy", "PyPy"),
    "pypy": ImplMarkerProfile("pypy", "PyPy"),
}


def _fallback_impl_profile(raw_impl: str) -> ImplMarkerProfile:
    # Keep it deterministic, no fancy heuristics.
    impl = (raw_impl or "").strip().lower() or "unknown"
    return ImplMarkerProfile(implementation_name=impl, platform_python_implementation=impl.capitalize())


def pep691_project_lookup_key(project_name: str) -> WheelKey:
    return WheelKey(project_name, "0")


_ANY_PLATFORM = "any"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolverRequirement(MultiformatModelMixin):
    """
    A resolvelib requirement: "what I need" (name + version constraints + optional extras).

    Context (tag, arch, os, python version) is provided by the current ResolutionContext
    via ContextVar, not stored here.
    """
    project_name: str
    specifier_set: SpecifierSet = SpecifierSet()
    extras: frozenset[str] = frozenset()

    @property
    def normalized_name(self) -> str:
        return canonicalize_name(self.project_name)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "specifier_set": str(self.specifier_set),
            "extras": sorted(self.extras),
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolverRequirement:
        return cls(
            project_name=str(mapping["project_name"]),
            specifier_set=SpecifierSet(str(mapping.get("specifier_set") or "")),
            extras=frozenset(mapping.get("extras") or []))


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolverCandidate(MultiformatModelMixin):
    """
    A resolvelib candidate: "a concrete pick" for a requirement (name + one version),
    plus optional per-context artifact info (download_url) if you choose to carry it.

    Dependencies are discovered through metadata resolution, not stored here.
    """
    project_name: str
    version: Version

    # Optional metadata that can help short-circuit / debugging:
    requires_python: str | None = None

    # Optional: if you pick a concrete wheel URL for the current context tag during candidate
    # selection, you can store it here. If you don't, leave it None and resolve later.
    download_url: str | None = None

    @property
    def normalized_name(self) -> str:
        return canonicalize_name(self.project_name)

    @property
    def wheel_key(self) -> WheelKey:
        return WheelKey(self.project_name, str(self.version))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "version": str(self.version),
            "requires_python": self.requires_python,
            "download_url": self.download_url,
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolverCandidate:
        return cls(
            project_name=str(mapping["project_name"]),
            version=Version(str(mapping["version"])),
            requires_python=mapping.get("requires_python"),
            download_url=mapping.get("download_url"))


def _safe_resolution_ctx_payload() -> dict[str, Any]:
    try:
        ctx: str = current_resolution_context.get().context_key
    except LookupError:
        return {"resolution_context": "not available"}
    return {"resolution_context": ctx}


def _audit(*, substage: str, message: str, payload: dict[str, Any] | None = None):
    audit_log = current_packaging_context.get().build_plan.audit_log
    merged = {}
    merged.update(_safe_resolution_ctx_payload())
    if payload:
        merged.update(payload)

    audit_log.append(
        BuildEvent.make(
            StageType.PLAN,
            EventType.RESOLVE,
            level=LevelType.DEBUG,
            substage=substage,
            message=message,
            payload=merged))


class PychubReporter(BaseReporter[ResolverRequirement, ResolverCandidate, str]):
    """
    Handles the reporting and auditing tasks during a resolution process.

    This class is responsible for generating audits for the various stages
    of a resolution process. It provides methods for logging the start and
    end of the resolution, handling requirement additions, pinning candidates,
    rejecting candidates, and resolving conflicts. It serves as a specialized
    reporter for tracking detailed audit information needed in the resolution
    workflow.
    """

    def starting(self) -> None:
        _audit(substage="starting",
               message="resolution starting")

    def starting_round(self, index: int) -> None:
        _audit(substage="starting_round",
               message=f"starting round {index}",
               payload={"round": index})

    def ending_round(self, index: int, state: State[ResolverRequirement, ResolverCandidate, str]) -> None:
        _audit(substage="ending_round",
               message=f"ending round {index}",
               payload={"round": index})

    def ending(self, state) -> None:
        _audit(substage="ending",
               message="resolution ending")

    def adding_requirement(self, requirement, parent) -> None:
        _audit(substage="add_requirement",
               message=f"adding requirement: {requirement}",
               payload={"parent": parent})

    def pinning(self, candidate) -> None:
        _audit(substage="pin",
               message=f"pinning candidate: {candidate}")

    def rejecting_candidate(
            self, criterion: Criterion[ResolverRequirement, ResolverCandidate],
            candidate: ResolverCandidate) -> None:
        _audit(substage="reject",
               message=f"rejecting candidate: {candidate} (criterion={criterion})")

    def resolving_conflicts(
            self,
            causes: Collection[RequirementInformation[ResolverRequirement, ResolverCandidate]]) -> None:
        _audit(
            substage="resolving_conflicts",
            message="resolving conflicts",
            payload={"causes": [str(c) for c in causes]})


class PychubResolverProvider(AbstractProvider[ResolverRequirement, ResolverCandidate, str]):
    """
    Provides a resolver provider implementation for PyChub that interacts
    with packaging metadata and dependency resolution to supply resolver
    requirements and candidates.

    This class facilitates candidate identification, preference scoring,
    candidate matching, and dependency retrieval using a combination of
    PEP 691 metadata and PEP 658 metadata. Specifically designed for
    resolving packages within the PyChub ecosystem, it enables robust
    compatibility checking and stable ordering of candidate matches.
    """

    def __init__(self):
        pkg_ctx = current_packaging_context.get()
        self._pep691 = pkg_ctx.pep691_resolver
        self._pep658 = pkg_ctx.pep658_resolver

    def identify(self, requirement_or_candidate: Any) -> str:
        # resolvelib wants a stable identifier for "this project"
        return canonicalize_name(requirement_or_candidate.project_name)

    def get_preference(
            self,
            identifier: str,
            resolutions: Mapping[str, ResolverCandidate],
            candidates: Mapping[str, Iterator[ResolverCandidate]],
            information: Mapping[str, Iterator[RequirementInformation[ResolverRequirement, ResolverCandidate]]],
            backtrack_causes: Sequence[RequirementInformation[ResolverRequirement, ResolverCandidate]]) -> Preference:
        return 0

    def find_matches(
            self,
            identifier: str,
            requirements: Mapping[str, Iterator[ResolverRequirement]],
            incompatibilities: Mapping[str, Iterator[ResolverCandidate]]) -> Matches[ResolverCandidate]:
        """
        Finds matches for the given identifier by combining requirement constraints, excluding
        incompatible candidates, and ranking candidates based on their compatibility and
        desirability within the current context.

        Args:
            identifier (str): The unique identifier for which matching candidates are being resolved.
            requirements (Mapping[str, Iterator[ResolverRequirement]]): A mapping of identifiers
                to iterables of requirements that specify constraints on acceptable candidates.
            incompatibilities (Mapping[str, Iterator[ResolverCandidate]]): A mapping of identifiers
                to iterables of candidates that are explicitly marked as incompatible.

        Returns:
            Matches[ResolverCandidate]: A list of resolved candidates, ordered by their
            desirability and compatibility with the constraints and context.
        """
        # Combine all specifier constraints for *this* identifier
        req_iter = requirements.get(identifier, iter(()))
        req_list = list(req_iter)

        spec: SpecifierSet | None = None
        for r in req_list:
            spec = r.specifier_set if spec is None else (spec & r.specifier_set)
        if spec is None:
            spec = SpecifierSet()

        # Materialize banned candidates for this identifier
        banned = set(incompatibilities.get(identifier, iter(())))

        meta_entry = self._pep691.resolve(wheel_key=pep691_project_lookup_key(identifier))
        if meta_entry is None:
            return []

        from pychub.package.domain.compatibility_model import Pep691Metadata
        project_meta = Pep691Metadata.from_file(path=meta_entry.path, fmt="json")

        ctx = current_resolution_context.get()

        # Accept if the wheel matches ANY tag in ctx.tags
        accepted = ctx.tags

        # Prefer the most universal tag first: py3-none-any, then py313-none-any, then everything else
        t_py_major = Tag(f"py{ctx.python_version.major}", "none", "any")
        t_py_minor = Tag(f"py{ctx.python_version.major}{ctx.python_version.minor}", "none", "any")

        preferred: list[Tag] = [t_py_major, t_py_minor] + sorted(
            (t for t in accepted if t not in {t_py_major, t_py_minor}),
            key=str
        )
        rank_by_tag: dict[Tag, int] = {t: i for i, t in enumerate(preferred)}
        best_url_by_version: dict[Version, str] = {}
        best_rank_by_version: dict[Version, int] = {}
        best_filename_by_version: dict[Version, str] = {}

        for f in project_meta.files:
            if f.yanked or not f.filename.endswith(".whl") or not f.url:
                continue

            try:
                _, v, _, tagset = parse_wheel_filename(f.filename)
            except Exception:
                continue

            ver = Version(str(v))
            if ver not in spec:
                continue

            # Compute the best (lowest) rank among the wheel's tags that are acceptable for this context
            best_rank = None
            for t in tagset:
                rank = rank_by_tag.get(t)
                if rank is None:
                    continue
                if best_rank is None or rank < best_rank:
                    best_rank = rank

            if best_rank is None:
                continue  # wheel doesn't match any acceptable tag for this context

            existing_rank = best_rank_by_version.get(ver)
            if existing_rank is None:
                best_rank_by_version[ver] = best_rank
                best_filename_by_version[ver] = f.filename
                best_url_by_version[ver] = f.url
                continue

            # Prefer lower rank (more universal); tiebreak by filename
            if best_rank < existing_rank or (best_rank == existing_rank and f.filename < best_filename_by_version[ver]):
                best_rank_by_version[ver] = best_rank
                best_filename_by_version[ver] = f.filename
                best_url_by_version[ver] = f.url

        # Emit candidates in a stable order (the newest first tends to reduce backtracking)
        matches: list[ResolverCandidate] = []
        for ver in sorted(best_url_by_version.keys(), reverse=True):
            cand = ResolverCandidate(project_name=identifier, version=ver, download_url=best_url_by_version[ver])
            if cand not in banned:
                matches.append(cand)

        return matches

    def is_satisfied_by(self, requirement: ResolverRequirement, candidate: ResolverCandidate) -> bool:
        if candidate.normalized_name != requirement.normalized_name:
            return False
        return candidate.version in requirement.specifier_set

    def get_dependencies(self, candidate: ResolverCandidate) -> list[ResolverRequirement]:
        """
        Expand dependencies for a chosen candidate under the current context.
        This is where marker evaluation happens.
        """
        if not candidate.download_url:
            return []

        ctx = current_resolution_context.get()
        wk = candidate.wheel_key
        filename = _wheel_filename_from_uri(candidate.download_url)

        try:
            _, _, _, tagset = parse_wheel_filename(filename)
        except Exception:
            return []

        actual_tag = choose_wheel_tag(filename=filename, name=wk.name, version=wk.version)
        accepted = ctx.tags or frozenset()
        satisfied = frozenset(str(t) for t in tagset if t in accepted)
        wk.set_metadata(
            WheelKeyMetadata(
            actual_tag=actual_tag,
            satisfied_tags=satisfied,
            origin_uri=candidate.download_url))

        entry = self._pep658.resolve(wheel_key=wk, uri=candidate.download_url)
        if entry is None:
            return []

        _, requires_dist_lines = _parse_core_metadata(entry.path)
        env = _marker_environment()
        deps: list[ResolverRequirement] = []
        for line in requires_dist_lines:
            try:
                req = PkgRequirement(line)
            except Exception:
                continue

            if req.marker is not None and not req.marker.evaluate(env):
                continue

            deps.append(
                ResolverRequirement(
                    project_name=req.name,
                    specifier_set=req.specifier,
                    extras=frozenset(req.extras)))

        return deps


def _accepted_tags_for_context(*, python_version: Version, context_tag: Tag) -> frozenset[Tag]:
    major = python_version.major
    minor = python_version.minor
    return frozenset({
        context_tag,
        Tag(f"py{major}", "none", "any"),
        Tag(f"py{major}{minor}", "none", "any"),
    })


def _parse_core_metadata(path: Path) -> tuple[str | None, list[str]]:
    """
    Parses METADATA-like content (PEP 658 sidecar, or extracted dist-info METADATA).
    Returns: (requires_python, requires_dist_lines)
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    msg = Parser().parsestr(text)
    requires_python = msg.get("Requires-Python")
    requires_dist = msg.get_all("Requires-Dist") or []
    return requires_python, list(requires_dist)


def _marker_environment() -> dict[str, str]:
    ctx = current_resolution_context.get()
    py_ver = ctx.python_version
    os_key = (ctx.os_family or "").strip().lower()
    os_profile = OS_FAMILY_MARKER_PROFILES.get(os_key, DEFAULT_OS_MARKER_PROFILE)
    impl_key = (ctx.python_implementation or "").strip().lower()
    impl_profile = IMPL_MARKER_PROFILES.get(impl_key, _fallback_impl_profile(impl_key))

    return {
        "python_version": f"{py_ver.major}.{py_ver.minor}",
        "python_full_version": str(py_ver),
        "implementation_name": impl_profile.implementation_name,
        "platform_python_implementation": impl_profile.platform_python_implementation,
        "platform_system": os_profile.platform_system,
        "sys_platform": os_profile.sys_platform,
        "os_name": os_profile.os_name,
        "platform_machine": ctx.arch,
    }


def _first_prefix_match(value: str, prefix_map: dict[str, str | None]) -> str | None:
    for prefix in sorted(prefix_map.keys(), key=len, reverse=True):
        if value.startswith(prefix):
            return prefix_map[prefix]
    return None


def _os_family_from_platform(platform: str) -> str | None:
    return _first_prefix_match(platform, _OS_PREFIX_TO_FAMILY)


def _arch_from_platform(platform: str) -> str | None:
    if platform == _ANY_PLATFORM:
        return None
    parts = platform.split("_")
    return parts[-1] if parts else None


def _impl_from_interpreter(interpreter: str) -> str | None:
    if not interpreter:
        return None
    key = interpreter.lower()
    prof = IMPL_MARKER_PROFILES.get(key) or IMPL_MARKER_PROFILES.get(key[:2])
    return prof.implementation_name if prof else None


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
    seen: set[str] = set()

    def add_ctx(ctx: ResolutionContext) -> None:
        # CHANGE: The model already defines a stable context_key, so use it.
        key = ctx.context_key
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

            # Validate arch is allowed for that OS family (if arch list is provided)
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
                        tags=_accepted_tags_for_context(python_version=v, context_tag=tag)))
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
                                tags=_accepted_tags_for_context(python_version=v, context_tag=tag)))

    out.sort(key=lambda c: c.context_key)
    return out


def build_dependency_metadata_tree() -> None:
    processed: set[tuple[str, str, str]] = set()
    pkg_ctx = current_packaging_context.get()
    build_plan = pkg_ctx.build_plan

    provider = PychubResolverProvider()
    reporter = PychubReporter()
    resolver = Resolver(provider=provider, reporter=reporter)

    for resolution_ctx in build_plan.resolution_contexts:
        token = current_resolution_context.set(resolution_ctx)
        try:
            # Build all roots for this context in one call (resolvelib supports multiple roots)
            root_reqs: list[ResolverRequirement] = []
            for root_wheel in build_plan.wheels:
                root_reqs.append(
                    ResolverRequirement(
                        project_name=root_wheel.name,
                        specifier_set=SpecifierSet(f"=={root_wheel.version}")))

            try:
                result = resolver.resolve(root_reqs)
            except ResolutionImpossible as e:
                # record failure on resolution_ctx.result here
                # resolution_ctx.result.status = FAILED, detail=str(e) ...
                continue

            # result.mapping: {identifier -> ResolverCandidate}
            # result.graph: directed graph of decisions (handy for auditing)
            mapping = result.mapping

            # TODO: turn `mapping` into your persisted graph/node model (ResolvedWheelNode, etc.)
            # This is where you'd populate your dependency tree structure in the BuildPlan.

        finally:
            current_resolution_context.reset(token)


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
