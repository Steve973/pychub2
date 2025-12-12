from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from pathlib import Path

from pychub.helper.strategy_loader import load_strategies_base

ENTRYPOINT_GROUP = "pychub.project_path_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

class ProjectPathStrategy(ABC):
    """
    Provides an abstract base class for implementing project path handling strategies.

    This class serves as a blueprint for defining behavior related to handling data
    and extracting paths based on specific criteria. Subclasses should implement the
    abstract methods to provide concrete functionality for assessing whether the strategy
    is applicable to particular data and extracting relevant paths accordingly.

    Attributes:
        name (str): The name of the strategy, identifying its purpose or role.
        precedence (int): A ranking used to determine the priority of the strategy. Lower
            values represent higher precedence.
    """

    name: str
    precedence: int = 100  # lower value = higher precedence

    @staticmethod
    @abstractmethod
    def can_handle(data: dict) -> bool:
        """
        Determines if a specific handler can process the given data.

        This abstract method should be implemented by subclasses to define the
        logic for determining whether the subclass can handle the provided data.

        Args:
            data (dict): The data to be analyzed by the handler.

        Returns:
            bool: True if the handler can process the given data, False otherwise.
        """
        ...

    @staticmethod
    @abstractmethod
    def extract_paths(data: dict, project_root: Path) -> list[Path]:
        """
        Extracts and returns a list of paths from the provided data structure.

        The method is designed to analyze the provided data dictionary and extract
        relevant paths relative to the project root. The output is a list of Path
        objects corresponding to the determined file or directory locations.

        Args:
            data (dict): A dictionary structure containing information from which
                paths are to be extracted. The actual keys and content depend on the
                specific implementation.
            project_root (Path): The root directory of the project. This path serves
                as the base for resolving relative paths from the data dictionary.

        Returns:
            list[Path]: A list of Path objects representing resolved paths extracted
            from the input data.

        """
        ...



class DefaultProjectPathStrategy(ProjectPathStrategy):
    """
    Provides a default strategy for determining project paths.

    This class implements a default mechanism for extracting project paths based
    on provided project data and a project root. It uses a specific precedence
    and always claims to handle the data passed to it.

    Attributes:
        name (str): The name of the strategy.
        precedence (int): The precedence level of the strategy. A lower value
            indicates higher precedence.
    """

    name = "default"
    precedence = 1000  # lower value = higher precedence

    @staticmethod
    def can_handle(data: dict) -> bool:
        """
        Determines if the given data dictionary can be handled.

        This method evaluates whether the provided data meets the criteria to be
        handled by the current implementation. It returns a boolean indicating
        if the data can be processed.

        Args:
            data (dict): The input data to be evaluated.

        Returns:
            bool: True if the given data can be handled, False otherwise.
        """
        return True

    @staticmethod
    def extract_paths(data: dict, project_root: Path) -> list[Path]:
        """
        Extracts and resolves file paths from a nested dependency structure.

        This method scans the provided dictionary for keys related to
        dependencies and extracts paths from these sections by resolving
        them relative to the provided 'project_root'. The method handles
        various structures of dependency definitions, including dictionaries
        and lists of dependencies, and ensures all collected paths are resolved
        as fully qualified paths.

        Args:
            data (dict): The input dictionary containing dependency definitions.
            project_root (Path): The root path used to resolve relative paths
                in the dependency definitions.

        Returns:
            list[Path]: A list of fully resolved paths extracted from the
            dependency definitions.
        """
        out = []

        def _extract_from_deps(deps_section):
            if isinstance(deps_section, dict):
                for lib_spec in deps_section.values():
                    if isinstance(lib_spec, dict) and "path" in lib_spec:
                        out.append((project_root / lib_spec["path"]).resolve())
                    elif isinstance(lib_spec, list):
                        for item in lib_spec:
                            if isinstance(item, dict) and "path" in item:
                                out.append((project_root / item["path"]).resolve())
            elif isinstance(deps_section, list):
                for item in deps_section:
                    if isinstance(item, dict) and "path" in item:
                        out.append((project_root / item["path"]).resolve())

        def _scan_all(obj):
            if not isinstance(obj, dict):
                return
            for key, value in obj.items():
                k = key.lower()
                if "dependenc" in k or k.endswith("deps"):
                    _extract_from_deps(value)
                    # Do NOT recurse into value (don't go inside dependencies)
                elif isinstance(value, dict):
                    _scan_all(value)

        _scan_all(data)
        return out





class HatchProjectPathStrategy(ProjectPathStrategy):
    """
    Defines a strategy for handling project configurations specifically related to projects
    that use the Hatch tool. This strategy evaluates and processes configuration data
    for such projects.

    Attributes:
        name (str): The name of the strategy, used to identify it as "hatch".
        precedence (int): A numeric value indicating the priority of this strategy. Lower
            values signify higher precedence when multiple strategies are considered.
    """

    name = "hatch"
    precedence = 60  # lower value = higher precedence

    @staticmethod
    def can_handle(data: dict) -> bool:
        """
        Determines if the provided data dictionary can be handled by verifying the existence
        of a specific section (`hatch`) in the `[tool]` section and a `dependencies` section in
        the `[project]` section.

        Args:
            data (dict): A dictionary containing project configuration data.

        Returns:
            bool: True if the data contains a `hatch` section in `tool` and `dependencies`
            in `project`, otherwise False.
        """
        # Hatch projects must have a [tool.hatch] section, but deps live in [project]
        tool = data.get("tool", {}) or {}
        project = data.get("project", {}) or {}
        return "hatch" in tool and "dependencies" in project

    @staticmethod
    def extract_paths(data: dict, project_root: Path) -> list[Path]:
        """
        Extract paths from project dependencies specified in the given data.

        This method processes the dependencies of a project defined within the `data`
        dictionary. Each dependency may include a "path" key specifying a relative
        path. The method resolves these paths against the given `project_root` and
        returns a list of absolute `Path` objects.

        Args:
            data (dict): The dictionary containing project data. It is expected to
                have a "project" key with a "dependencies" subkey, which is a list
                of dependency objects.
            project_root (Path): The root path of the project, used as the base
                directory to resolve relative paths of dependencies.

        Returns:
            list[Path]: A list of resolved absolute `Path` objects representing the
            paths of the project dependencies.
        """
        project = data.get("project", {}) or {}
        project_deps = project.get("dependencies", []) or []
        out: list[Path] = []
        for dep in project_deps:
            if isinstance(dep, dict) and "path" in dep:
                out.append((project_root / dep["path"]).resolve())
        return out



class PdmProjectPathStrategy(ProjectPathStrategy):
    """
    Represents a strategy for extracting project paths specific to PDM (Python Dependency Manager).

    This class provides methods to determine if PDM dependencies are present in a given project
    configuration and extract dependency paths relative to the project root. The strategies
    defined here are specific to the structure used by PDM in the "tool.pdm" section of project
    metadata.

    Attributes:
        name (str): The name of the strategy, set to "pdm".
        precedence (int): Determines the priority of the strategy. Lower values mean higher
            precedence, with the default value set to 70.
    """

    name = "pdm"
    precedence = 70  # lower value = higher precedence

    @staticmethod
    def can_handle(data: dict) -> bool:
        """
        Determines if the given input data can be handled based on the presence
        of "dependencies" within the "pdm" section of the "tool" dictionary.

        Args:
            data (dict): The input data dictionary to be evaluated.

        Returns:
            bool: True if the input data contains "dependencies" under the "pdm"
                section of the "tool" dictionary, False otherwise.
        """
        tool = data.get("tool", {}) or {}
        tool_pdm = tool.get("pdm", {}) or {}
        return "dependencies" in tool_pdm

    @staticmethod
    def extract_paths(data: dict, project_root: Path) -> list[Path]:
        """
        Extracts dependency paths specified in a dictionary structure.

        This function parses a nested dictionary structure to extract paths to
        dependencies defined under "tool.pdm.dependencies". When a dependency is a
        dictionary and contains a "path" key, the path is resolved relative to the
        `project_root` and added to the output list.

        Args:
            data (dict): A dictionary containing project configuration, potentially
                including dependency information under the keys "tool.pdm.dependencies".
            project_root (Path): The root directory of the project as a Path object,
                used to resolve relative paths to absolute paths.

        Returns:
            list[Path]: A list of absolute paths corresponding to the dependencies
            defined with paths in the input `data`.

        """
        tool = data.get("tool", {}) or {}
        tool_pdm = tool.get("pdm", {}) or {}
        tool_pdm_dependencies = tool_pdm.get("dependencies", {}) or {}
        out: list[Path] = []
        for _, val in tool_pdm_dependencies.items():
            if isinstance(val, dict) and "path" in val:
                out.append((project_root / val["path"]).resolve())
        return out




class PoetryProjectPathStrategy(ProjectPathStrategy):
    """
    Represents a strategy for handling project paths specific to the poetry configuration.

    This class specializes in determining whether a given project configuration
    is compatible with Poetry and extracting paths defined under the Poetry configuration.
    It provides methods to validate and extract dependencies paths relative to the project root.

    Attributes:
        name (str): The name of the strategy.
        precedence (int): The precedence level of this strategy, with lower values indicating
            higher priority.
    """

    name = "poetry"
    precedence = 50  # lower value = higher precedence

    @staticmethod
    def can_handle(data: dict) -> bool:
        """
        Determines if the given data dictionary contains "poetry" as part of its configuration.

        The method checks if the "poetry" key is present within the "tool" key of the provided
        dictionary and returns a boolean indicating whether it can handle the provided data.

        Args:
            data (dict): A dictionary to inspect, expected to have a "tool" key containing
                nested configuration data.

        Returns:
            bool: True if the "poetry" key exists in the "tool" section of the dictionary,
            otherwise False.
        """
        return "poetry" in (data.get("tool", {}) or {})

    @staticmethod
    def extract_paths(data: dict, project_root: Path) -> list[Path]:
        """
        Extracts and resolves paths for dependencies defined in a given configuration.

        This method extracts the file paths of dependencies from a specific configuration
        (`tool.poetry.dependencies`) in the provided data dictionary. It then resolves these
        paths based on the project root. This is primarily intended to handle dependencies
        with a "path" attribute.

        Args:
            data (dict): A dictionary containing configuration data, typically including
                `tool.poetry.dependencies` where dependencies and their paths are defined.
            project_root (Path): The root directory of the project, used to resolve relative
                dependency paths.

        Returns:
            list[Path]: A list of resolved file paths for dependencies that include a "path"
                attribute in the configuration.
        """
        tool = data.get("tool", {}) or {}
        tool_poetry = tool.get("poetry", {}) or {}
        tool_poetry_dependencies = tool_poetry.get("dependencies", {}) or {}
        return [
            (project_root / val["path"]).resolve()
            for _, val in tool_poetry_dependencies.items()
            if isinstance(val, dict) and "path" in val
        ]




def load_strategies(
    ordered_names: Iterable[str] | None = None,
    precedence_overrides: Mapping[str, int] | None = None) -> list[ProjectPathStrategy]:
    """
    Loads and returns a list of `ProjectPathStrategy` objects based on specified configurations.
    This function uses a base loading mechanism to gather and organize implementations
    of the `ProjectPathStrategy` interface from an entry point group. The strategies can be
    optionally ordered and prioritized according to the provided arguments.

    Args:
        ordered_names (Iterable[str] | None): An optional iterable of strategy names specifying the
            order in which strategies should be loaded. If provided, the strategies will be ordered
            according to this list, with any additional ones appended later in an undefined order.
        precedence_overrides (Mapping[str, int] | None): An optional mapping of strategy names to
            their respective precedence values. Lower precedence values define a higher priority,
            directly influencing the sorting of strategies.

    Returns:
        list[ProjectPathStrategy]: A list of `ProjectPathStrategy` instances, sorted based on the
            provided `ordered_names` and `precedence_overrides`.
    """
    return load_strategies_base(
        base=ProjectPathStrategy,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
