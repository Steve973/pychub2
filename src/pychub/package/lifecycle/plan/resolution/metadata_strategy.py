from __future__ import annotations

import zipfile
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from urllib.parse import urlparse

from packaging.utils import canonicalize_name, parse_wheel_filename

from pychub.helper.strategy_loader import load_strategies_base
from pychub.helper.wheel_tag_utils import choose_wheel_tag
from pychub.package.context_vars import current_packaging_context
from pychub.package.domain.compatibility_model import WheelKey
from pychub.package.lifecycle.plan.resolution.artifact_resolution import WheelArtifactResolver
from pychub.package.lifecycle.plan.resolution.artifact_resolution_strategy import ArtifactResolutionStrategy, \
    download_to_file, write_bytes_atomic
from pychub.package.lifecycle.plan.resolution.resolution_config_model import (
    StrategyType,
    Pep658SidecarMetadataStrategyConfig,
    Pep691SimpleApiMetadataStrategyConfig,
    WheelInspectionMetadataStrategyConfig,
)

ENTRYPOINT_GROUP = "pychub.metadata_resolution_strategies"
PACKAGE_NAME = __name__.rsplit(".", 1)[0]

_METADATA_STRATEGY_REGISTRY: dict[str, tuple[type["BaseMetadataResolutionStrategy"], str]] = {}

TMetaCfg = TypeVar(
    "TMetaCfg",
    Pep658SidecarMetadataStrategyConfig,
    Pep691SimpleApiMetadataStrategyConfig,
    WheelInspectionMetadataStrategyConfig)


def _default_request_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.pypi.simple.v1+json",
        "User-Agent": "pychub/2.x",
    }


def _register_metadata_strategies(strategies: Iterable["BaseMetadataResolutionStrategy"]) -> None:
    for strategy in strategies:
        name = strategy.name
        if not name:
            continue
        cls = type(strategy)
        fqcn = f"{cls.__module__}.{cls.__qualname__}"
        _METADATA_STRATEGY_REGISTRY[name] = (cls, fqcn)


def metadata_strategy_from_mapping(mapping: Mapping[str, Any]) -> "BaseMetadataResolutionStrategy":
    return BaseMetadataResolutionStrategy.from_mapping(mapping)


def load_metadata_resolution_strategies(
        ordered_names: Iterable[str] | None = None,
        precedence_overrides: Mapping[str, int] | None = None) -> list["BaseMetadataResolutionStrategy"]:
    strategies = load_strategies_base(
        base=BaseMetadataResolutionStrategy,
        package_name=PACKAGE_NAME,
        entrypoint_group=ENTRYPOINT_GROUP,
        ordered_names=ordered_names,
        precedence_overrides=precedence_overrides)
    _register_metadata_strategies(strategies)
    return strategies


def _wheel_key_from_uri(uri: str) -> WheelKey | None:
    filename = Path(urlparse(uri).path).name
    if not filename.endswith(".whl"):
        return None
    name, version, _, _ = parse_wheel_filename(filename)
    return WheelKey(name=str(name), version=str(version))


@dataclass(slots=True, frozen=True, kw_only=True)
class BaseMetadataResolutionStrategy(ArtifactResolutionStrategy[TMetaCfg], ABC):
    strategy_type: ClassVar[StrategyType] = StrategyType.UNSPECIFIED

    @property
    def artifact_subdir(self) -> str:
        return "metadata"

    def resolve(
            self,
            dest_dir: Path,
            uri: str | None = None,
            wheel_key: WheelKey | None = None) -> Path | None:
        # Accept either: caller either passes the wheel_key, OR passes the uri,
        # and we derive the wheel_key.
        wk = wheel_key
        if wk is None and uri is not None:
            wk = _wheel_key_from_uri(uri)
        if wk is None:
            return None
        return self.fetch_metadata(dest_dir=dest_dir, wheel_key=wk, uri=uri)

    @abstractmethod
    def fetch_metadata(self, dest_dir: Path, *, wheel_key: WheelKey, uri: str | None = None) -> Path | None:
        raise NotImplementedError


@dataclass(slots=True, frozen=True, kw_only=True)
class Pep691SimpleApiMetadataStrategy(BaseMetadataResolutionStrategy[Pep691SimpleApiMetadataStrategyConfig]):
    strategy_type = StrategyType.CANDIDATE_METADATA

    def fetch_metadata(self, dest_dir: Path, *, wheel_key: WheelKey, uri: str | None = None) -> Path | None:
        # PEP 691 “project index” JSON
        project = canonicalize_name(wheel_key.name)
        index_url = f"{self.strategy_config.base_simple_url.rstrip('/')}/{project}/"
        # filename: stable and deterministic
        dest_path = dest_dir / f"{project}.pep691.json"
        return download_to_file(index_url, dest_path, headers=self.strategy_config.request_headers)

    @classmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> Pep691SimpleApiMetadataStrategyConfig:
        return Pep691SimpleApiMetadataStrategyConfig.from_mapping(mapping)


@dataclass(slots=True, frozen=True, kw_only=True)
class Pep658SidecarMetadataStrategy(BaseMetadataResolutionStrategy[Pep658SidecarMetadataStrategyConfig]):
    strategy_type = StrategyType.DEPENDENCY_METADATA

    def fetch_metadata(self, dest_dir: Path, *, wheel_key: WheelKey, uri: str | None = None) -> Path | None:
        """
        Uses PEP 691 JSON to find the chosen wheel file, then downloads its PEP 658 sidecar metadata.
        """
        project = canonicalize_name(wheel_key.name)
        index_url = f"{self.strategy_config.base_simple_url.rstrip('/')}/{project}/"

        # 1) download index JSON (or better: reuse pep691 cache later; you already know)
        index_path = dest_dir / f"{project}.pep691.json"
        index_file = download_to_file(index_url, index_path, headers=self.strategy_config.request_headers)
        if index_file is None:
            return None

        # 2) parse JSON -> find the best wheel file for wheel_key and read its dist-info-metadata url
        # NOTE: this parsing depends on your Pep691Metadata model; use it instead of ad hoc parsing.
        from pychub.package.domain.compatibility_model import Pep691Metadata  # local import avoids cycles
        candidate_meta = Pep691Metadata.from_file(path=index_file, fmt="json")

        best = min(
            (
                (choose_wheel_tag(f.filename, wheel_key.name, wheel_key.version), f)
                for f in candidate_meta.files
                if (not f.yanked and f.filename.endswith(".whl"))
            ),
            default=None,
            key=lambda t: (t[0], t[1].filename))
        if best is None:
            return None

        file_meta = best[1]

        # 3) Check if PEP 658 metadata is available
        # If core_metadata is False, the sidecar doesn't exist.
        # If the url is None, the wheel file is missing.
        if not file_meta.core_metadata or not file_meta.url:
            return None

        sidecar_url = f"{file_meta.url}.metadata"
        sidecar_name = f"{file_meta.filename}.metadata"
        dest_path = dest_dir / sidecar_name
        return download_to_file(sidecar_url, dest_path, headers=self.strategy_config.request_headers)

    @classmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> Pep658SidecarMetadataStrategyConfig:
        return Pep658SidecarMetadataStrategyConfig.from_mapping(mapping)


@dataclass(slots=True, frozen=True, kw_only=True)
class WheelInspectionMetadataStrategy(BaseMetadataResolutionStrategy[WheelInspectionMetadataStrategyConfig]):
    """
    Fallback strategy: resolve dependency metadata by downloading a wheel and extracting the
    dist-info METADATA file from inside it.

    This exists specifically as the "last resort" when sidecar metadata (PEP 658) is not
    available, and you still need dependency metadata to build a tree.
    """

    strategy_config: WheelInspectionMetadataStrategyConfig
    wheel_resolver: "WheelArtifactResolver"
    index_base_url: str = "https://pypi.org/simple"
    index_request_headers: dict[str, str] = field(default_factory=_default_request_headers)
    strategy_type: ClassVar[StrategyType] = StrategyType.DEPENDENCY_METADATA

    @staticmethod
    def _extract_metadata_bytes(wheel_path: Path) -> bytes | None:
        try:
            with zipfile.ZipFile(wheel_path) as zf:
                meta_name = next((n for n in zf.namelist() if n.endswith("METADATA")), None)
                if not meta_name:
                    return None
                with zf.open(meta_name) as fh:
                    return fh.read()
        except Exception:
            return None

    def fetch_metadata(self, dest_dir: Path, *, wheel_key: WheelKey, uri: str | None = None) -> Path | None:
        if uri is None:
            pep691_resolver = current_packaging_context.get().pep691_resolver
            metadata = pep691_resolver.resolve(wheel_key=wheel_key)
            if metadata is None:
                return None
            uri = metadata.origin_uri

        if uri is None:
            return None

        wheel_result = self.wheel_resolver.resolve(wheel_key=wheel_key, uri=uri)
        wheel_path = wheel_result.path if wheel_result is not None else None
        if wheel_path is None:
            return None

        meta_bytes = self._extract_metadata_bytes(wheel_path)
        if meta_bytes is None:
            return None

        try:
            chosen_tag_str = choose_wheel_tag(
                filename=wheel_path.name,
                name=wheel_key.name,
                version=wheel_key.version)
        except ValueError:
            chosen_tag_str = "unknown"

        dest_path = dest_dir / f"{canonicalize_name(wheel_key.name)}-{wheel_key.version}-{chosen_tag_str}.metadata"
        return write_bytes_atomic(dest_path, meta_bytes)

    @classmethod
    def _config_from_mapping(cls, mapping: Mapping[str, Any]) -> WheelInspectionMetadataStrategyConfig:
        return WheelInspectionMetadataStrategyConfig.from_mapping(mapping)

    @classmethod
    def _construct_from_parts(
            cls,
            config: WheelInspectionMetadataStrategyConfig,
            **deps: Any) -> "WheelInspectionMetadataStrategy":
        return cls(
            strategy_config=config,
            wheel_resolver=deps["wheel_resolver"],
            index_base_url=deps.get("index_base_url", "https://pypi.org/simple"),
            index_request_headers=deps.get("index_request_headers", _default_request_headers()))
