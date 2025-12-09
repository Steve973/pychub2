from __future__ import annotations

from pathlib import Path

from pychub.model.build_lifecycle.build_event import audit, StageType
from pychub.package.context_vars import current_build_plan
from pychub.package.lifecycle.plan.compatibility.compatibility_resolver import resolve_compatibility


@audit(StageType.PLAN)
def plan_build(cache_dir: Path) -> Path:
    """
    Constructs and persists a build plan based on the current build configuration.

    This function stages runtime resources needed for building a project,
    including resolving wheels, pre-install scripts, post-install scripts,
    and included files. Once all resources are prepared, the build plan is
    saved as a JSON file in the provided cache directory.

    NOTE: If the user (or project config) explicitly specifies a wheel,
    script, or include, then failure to resolve it is a hard error.

    Args:
        cache_dir (Path): The directory where the build plan and related resources
            will be stored.

    Returns:
        Path: The path to the persisted build plan JSON file.
    """
    build_plan = current_build_plan.get()
    # project = build_plan.project

    # Stage runtime resources:

    # 1. compatibility spec
    resolve_compatibility()

    # # 2. wheels
    # build_plan.wheels = WheelCollection(
    #     set(resolve_wheels_for_project(project.wheels, cache_dir / CHUB_WHEELS_DIR, strategies).values()))
    #
    # # 3. pre-install scripts
    # resolve_pre_install_scripts()
    #
    # # 4. post-install scripts
    # resolve_post_install_scripts()
    #
    # # 5. included files
    # resolve_includes()

    # 6. persist the build plan
    plan_path = cache_dir / "buildplan.json"
    plan_path.write_text(build_plan.to_json(indent=2), encoding="utf-8")

    return plan_path
