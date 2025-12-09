from __future__ import annotations

import json
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from pychub.model.compatibility.artifact_resolution_strategy_config_model import StrategyType, \
    Pep691SimpleApiMetadataStrategyConfig, WheelInspectionMetadataStrategyConfig
from pychub.model.compatibility.compatibility_resolution_model import WheelKey
from pychub.model.compatibility.pep658_metadata_model import Pep658Metadata
from pychub.model.compatibility.pep691_metadata_model import Pep691Metadata
from pychub.package.lifecycle.plan.resolution.artifact_resolution_strategy import ArtifactResolutionStrategy
from pychub.package.lifecycle.plan.resolution.wheels.wheel_resolver import WheelResolver


def _default_request_headers() -> dict[str, str]:
    return {"Accept": "application/vnd.pypi.simple.v1+json"}


@dataclass(slots=True, frozen=True, kw_only=True)
class BaseMetadataStrategy(ArtifactResolutionStrategy, ABC):
    """
    Represents a base metadata strategy for artifact resolution.

    This abstract base class defines the contract for implementing custom metadata
    retrieval strategies for dependency and candidate metadata. It also provides
    some utility methods for conversion and initialization.
    """

    @abstractmethod
    def get_dependency_metadata(self, wheel_key: WheelKey) -> Pep658Metadata | None:
        # Concrete classes must implement this method to return dependency metadata for a given wheel key.
        raise NotImplementedError

    @abstractmethod
    def get_candidate_metadata(self, wheel_key: WheelKey) -> Pep691Metadata | None:
        # Concrete classes must implement this method to return metadata for a given wheel key.
        raise NotImplementedError

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Converts the object to a dictionary representation.

        This method creates a mapping (dictionary) representation of the object
        by calling the superclass implementation of `to_mapping`.

        Args:
            *args: Positional arguments passed to the superclass's `to_mapping` method.
            **kwargs: Keyword arguments passed to the superclass's `to_mapping` method.

        Returns:
            dict[str, Any]: A dictionary representing the object's data.
        """
        return super().to_mapping(*args, **kwargs)


@dataclass(slots=True, frozen=True, kw_only=True)
class Pep691SimpleApiMetadataStrategy(BaseMetadataStrategy):
    """
    Represents a metadata strategy for handling PEP 691 Simple API metadata.

    This class implements a metadata strategy that fetches candidate metadata from
    a PEP 691 compatible Simple API. It uses a base Simple API URL and headers for
    making requests to retrieve metadata for specific Python package candidates.

    Attributes:
        name (str): The name of the metadata strategy. Default is "pep691-simple-api".
        precedence (int): The precedence level of the strategy. Default is 50.
        strategy_type (StrategyType): The type of strategy, classified as candidate
            metadata. This value is defined as a class variable.
        base_simple_url (str): The base URL of the Simple API used for metadata
            retrieval.
        request_headers (dict[str, str]): A dictionary representing the default HTTP
            headers to be sent with each request.
    """
    name: str = field(default="pep691-simple-api")
    precedence: int = field(default=50)
    strategy_type: ClassVar[StrategyType] = StrategyType.CANDIDATE_METADATA
    base_simple_url: str = "https://pypi.org/simple"
    request_headers: dict[str, str] = field(default_factory=_default_request_headers)

    def get_dependency_metadata(self, wheel_key: WheelKey) -> Pep658Metadata | None:
        # This strategy does not provide dependency metadata.
        return None

    def get_candidate_metadata(self, wheel_key: WheelKey) -> Pep691Metadata | None:
        """
        Fetches and parses metadata for a given wheel key from an index URL.

        This method retrieves metadata for a specified wheel key by making a request
        to the corresponding index URL and parsing the response. The metadata is
        returned in the form of a `Pep691Metadata` object if the operation is
        successful, or `None` otherwise.

        Args:
            wheel_key: A `WheelKey` object representing the specific wheel for which
                metadata is requested.

        Returns:
            Pep691Metadata: The parsed metadata object if the metadata is successfully
                retrieved and parsed.
            None: If the metadata retrieval or parsing fails due to a request error,
                invalid JSON response, or any other failure.
        """
        project = wheel_key.name
        index_url = f"{self.base_simple_url.rstrip('/')}/{project}/"
        req = Request(index_url, headers=self.request_headers)

        try:
            with urlopen(req) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError):
            return None

        try:
            raw = json.loads(text or "{}")
        except json.JSONDecodeError:
            return None

        return Pep691Metadata.from_mapping(raw)

    def to_mapping(self, *args, **kwargs):
        """
        Converts the object's data and attributes into a mapping (dictionary format) by
        extending the mapping created by the parent class and adding additional key-value
        pairs that represent specific properties of the object.

        Args:
            *args: Variable length argument list, passed to the parent class's to_mapping method.
            **kwargs: Arbitrary keyword arguments, passed to the parent class's to_mapping
                method.

        Returns:
            dict: A dictionary containing the mapping of the object's data, including the keys
                added specifically in this method.
        """
        mapping = super().to_mapping(*args, **kwargs)
        mapping.update({
            "base_simple_url": self.base_simple_url,
            "request_headers": self.request_headers
        })
        return mapping

    @classmethod
    def _config_from_mapping(
        cls,
        mapping: Mapping[str, Any]) -> Pep691SimpleApiMetadataStrategyConfig:
        return Pep691SimpleApiMetadataStrategyConfig.from_mapping(mapping)


@dataclass(slots=True, frozen=True, kw_only=True)
class WheelInspectionMetadataStrategy(BaseMetadataStrategy):
    """
    Represents a metadata strategy for inspecting wheel files.

    This class provides functionality to handle metadata extraction, processing, and
    conversion related to Python wheel files, specifically focusing on dependency
    metadata. It includes methods to resolve wheels, extract their METADATA content,
    and parse dependency metadata.

    Attributes:
        wheel_resolver (WheelResolver): An instance responsible for resolving wheel
            files based on a given key.
        name (str): The name of the strategy, fixed as "wheel-inspection-metadata".
        precedence (int): The priority of this strategy, set to 90.
        strategy_type (ClassVar[StrategyType]): The type of this strategy, fixed as
            `StrategyType.DEPENDENCY_METADATA`.
    """
    wheel_resolver: WheelResolver
    name: str = "wheel-inspection-metadata"
    precedence: int = 90
    strategy_type: ClassVar[StrategyType] = StrategyType.DEPENDENCY_METADATA

    @staticmethod
    def _extract_metadata_text(wheel_path: Path) -> str | None:
        """
        Extracts and decodes the METADATA file content from a given wheel file.

        This method attempts to locate the METADATA file within the provided wheel file
        and reads its content. If the METADATA file is not present or an error occurs
        during the process, it will return None.

        Args:
            wheel_path (Path): The path to the wheel file.

        Returns:
            str | None: The decoded content of the METADATA file as a string if found,
            otherwise None.
        """
        try:
            with zipfile.ZipFile(wheel_path) as zf:
                meta_name = next(
                    (n for n in zf.namelist() if n.endswith("METADATA")),
                    None,
                )
                if not meta_name:
                    return None

                with zf.open(meta_name) as fh:
                    return fh.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def _resolve_wheel_for_metadata(self, wheel_key: WheelKey) -> Path | None:
        """
        Resolves the wheel file path using the given wheel key.

        This method attempts to retrieve the wheel file path corresponding to
        the provided wheel key using the wheel resolver. If no matching wheel
        is found, it returns None.

        Args:
            wheel_key: The key corresponding to the desired wheel.

        Returns:
            Path | None: The path to the resolved wheel file, or None if no
            matching wheel is found.
        """
        return self.wheel_resolver.get_wheel_by_key(wheel_key)

    def get_candidate_metadata(self, wheel_key: WheelKey) -> Pep691Metadata | None:
        # This strategy does not provide candidate/file metadata.
        return None

    def get_dependency_metadata(self, wheel_key: WheelKey) -> Pep658Metadata | None:
        """
        Fetches and processes dependency metadata for a given wheel key.

        This method retrieves the dependency metadata associated with the provided
        wheel key by resolving the wheel path and extracting its metadata text. The
        metadata is then parsed into a structured format. If the wheel path or metadata
        text cannot be resolved, the method returns None.

        Args:
            wheel_key: The key representing a specific wheel artifact for which
                dependency metadata needs to be fetched.

        Returns:
            Pep658Metadata | None: An instance of Pep658Metadata representing the parsed
            dependency data, or None if the metadata cannot be resolved or extracted.
        """
        wheel_path = self._resolve_wheel_for_metadata(wheel_key)
        if wheel_path is None:
            return None

        meta_text = self._extract_metadata_text(wheel_path)
        if meta_text is None:
            return None

        return Pep658Metadata.from_core_metadata_text(meta_text)

    def to_mapping(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Transforms the current object into a mapping (dictionary) representation.

        This method converts the object into a dictionary, utilizing the `to_mapping`
        function of its superclass and extending it with additional fields relevant
        to the object. The output dictionary contains serialized data, which makes it
        useful for storage, network transmission, or other serialization purposes.

        Args:
            *args: Variable length argument list passed to the superclass `to_mapping`
                method for additional processing.
            **kwargs: Arbitrary keyword arguments passed to the superclass `to_mapping`
                method for further customization or inclusion of parameters.

        Returns:
            dict[str, Any]: A mapping (dictionary) representation of the object,
            including both data from the superclass and additional data specific to
            this class.
        """
        mapping = super().to_mapping(*args, **kwargs)
        mapping["wheel_resolver"] = self.wheel_resolver.to_mapping()
        return mapping

    @classmethod
    def _config_from_mapping(
        cls,
        mapping: Mapping[str, Any]) -> WheelInspectionMetadataStrategyConfig:
        return WheelInspectionMetadataStrategyConfig.from_mapping(mapping)
