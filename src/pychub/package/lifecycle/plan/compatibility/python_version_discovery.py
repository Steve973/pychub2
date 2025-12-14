from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping

import httpx

from pychub.helper.strategy_loader import load_strategies_base
from pychub.package.domain.compatibility_model import PythonVersionsSpec

_HTTP_TIMEOUT_SECONDS = 10.0
ENTRYPOINT_GROUP = "pychub.model.compatibility.version_discovery"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]


def _list_all_available_python_versions(discovery: PythonVersionDiscovery | None = None) -> list[str]:
    """
    Attempts to discover all available Python versions using the provided discovery
    mechanism or by using a set of predefined discovery strategies.

    This function iterates through a list of discovery strategies and attempts to
    fetch the list of available Python versions. If a specific discovery mechanism
    is provided, it is used exclusively; otherwise, the default set of strategies
    is loaded and used. The function stops and returns the discovered versions as
    soon as a successful strategy produces non-empty results. If no versions can
    be found and at least one strategy raises an error, the last encountered error
    is raised. Otherwise, a generic runtime error is raised if no strategies can
    discover a version.

    Args:
        discovery (PythonVersionDiscovery | None): A specific discovery mechanism to
            be used. If set to None, default discovery strategies are used.

    Returns:
        list[str]: A list of discovered Python version strings.

    Raises:
        RuntimeError: Raised if no Python versions can be found. If any discovery
            strategies encountered errors during execution, the last error
            encountered will be chained with this exception.
    """
    strategies: list[PythonVersionDiscovery] = (
        [discovery]
        if discovery is not None
        else load_python_version_discovery_strategies())

    versions: list[str] | None = None
    last_error: Exception | None = None

    for strat in strategies:
        try:
            versions = strat.list_versions()
        except Exception as exc:
            last_error = exc

        if versions:
            return versions

    if last_error is not None:
        raise RuntimeError(
            "No available Python versions found; last discovery error was"
        ) from last_error

    raise RuntimeError("No available Python versions found")


def list_available_python_versions_for_spec(
    py_ver_spec: PythonVersionsSpec,
    discovery: PythonVersionDiscovery | None = None) -> list[str]:
    """
    Lists all available Python versions that match the given specification.

    This function discovers all Python versions using the provided discovery mechanism
    (if any) and filters them based on the given Python version specification. If no
    versions match the specification, a `RuntimeError` is raised.

    Args:
        py_ver_spec: A PythonVersionsSpec instance used to filter available versions.
        discovery: An optional PythonVersionDiscovery instance for custom discovery
            logic. If None, a default discovery mechanism is used.

    Returns:
        A list of strings representing the Python versions that satisfy the provided
        specification.

    Raises:
        RuntimeError: If no Python versions match the given specification.
    """
    versions = _list_all_available_python_versions(discovery)
    filtered = py_ver_spec.filter_versions(versions)
    if filtered:
        return filtered
    raise RuntimeError("No available Python versions found for the given spec")


def load_python_version_discovery_strategies(
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list[PythonVersionDiscovery]:
    """
    Loads and resolves Python version discovery strategies, considering the specified
    ordering and precedence overrides if provided.

    This function dynamically loads and prepares strategies for discovering Python
    versions. The strategies can be explicitly ordered or reprioritized based on the
    parameters supplied. It leverages a base loading mechanism to retrieve and process
    registered strategies.

    Args:
        ordered_names (Iterable[str] | None): A list of strategy names in the desired
            order. When provided, this ensures the specified order is applied during
            strategy resolution.
        precedence_overrides (Mapping[str, int] | None): A mapping of strategy names
            to precedence values. Strategies with specified precedence overrides will
            follow this configuration.

    Returns:
        list[PythonVersionDiscovery]: A list of resolved Python version discovery
        strategies based on the provided ordering and precedence configurations.
    """
    return load_strategies_base(
        base=PythonVersionDiscovery,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)


class PythonVersionDiscovery(ABC):
    """
    Represents an abstract base class for Python version discovery.

    This class provides an interface for discovering Python versions through
    subclasses. Subclasses must implement the `list_versions` method to provide
    specific functionality for identifying available Python versions. This class
    also includes attributes to define a name and precedence for the version
    discovery mechanism.

    Attributes:
        name (str): The descriptive name for the discovery mechanism. Defaults
            to "unspecified".
        precedence (int): The precedence level for this discovery mechanism.
            Lower numbers indicate higher priority. Defaults to 100.
    """
    name: str = "unspecified"
    precedence: int = 100

    @abstractmethod
    def list_versions(self) -> list[str]:
        raise NotImplementedError("This method must be implemented by subclasses.")


class EndOfLifePythonVersionDiscovery(PythonVersionDiscovery):
    name = "endoflife.date"
    precedence = 30

    def list_versions(self) -> list[str]:
        """
        Fetches and filters the available Python versions based on the specification provided.

        This function retrieves a list of Python version cycles from an external API and then
        filters these versions according to the provided `PythonVersionsSpec` object. The
        result is a list of compatible Python versions matching the specification criteria.

        Returns:
            list[str]: A list of strings representing the Python versions that match the
                provided specification.

        Raises:
            httpx.HTTPStatusError: If the API response contains a non-successful status code.
            httpx.RequestError: If an error occurs while making the API request.
        """
        resp = httpx.get("https://endoflife.date/api/python.json", timeout=_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        return [str(entry["cycle"]) for entry in data]


class PythonDownloadsVersionDiscovery(PythonVersionDiscovery):
    name = "python.org"
    precedence = 40

    def list_versions(self) -> list[str]:
        """
        Lists all Python versions available on the Python official downloads page.

        This method fetches the content of the Python downloads page and extracts the
        versions of Python available for download using regular expressions.

        Returns:
            list[str]: A list of Python version strings available for download.

        Raises:
            httpx.RequestError: If there is a problem with the network request.
            httpx.HTTPStatusError: If the HTTP response indicates an unsuccessful status code.
        """
        resp = httpx.get("https://www.python.org/downloads/", timeout=_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        versions = re.findall(r"Python\s+(\d+\.\d+)", resp.text)
        return sorted(set(versions))


class EnumeratedDefaultVersionDiscovery(PythonVersionDiscovery):
    name = "default.enumerated"
    precedence = 1000
    _default_versions: list[str] = [
        "3.14",
        "3.13",
        "3.12",
        "3.11",
        "3.10"
    ]

    def __init__(self, python_versions: list[str] | None = None):
        self.python_versions = list(python_versions or self._default_versions)

    def list_versions(self) -> list[str]:
        """
        Lists all available Python versions.

        Retrieves a list of Python versions currently available.

        Returns:
            list[str]: A list of available Python version strings.
        """
        return self.python_versions
