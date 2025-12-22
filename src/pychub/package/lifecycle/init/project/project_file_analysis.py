from __future__ import annotations

from pathlib import Path

from pychub.helper.toml_utils import load_toml_file
from pychub.package.lifecycle.audit.build_event_model import audit, StageType, EventType, LevelType, BuildEvent
from pychub.package.lifecycle.init.project.project_path_strategy import ProjectPathStrategy, load_strategies
from pychub.package.packaging_context_vars import current_packaging_context


@audit(StageType.INIT, substage="collect_path_dependency_wheel_locations")
def collect_path_dependency_wheel_locations(project_paths: set[Path]) -> set[Path]:
    """
    Collects wheel file locations from the "dist" directories of the specified dependency projects.

    This function checks each input project path for a "dist" directory and collects all `.whl` files
    present in it. If a "dist" directory does not exist in any of the provided paths, an error
    is logged in the build plan audit log.

    Args:
        project_paths (set[Path]): A set of paths representing dependency projects whose wheel file
            locations need to be collected.

    Returns:
        set[Path]: A set containing the paths to the `.whl` files found in the "dist" directories
            of the specified projects.
    """
    build_plan = current_packaging_context.get().build_plan

    wheel_deps = set()
    for project_path in project_paths:
        dist_dir = project_path / "dist"
        if dist_dir.is_dir():
            found_wheels = list(dist_dir.glob("*.whl"))
            if found_wheels:
                wheel_deps.update(found_wheels)
            else:
                raise RuntimeError(f"Dependency project '{project_path}' has no wheel files in 'dist' directory.")
        else:
            build_plan.audit_log.append(
                BuildEvent.make(
                    StageType.INIT,
                    EventType.DISCOVER,
                    LevelType.ERROR,
                    message=f"Dependency project '{project_path}' missing 'dist' directory."))
    return wheel_deps


@audit(StageType.INIT, substage="collect_path_dependencies")
def collect_path_dependencies(
        pyproject_path: Path,
        seen: set[Path] | None = None,
        depth: int = 0) -> set[Path]:
    """
    Collects and resolves path dependencies for a project by analyzing its
    pyproject.toml file and applying appropriate strategies.

    This function iteratively inspects the specified pyproject.toml file and
    recursively resolves dependencies based on the project structure. It supports
    multiple path resolution strategies and ensures each unique project root is
    processed only once.

    Args:
        pyproject_path (Path): The path to the pyproject.toml file to process.
        seen (set[Path] | None): A dictionary to track already processed
            project roots and their corresponding resolution strategy labels. If
            None, a new dictionary will be initialized.
        depth (int): The current recursion depth used for logging purposes.

    Returns:
        set[Path]: A set containing resolved project roots.
    """
    build_plan = current_packaging_context.get().build_plan

    if seen is None:
        seen = set()

    pyproject_path = pyproject_path.resolve()
    project_root = pyproject_path.parent

    if project_root in seen:
        return seen

    data = load_toml_file(pyproject_path)

    strat = None
    strategies: list[ProjectPathStrategy] = load_strategies()
    for s in strategies:
        if s.can_handle(data):
            strat = s
            break

    if not strat:
        raise RuntimeError(f"No strategies matched for project at: {project_root}")
    else:
        build_plan.audit_log.append(
            BuildEvent.make(
                StageType.INIT,
                EventType.DISCOVER,
                message=f"Project path dependency strategy selected for {project_root}: {strat.name}."))

    seen.add(project_root)
    dep_paths = strat.extract_paths(data, project_root)

    if dep_paths:
        for dep_path in dep_paths:
            dep_py = dep_path / "pyproject.toml"
            if dep_py.is_file():
                collect_path_dependencies(dep_py, seen, depth + 1)
            else:
                raise RuntimeError(f"Path dependency project '{dep_path}' missing pyproject.toml")
        build_plan.audit_log.append(
            BuildEvent.make(
                StageType.INIT,
                EventType.DISCOVER,
                message=f"Found path dependencies in {', '.join([str(p) for p in dep_paths])}."))

    return seen


@audit(StageType.INIT, substage="analyze_project")
def analyze_project():
    build_plan = current_packaging_context.get().build_plan
    path_deps = collect_path_dependencies(build_plan.project_dir / "pyproject.toml")
    path_dep_wheel_locations = collect_path_dependency_wheel_locations(path_deps - {build_plan.project_dir})
    build_plan.path_dep_wheel_locations.update(path_dep_wheel_locations)
