import sys
from importlib.metadata import PackageNotFoundError, version as get_version
from pathlib import Path

from pychub.package.domain.project_model import ChubProject
from pychub.package.lifecycle.audit.build_event_model import StageType, audit


@audit(StageType.EXECUTE, substage="execute_analyze_compatibility")
def execute_analyze_compatibility(chubproject: ChubProject):
    """
    Executes analysis of compatibility for the given ChubProject and resolves the
    common compatibility targets. Constructs the staged wheels directory, reuses
    the resolver to discover strategies, and validates compatibility of resolved
    wheels.

    Args:
        chubproject (ChubProject): The ChubProject instance containing the wheel
            files for which compatibility analysis will be performed.

    Raises:
        RuntimeError: If there is no active BuildPlan in the current context during
            compatibility analysis.
    """
    pass


@audit(StageType.EXECUTE, substage="execute_chubproject_save")
def execute_chubproject_save(chubproject: ChubProject, path: Path | str):
    ChubProject.save_file(chubproject, path, overwrite=True, make_parents=True)


@audit(StageType.EXECUTE, substage="execute_version")
def execute_version():
    print(f"Python: {sys.version.split()[0]}")
    try:
        version = get_version("pychub")
    except PackageNotFoundError:
        version = "(source)"
    print(f"pychub: {version}")
