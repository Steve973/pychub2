from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Any

from appdirs import user_cache_dir

from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.model.packaging.includes_model import Includes
from pychub.model.packaging.scripts_model import Scripts
from pychub.model.packaging.wheels_model import WheelCollection
from pychub.model.project.chubproject_model import ChubProject
from pychub.package.constants import CHUB_INCLUDES_DIR, CHUB_SCRIPTS_DIR, RUNTIME_DIR, CHUB_BUILD_DIR, CHUB_LIBS_DIR, \
    CHUBCONFIG_FILENAME, CHUB_WHEELS_DIR
from .build_event import BuildEvent
from ..compatibility.compatibility_spec_model import CompatibilitySpec
from ...helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from ...package.lifecycle.plan.resolution.metadata.metadata_resolver import MetadataResolver
from ...package.lifecycle.plan.resolution.wheels.wheel_resolver import WheelResolver


@dataclass(slots=True, frozen=False, kw_only=True)
class BuildPlan(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    """
    Represents a build plan for a Chub project, which organizes various configurations,
    metadata, and resources required during the build process.

    The BuildPlan class serves as a central configuration and tracking structure for
    a Chub project, detailing resources like file inclusions, scripts, metadata, and
    compatibility requirements. It also provides mechanisms for serialization and
    deserialization from common formats such as mappings and YAML.

    Attributes:
        audit_log (list[BuildEvent]): A log of events recorded during the build process.
        cache_root (Path): Path to the top-level staging/cache directory.
        compatibility_spec (CompatibilitySpec): Specification for evaluating wheel.
        created_at (datetime): Timestamp indicating when the build plan was created.
        include_files (Includes): Files included as part of the build staging area.
        install_scripts (Scripts): Installation scripts to be staged as part of the build.
        metadata (dict[str, Any]): Additional metadata associated with the build plan.
        metadata_resolver (MetadataResolver): Configured metadata resolver for resolving
            project dependencies and metadata.
        path_dep_wheel_locations (set[Path]): Locations of wheel files derived from
            project path dependency analysis.
        project (ChubProject): The Chub project definition associated with the build
            plan.
        project_dir (Path): Path to the directory containing the project being built.
        project_hash (str): Unique identifier or hash of the Chub project directory,
            used for staging organization.
        pychub_version (str): The version of Pychub used to create this build plan.
        resolved_python_versions (list[str]): Resolved Python versions for the project.
        wheel_resolver (WheelResolver): Configured resolver for managing wheel files.
        wheels (WheelCollection): Collection of wheels to be included in the build.
    """

    # The audit log of events that occurred during the build process
    audit_log: list[BuildEvent] = field(default_factory=list)
    # Path to the top-level pychub staging/cache directory
    cache_root: Path = field(default_factory=Path)
    # The compatibility evaluator used to evaluate the compatibility of wheels based on the compatibility spec
    compatibility_spec: CompatibilitySpec | None = None
    # When the build plan was created
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    # Included files to be staged in the build
    include_files: Includes = field(default_factory=Includes)
    # Scripts to be staged in the build
    install_scripts: Scripts = field(default_factory=Scripts)
    # Additional metadata for the build
    metadata: dict[str, Any] = field(default_factory=dict)
    # The configured metadata resolver
    metadata_resolver: MetadataResolver | None = None
    # Wheel files from project path dependency analysis
    path_dep_wheel_locations: set[Path] = field(default_factory=set)
    # The ChubProject definition
    project: ChubProject = field(default_factory=ChubProject)
    # Path to the wheel project directory
    project_dir: Path = field(default_factory=Path)
    # Becomes a directory under the staging directory for this chub project
    project_hash: str = field(default="")
    # The version of pychub that created this plan
    pychub_version: str = field(default_factory=lambda: get_version("pychub"))
    # Resolved Python versions for the project
    resolved_python_versions: list[str] = field(default_factory=list)
    # The configured wheel resolver
    wheel_resolver: WheelResolver | None = None
    # Wheels to be staged in the build
    wheels: WheelCollection = field(default_factory=WheelCollection)

    # ------------------------------------------------------------------ #
    # Construction helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> BuildPlan:
        """
        Creates a BuildPlan object from a mapping dictionary containing configuration
        details. The method validates and extracts required and optional fields
        from the mapping and constructs an instance of BuildPlan using the extracted
        values. A nested "project" mapping is mandatory; otherwise, the method raises
        a ValueError.

        Args:
            mapping (Mapping[str, Any]): A dictionary-like object containing the
                configuration details for building a BuildPlan. Must include a "project"
                key with nested mapping.
            **_ (Any): Additional arguments not used in the method execution.

        Returns:
            BuildPlan: A constructed instance of the BuildPlan class.

        Raises:
            ValueError: If the "project" key is missing from the mapping or its
                content is None.
        """
        project = ChubProject.from_mapping(mapping["project"]) if "project" in mapping else None
        if project is None:
            raise ValueError("BuildPlan requires a nested 'project' mapping")

        return BuildPlan(
            audit_log=list(mapping.get("audit_log", [])),
            cache_root=Path(mapping.get("cache_root", str(user_cache_dir("pychub")))),
            compatibility_spec=CompatibilitySpec.from_mapping(mapping.get("compatibility_spec", {})),
            created_at=datetime.datetime.fromisoformat(
                mapping.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())),
            include_files=Includes.from_mapping(mapping.get("include_files", {})),
            install_scripts=Scripts.from_mapping(mapping.get("install_scripts", {})),
            metadata=dict(mapping.get("metadata") or {}),
            metadata_resolver=MetadataResolver.from_mapping(mapping.get("metadata_resolver", {})),
            path_dep_wheel_locations=set(mapping.get("path_dep_wheel_locations", [])),
            project=project,
            project_dir=Path(mapping.get("project_dir") or "."),
            project_hash=mapping.get("project_hash", ""),
            pychub_version=mapping.get("pychub_version", get_version("pychub")),
            resolved_python_versions=mapping.get("resolved_python_versions", []),
            wheel_resolver=WheelResolver.from_mapping(mapping.get("wheel_resolver", {})),
            wheels=WheelCollection.from_mapping(mapping.get("wheels", [])))

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_mapping(self, include_derived: bool = False) -> dict[str, Any]:
        """
        Converts the internal state of the object to a dictionary.

        This function generates a mapping representation of the object's core attributes
        and, optionally, derived attributes if the `include_derived` parameter is set
        to True. Core attributes always include information like audit logs, project
        data, metadata, timestamps, and compatibility specifications. Derived attributes
        represent additional data related to staged and bundled directories, and other
        project-specific runtime configurations.

        Args:
            include_derived (bool): Determines whether to include derived attributes in
                the returned dictionary. Defaults to False.

        Returns:
            dict[str, Any]: A dictionary containing the core attributes and, if specified,
            the derived attributes.
        """
        mapping = {
            "audit_log": [e.to_mapping() for e in self.audit_log],
            "cache_root": str(self.cache_root),
            "compatibility_spec": self.compatibility_spec.to_mapping() if self.compatibility_spec is not None else {},
            "created_at": str(self.created_at.isoformat()),
            "include_files": self.include_files.to_mapping(),
            "install_scripts": self.install_scripts.to_mapping(),
            "metadata": dict(self.metadata),
            "metadata_resolver": self.metadata_resolver.to_mapping() if self.metadata_resolver is not None else {},
            "path_dep_wheel_locations": list(sorted(self.path_dep_wheel_locations)),
            "project": self.project.to_mapping(),
            "project_dir": str(self.project_dir),
            "project_hash": self.project_hash,
            "pychub_version": self.pychub_version,
            "resolved_python_versions": self.resolved_python_versions,
            "wheel_resolver": self.wheel_resolver.to_mapping() if self.wheel_resolver is not None else {},
            "wheels": self.wheels.to_mapping(),
        }
        derived = {
            "build_dir": str(self.build_dir),
            "bundled_chubconfig_path": str(self.bundled_chubconfig_path),
            "bundled_includes_dir": str(self.bundled_includes_dir),
            "bundled_libs_dir": str(self.bundled_libs_dir),
            "bundled_runtime_dir": str(self.bundled_runtime_dir),
            "bundled_scripts_dir": str(self.bundled_scripts_dir),
            "project_staging_dir": str(self.project_staging_dir),
            "staged_includes_dir": str(self.staged_includes_dir),
            "staged_runtime_dir": str(self.staged_runtime_dir),
            "staged_scripts_dir": str(self.staged_scripts_dir),
            "staged_wheels_dir": str(self.staged_wheels_dir),
        }
        if include_derived:
            mapping.update(derived)
        return mapping

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def validate(self) -> None:
        """
        Validates the attributes of the instance to ensure they match the expected
        types and constraints. If any attribute fails validation, an appropriate
        ValueError is raised.

        Raises:
            ValueError: If any of the attributes does not match its expected type.
            ValueError: If any entry in the 'audit_log' is not an instance of BuildEvent.
        """
        validations = {
            'audit_log': (list, 'audit_log list[BuildEvent]'),
            'cache_root': (Path, 'cache_root Path'),
            'compatibility_spec': (CompatibilitySpec, 'compatibility_spec CompatibilitySpec'),
            'created_at': (datetime.datetime, 'created_at datetime'),
            'include_files': (Includes, 'include_files Includes'),
            'install_scripts': (Scripts, 'install_scripts Scripts'),
            'metadata': (dict, 'metadata dict'),
            'metadata_resolver': (MetadataResolver, 'metadata_resolver MetadataResolver'),
            'path_dep_wheel_locations': (set, 'path_dep_wheel_locations set[Path]'),
            'project': (ChubProject, 'ChubProject'),
            'project_dir': (Path, 'project_dir Path'),
            'project_hash': (str, 'project_hash str'),
            'pychub_version': (str, 'pychub_version str'),
            'resolved_python_versions': (list, 'resolved_python_versions list[str]'),
            'wheel_resolver': (WheelResolver, 'wheel_resolver WheelResolver'),
            'wheels': (WheelCollection, 'wheels WheelCollection'),
        }

        for attr_name, (expected_type, type_desc) in validations.items():
            value = getattr(self, attr_name)
            if not isinstance(value, expected_type):
                raise ValueError(f"expected {type_desc}, got {type(value)}")

        # Special validation for audit_log contents
        if not all(isinstance(i, BuildEvent) for i in self.audit_log):
            raise ValueError("each entry in 'audit_log' must be a BuildEvent")

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def project_staging_dir(self) -> Path:
        return self.cache_root / self.project_hash

    @property
    def staged_wheels_dir(self) -> Path:
        """Where wheels are first staged."""
        return self.project_staging_dir / CHUB_WHEELS_DIR

    @property
    def staged_includes_dir(self) -> Path:
        """Where includes are initially copied for staging."""
        return self.project_staging_dir / CHUB_INCLUDES_DIR

    @property
    def staged_scripts_dir(self) -> Path:
        """Where scripts are staged."""
        return self.project_staging_dir / CHUB_SCRIPTS_DIR

    @property
    def staged_runtime_dir(self) -> Path:
        """Where runtime files are staged."""
        return self.project_staging_dir / RUNTIME_DIR

    @property
    def build_dir(self) -> Path:
        """Root of the final build structure (from which .chub is assembled)."""
        return self.project_staging_dir / CHUB_BUILD_DIR

    @property
    def bundled_libs_dir(self) -> Path:
        """libs/ in the final build dir"""
        return self.build_dir / CHUB_LIBS_DIR

    @property
    def bundled_includes_dir(self) -> Path:
        return self.build_dir / CHUB_INCLUDES_DIR

    @property
    def bundled_scripts_dir(self) -> Path:
        return self.build_dir / CHUB_SCRIPTS_DIR

    @property
    def bundled_runtime_dir(self) -> Path:
        return self.build_dir / RUNTIME_DIR

    @property
    def bundled_chubconfig_path(self) -> Path:
        return self.build_dir / CHUBCONFIG_FILENAME

    @property
    def meta_json(self) -> dict[str, Any]:
        return {
            "pychub_version": self.pychub_version,
            "created_at": self.created_at.isoformat(),
            "project_hash": self.project_hash,
        }
