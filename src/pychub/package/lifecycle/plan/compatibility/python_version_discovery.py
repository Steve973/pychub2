from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import cast

import httpx

from pychub.helper.strategy_loader import load_strategies_base
from pychub.package.domain.compatibility_model import PythonVersionsSpec

_HTTP_TIMEOUT_SECONDS = 10.0
ENTRYPOINT_GROUP = "pychub.model.compatibility.version_discovery"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]


def list_available_python_versions_for_spec(
    py_ver_spec: PythonVersionsSpec,
    discovery: PythonVersionDiscovery | None = None) -> list[str]:
    """
    Lists available Python versions matching the given specification.

    This function attempts to discover Python versions that match a specified
    Python version constraint using one or more available discovery strategies.
    If a specific strategy is provided, it will use that strategy; otherwise,
    it will load and iterate through the default discovery strategies. The function
    returns a filtered list of Python versions that satisfy the given constraints.
    If no versions match or if all strategies fail, an exception is raised.

    Args:
        py_ver_spec: A PythonVersionsSpec object that defines the specification or
            version constraint against which Python versions will be filtered.
        discovery: Optional; A specific PythonVersionDiscovery strategy to use for
            discovering Python versions. If not provided, the function uses
            default discovery strategies.

    Returns:
        list[str]: A list of Python versions as strings that match the given
        specification, or an empty list if no matches are found.

    Raises:
        RuntimeError: If no Python versions matching the given specification are
        found, either due to discovery failures or because none of the discovered
        versions meet the criteria.
    """
    if discovery is not None:
        discovery_strategies: list[PythonVersionDiscovery] = [discovery]
    else:
        discovery_strategies = load_python_version_discovery_strategies()

    last_error: Exception | None = None

    for strat in discovery_strategies:
        try:
            versions = strat.list_versions()
        except Exception as exc:
            # Probably httpx errors, JSON parse, etc. Try the next strategy.
            last_error = exc
            continue

        if not versions:
            continue

        filtered = py_ver_spec.filter_versions(versions)
        if filtered:
            return filtered

    # If we get here, either no strategy worked, or none produced any versions
    # within the spec band.
    if last_error is not None:
        raise RuntimeError(
            "No available Python versions found; last discovery error was"
        ) from last_error

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
    raw = load_strategies_base(
        base=PythonVersionDiscovery,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
    return cast(list[PythonVersionDiscovery], raw)


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
