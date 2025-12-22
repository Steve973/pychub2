from __future__ import annotations

import json
import sys
from argparse import Namespace
from enum import Enum, auto
from pathlib import Path

from appdirs import user_cache_dir

from pychub.package.cli import parse_cli
from pychub.package.constants import CHUBPROJECT_FILENAME
from pychub.package.domain.project_model import ChubProject, SourceKind
from pychub.package.lifecycle.audit.build_event_model import audit, BuildEvent, StageType, EventType
from pychub.package.lifecycle.init import immediate_operations
from pychub.package.lifecycle.init.project.project_file_analysis import analyze_project
from pychub.package.lifecycle.plan.resolution.artifact_resolution import MetadataArtifactResolver, WheelArtifactResolver
from pychub.package.lifecycle.plan.resolution.metadata_strategy import Pep691SimpleApiMetadataStrategy, \
    Pep658SidecarMetadataStrategy, WheelInspectionMetadataStrategy
from pychub.package.lifecycle.plan.resolution.resolution_config_model import WheelResolverConfig, \
    MetadataResolverConfig, FilesystemWheelStrategyConfig, HttpWheelStrategyConfig, \
    Pep691SimpleApiMetadataStrategyConfig, Pep658SidecarMetadataStrategyConfig, WheelInspectionMetadataStrategyConfig
from pychub.package.lifecycle.plan.resolution.wheel_strategy import BaseWheelResolutionStrategy, \
    FilesystemWheelStrategy, HttpWheelStrategy
from pychub.package.packaging_context_vars import current_packaging_context


class ImmediateOutcome(Enum):
    """
    Lists possible immediate outcomes for a process or action.

    This class provides predefined constants that represent the immediate
    result or state of a process or action. It is used primarily to standardize
    the representation of outcomes across different components or instances.

    Attributes:
        NONE: Represents the absence of an outcome or any specific result.
        EXIT: Indicates that the process or action should terminate or exit.
        CONTINUE: Denotes that the process or action should keep proceeding.
    """
    NONE = auto()
    EXIT = auto()
    CONTINUE = auto()


@audit(StageType.INIT, "check_immediate_operations")
def check_immediate_operations(args: Namespace, chubproject: ChubProject) -> ImmediateOutcome:
    """
    Executes immediate operations based on the provided arguments and ChubProject.

    This function determines which immediate operation to execute based on the
    input arguments. It may analyze compatibility, save the ChubProject, or
    display the version information. The function logs the respective operation
    performed as part of the build plan's audit log.

    Args:
        args (Namespace): Command-line arguments that define immediate operations
            to perform, such as analyzing compatibility, saving the ChubProject,
            or displaying version information.
        chubproject (ChubProject): Instance of the ChubProject that will be
            operated upon for the specified immediate action.

    Returns:
        ImmediateOutcome: An enumeration indicating the result of executing
        the immediate operation. It could be EXIT, CONTINUE, or NONE, based
        on the action taken or if no action was performed.
    """
    build_plan = current_packaging_context.get().build_plan
    if args.analyze_compatibility:
        immediate_operations.execute_analyze_compatibility(chubproject)
        build_plan.audit_log.append(
            BuildEvent.make(
                StageType.INIT,
                EventType.ACTION,
                message="Invoked immediate action: analyze compatibility."))
        return ImmediateOutcome.EXIT
    elif args.chubproject_save:
        immediate_operations.execute_chubproject_save(chubproject, args.chubproject_save)
        build_plan.audit_log.append(
            BuildEvent.make(
                StageType.INIT,
                EventType.ACTION,
                message="Invoked immediate action: chubproject save."))
        return ImmediateOutcome.CONTINUE
    elif args.version:
        immediate_operations.execute_version()
        build_plan.audit_log.append(
            BuildEvent.make(
                StageType.INIT,
                EventType.ACTION,
                message="Invoked immediate action: version."))
        return ImmediateOutcome.EXIT
    return ImmediateOutcome.NONE


@audit(StageType.INIT, "create_project_cache")
def cache_project(chubproject: ChubProject) -> Path:
    """
    Caches a given ChubProject by creating a stable hash, ensuring the necessary directories,
    and saving project-related files. This function prepares the ChubProject for later
    build steps by writing the project configuration and metadata into a designated cache
    directory.

    Args:
        chubproject (ChubProject): Instance of ChubProject representing the target project to cache.

    Returns:
        Path: The path to the staging directory where the project cache is stored.
    """
    build_plan = current_packaging_context.get().build_plan

    # Ensure cache_root is set (falls back to user_cache_dir if still default)
    if not build_plan.cache_root:
        build_plan.cache_root = Path(user_cache_dir("pychub"))

    # Compute a stable semantic hash from the ChubProject
    build_plan.project_hash = chubproject.mapping_hash()

    # Ensure the BuildPlan's staging dir exists
    project_staging_dir = build_plan.project_staging_dir
    project_staging_dir.mkdir(parents=True, exist_ok=True)

    # Write chubproject.toml using the model's own save logic
    project_path = project_staging_dir / CHUBPROJECT_FILENAME
    ChubProject.save_file(chubproject, path=project_path, overwrite=True)

    # Write a small meta.json that reflects the BuildPlan state
    (project_staging_dir / "meta.json").write_text(json.dumps(build_plan.meta_json, indent=2))

    return project_staging_dir


@audit(StageType.INIT, "parse_chubproject")
def process_chubproject(chubproject_path: Path) -> ChubProject:
    """
    Parses a Chub project file and returns a ChubProject instance.

    This function processes a given path to a Chub project file, validates its
    existence, and loads its content as a ChubProject instance. If the specified
    file does not exist, an exception is raised.

    Args:
        chubproject_path (Path): The path to the Chub project file to be processed.

    Returns:
        ChubProject: An instance of the ChubProject loaded from the given file.

    Raises:
        FileNotFoundError: If the specified Chub project file does not exist.
    """
    if not chubproject_path.is_file():
        raise FileNotFoundError(f"Chub project file not found: {chubproject_path}")
    return ChubProject.from_file(chubproject_path)


@audit(StageType.INIT, "process_cli_options")
def process_options(args: Namespace) -> ChubProject:
    """
    Processes command-line interface (CLI) options and creates or updates a
    ChubProject instance based on the provided arguments. If a ChubProject file
    is specified, it processes and merges CLI options into the ChubProject,
    otherwise builds a new ChubProject directly from the mapping.

    Args:
        args (Namespace): CLI arguments containing user-specified options
            for ChubProject processing.

    Returns:
        ChubProject: An instance of ChubProject reflecting the merged or
            newly created state based on the provided CLI options.

    """
    cli_mapping = ChubProject.cli_to_mapping(args)
    cli_details = {"argv": sys.argv[1:]}
    if args.chubproject:
        chubproject_path = Path(args.chubproject).expanduser().resolve()
        chubproject = process_chubproject(chubproject_path)
        chubproject.merge_from_mapping(
            cli_mapping,
            source=SourceKind.CLI,
            details=cli_details)
        return chubproject
    else:
        return ChubProject.from_mapping(
            cli_mapping,
            source=SourceKind.CLI,
            details=cli_details)


def _resolver_roots() -> tuple[Path, Path]:
    build_plan = current_packaging_context.get().build_plan
    if not build_plan.cache_root:
        build_plan.cache_root = Path(user_cache_dir("pychub"))
    local_root = build_plan.project_staging_dir
    global_root = build_plan.cache_root / "global"
    global_root.mkdir(parents=True, exist_ok=True)
    return local_root, global_root


@audit(StageType.INIT, substage="init_metadata_resolver_config")
def init_metadata_resolver_config() -> MetadataResolverConfig:
    local_root, global_root = _resolver_roots()
    return MetadataResolverConfig(
        local_cache_root=local_root,
        global_cache_root=global_root,
        # TODO: wire these from configuration
        project_isolation=True,
        clear_on_startup=False)


@audit(StageType.INIT, substage="init_wheel_resolver_config")
def init_wheel_resolver_config() -> WheelResolverConfig:
    local_root, global_root = _resolver_roots()
    return WheelResolverConfig(
        local_cache_root=local_root,
        global_cache_root=global_root,
        project_isolation=True,
        clear_on_startup=False)


@audit(StageType.INIT, substage="init_wheel_resolver_strategies")
def init_wheel_resolver_strategies() -> list[BaseWheelResolutionStrategy]:
    return [
        FilesystemWheelStrategy(
            strategy_config=FilesystemWheelStrategyConfig()),
        HttpWheelStrategy(
            strategy_config=HttpWheelStrategyConfig()),
    ]


@audit(StageType.INIT, substage="init_pep691_resolver")
def init_pep691_resolver() -> MetadataArtifactResolver:
    cfg = init_metadata_resolver_config()
    strategies = [
        Pep691SimpleApiMetadataStrategy(
            strategy_config=Pep691SimpleApiMetadataStrategyConfig()),
    ]
    # destination_dir currently isn’t used by ArtifactResolver resolve-pathing (see note below)
    return MetadataArtifactResolver(
        config=cfg,
        strategies=strategies,
        destination_dir=cfg.local_cache_root / "metadata")


@audit(StageType.INIT, substage="init_pep658_resolver")
def init_pep658_resolver(wheel_resolver: WheelArtifactResolver) -> MetadataArtifactResolver:
    cfg = init_metadata_resolver_config()
    strategies = [
        Pep658SidecarMetadataStrategy(
            strategy_config=Pep658SidecarMetadataStrategyConfig()),
        WheelInspectionMetadataStrategy(
            strategy_config=WheelInspectionMetadataStrategyConfig(),
            wheel_resolver=wheel_resolver)
    ]
    return MetadataArtifactResolver(
        config=cfg,
        strategies=strategies,
        destination_dir=cfg.local_cache_root / "metadata")


@audit(StageType.INIT, substage="init_resolvers")
def init_resolvers() -> tuple[WheelArtifactResolver, MetadataArtifactResolver, MetadataArtifactResolver]:
    wheel = WheelArtifactResolver(
        config=init_wheel_resolver_config(),
        strategies=init_wheel_resolver_strategies(),
        destination_dir=_resolver_roots()[0] / "wheels")
    pep691 = init_pep691_resolver()
    pep658 = init_pep658_resolver(wheel_resolver=wheel)
    return wheel, pep658, pep691


@audit(StageType.INIT)
def init_project(chubproject_path: Path | None = None) -> tuple[Path, ImmediateOutcome]:
    """
    Initializes the project by processing both the build plan and provided project options.
    - it parses CLI
    - it populates build_plan.project and cache
    - it may indicate “exit early” via the returned bool

    This function manages the project initialization process by either directly using
    the `chubproject_path` provided or by parsing command-line arguments to determine
    the project setup. It updates the current build plan with the project configuration,
    analyzes the project for project path dependencies, etc. Then it caches the processed
    project and checks for immediate operations that may be one-shot actions (like info
    requests) and require an early exit.

    Args:
        chubproject_path (Path | None): The path to a specific project, or None to use
            options derived from command-line arguments.

    Returns:
        tuple[Path, ImmediateOutcome]: A tuple containing the path to the cached project
            and an indication if an immediate operation requires the process to exit.
    """
    build_plan = current_packaging_context.get().build_plan
    args = parse_cli()
    if chubproject_path:
        chubproject = process_chubproject(chubproject_path)
    else:
        chubproject = process_options(args)
        if chubproject.project_path is None:
            chubproject.project_path = str(Path.cwd().expanduser().resolve())
    build_plan.project = chubproject
    if build_plan.project_dir is None:
        build_plan.project_dir = Path(chubproject.project_path)
    analyze_project()
    project_cache_path = cache_project(chubproject)
    must_exit = check_immediate_operations(args, chubproject)
    return project_cache_path, must_exit
