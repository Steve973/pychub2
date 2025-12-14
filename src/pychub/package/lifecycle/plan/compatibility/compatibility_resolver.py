from __future__ import annotations

from pychub.package.context_vars import current_packaging_context
from pychub.package.domain.compatibility_model import WheelKey, CompatibilitySpec
from pychub.package.domain.project_model import ChubProject
from pychub.package.lifecycle.plan.compatibility.compatibility_spec_loader import load_compatibility_spec
from pychub.package.lifecycle.plan.compatibility.python_version_discovery import \
    list_all_available_python_versions


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
    available_python_versions = list_all_available_python_versions()
    build_plan.resolved_python_versions = available_python_versions
    chubproject: ChubProject = build_plan.project
    spec: CompatibilitySpec = load_compatibility_spec(chubproject)
    build_plan.compatibility_spec = spec
    return spec


def resolve_compatibility():
    build_plan = current_packaging_context.get().build_plan
    spec = init_compatibility_for_plan()
