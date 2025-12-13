from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

from packaging.tags import Tag
from packaging.utils import parse_wheel_filename

from pychub.helper.multiformat_deserializable_mixin import MultiformatDeserializableMixin
from pychub.helper.multiformat_serializable_mixin import MultiformatSerializableMixin
from pychub.package.context_vars import current_packaging_context
from pychub.package.domain.compatibility_model import WheelKey, Pep691Metadata, Pep691FileMetadata
from pychub.package.lifecycle.plan.resolution.caching_model import WheelCacheModel, create_key, WheelCacheIndexModel
from pychub.package.lifecycle.plan.resolution.metadata.metadata_resolver import MetadataResolver
from pychub.package.lifecycle.plan.resolution.resolution_config_model import WheelResolverConfig
from pychub.package.lifecycle.plan.resolution.wheels.wheel_strategy import \
    WheelResolutionStrategy

WHEEL_SUBDIR = "wheels"
INDEX_FILENAME = ".wheel_index.json"
_WHEEL_RE = re.compile(
    r"""
    ^(?P<name>.+?)              # distribution name (greedy-but-minimal)
    -(?P<version>[^-]+)         # version (no '-' inside)
    (?:-(?P<build>[^-]+))?      # optional build tag
    -(?P<py>[^-]+)              # python tag
    -(?P<abi>[^-]+)             # abi tag
    -(?P<plat>[^-]+)            # platform tag
    \.whl$                      # .whl suffix
    """,
    re.VERBOSE)


def _extract_filename_from_uri(uri: str) -> str:
    parsed = urlparse(uri)
    return Path(parsed.path).name


def _extract_wheel_filename_parts(filename: str, py_major: int = 3) -> tuple[str, str, str]:
    """
    Parse a wheel filename into (name, version, compatibility_tag_triple).

    Example:
      'mypkg-1.2.3-cp311-cp311-manylinux_2_17_x86_64.whl'
      -> ('mypkg', '1.2.3', 'cp311-cp311-manylinux_2_17_x86_64')
    """
    name, version, _, tagset = parse_wheel_filename(filename)
    parsed_tag = Tag("py3", "none", "any")
    if parsed_tag not in tagset:
        cp_candidates = [t for t in tagset if t.interpreter.startswith(f"cp{py_major}")]
        py_candidates = [t for t in tagset if t.interpreter.startswith(f"py{py_major}")]
        if cp_candidates:
            parsed_tag = sorted(cp_candidates, key=str)[0]
        elif py_candidates:
            parsed_tag = sorted(py_candidates, key=str)[0]
        else:
            parsed_tag = sorted(tagset, key=str)[0]
    return name, str(version), str(parsed_tag)


def _compute_hash_and_size(path: Path) -> tuple[str, str, int]:
    """
    Compute SHA-256 hash and size in bytes.
    Returns (hash_algorithm, hex_digest, size_bytes).
    """
    algorithm = "sha256"
    h = sha256()
    size = 0

    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)

    return algorithm, h.hexdigest(), size


def _resolve_uri_for_wheel_key(
        wheel_key: WheelKey,
        metadata_resolver: MetadataResolver) -> str | None:
    """
    Use candidate (PEP 691) metadata to turn a wheel identity into a download URI.
    """
    # 1. Ask metadata resolver for 691 candidates for this project+version.
    candidate_meta: Pep691Metadata | None = metadata_resolver.resolve_pep691_metadata(wheel_key)
    if candidate_meta is None:
        return None

    # 2. Filter files by compat tag — derived from *their* filenames.
    matching_files: list[Pep691FileMetadata] = []
    for file_meta in candidate_meta.files:
        name, version, file_compat = _extract_wheel_filename_parts(file_meta.filename)
        # name/version should match the wheel_key; compat must match the requested triple.
        if name != wheel_key.name or version != wheel_key.version:
            continue
        if file_meta.yanked:
            continue  # skip yanked files unless you deliberately want them
        matching_files.append(file_meta)

    if not matching_files:
        return None

    # 3. Pick one deterministically (for now, just the first or lexicographically smallest).
    # You could later add smarter rules: prefer core-metadata-inlined, prefer certain hashes, etc.
    chosen = sorted(matching_files, key=lambda f: f.filename)[0]

    # 4. That’s your URI.
    return chosen.url


class WheelResolver(MultiformatSerializableMixin, MultiformatDeserializableMixin):
    _config: WheelResolverConfig
    _strategies: Sequence[WheelResolutionStrategy]
    _index: WheelCacheModel
    _cache_dir: Path
    _index_path: Path

    def __init__(self, config: WheelResolverConfig, strategies: Sequence[WheelResolutionStrategy]):
        self._config = config
        self._strategies = strategies
        self._index = WheelCacheModel()
        self._cache_dir = config.local_cache_root \
            if config.project_isolation \
            else config.global_cache_root
        self._index_path = self._cache_dir / WHEEL_SUBDIR / INDEX_FILENAME
        if self._index_path.exists():
            loaded = WheelCacheModel.from_file(self._index_path, "json")
            self._index.update(loaded.as_dict())

    def get_wheel_by_key(self, wheel_key: WheelKey, *, force_refresh: bool = False) -> Path | None:
        """
        Retrieves a wheel's file path corresponding to a given wheel key.

        This method takes a wheel key and optionally forces a refresh to retrieve the
        wheel file path. Resolving from wheel key to URI is managed internally. If the
        URI cannot be resolved from the wheel key, the method will return None.

        Args:
            wheel_key: Key object representing the wheel to be resolved.
            force_refresh: Boolean flag indicating whether to bypass cached values
                and force retrieving the latest available data.

        Returns:
            Path | None: Path to the wheel file if successfully resolved; otherwise,
            None.
        """
        metadata_resolver = current_packaging_context.get().metadata_resolver
        if metadata_resolver is None:
            raise RuntimeError("MetadataResolver not initialized")
        uri = _resolve_uri_for_wheel_key(wheel_key, metadata_resolver)
        if uri is None:
            return None
        return self.get_wheel_by_uri(uri, force_refresh=force_refresh)

    def get_wheel_by_uri(self, uri: str, *, force_refresh: bool = False) -> Path | None:
        """
        Fetches a wheel file by its URI and manages its cache.

        This method retrieves a wheel file by its URI, verifying its cache status and deciding whether to
        refresh it. It uses predefined resolution strategies to fetch the wheel if not already available
        or if force refresh is enabled. The method also validates cache integrity by computing and storing
        hash values, metadata, and timestamps. Returns the path to the fetched wheel or None if all
        strategies fail or the URI cannot be processed.

        Args:
            uri (str): The URI of the wheel file to fetch.
            force_refresh (bool, optional): If True, forces a refresh of the cached wheel file by
                re-fetching it, even if it already exists in the cache. Defaults to False.

        Returns:
            Path | None: The local path to the fetched wheel file if successful, or None if no wheel
            could be fetched.
        """
        filename = _extract_filename_from_uri(uri)
        if not filename:
            # No filename -> nothing sensible to do.
            return None

        # Derive identity from the filename.
        name, version, compatibility_tag = _extract_wheel_filename_parts(filename)
        wheel_key: WheelKey = WheelKey(name, version)
        cache_key = create_key(wheel_key, compatibility_tag)

        # 1. Cache lookup
        if not force_refresh:
            existing = self._index.get(cache_key)
            if existing is not None and existing.path.exists():
                return existing.path

        # 2. Decide where this wheel should live in the cache.
        wheels_dir = self._cache_dir / WHEEL_SUBDIR
        wheels_dir.mkdir(parents=True, exist_ok=True)

        dest_path = wheels_dir / filename

        # If we're force-refreshing, you *may* want to delete any existing file first.
        # Not required, but avoids keeping stale bytes around.
        if force_refresh and dest_path.exists():
            dest_path.unlink()

        # 3. Ask strategies to fetch the wheel.
        for strategy in self._strategies:
            wheel_path = strategy.fetch_wheel(uri, dest_path)
            if wheel_path is None:
                continue

            # 4. Compute integrity info.
            hash_algorithm, hash_value, size_bytes = _compute_hash_and_size(wheel_path)

            # 5. Build index entry and update cache.
            index_entry = WheelCacheIndexModel(
                key=cache_key,
                path=wheel_path,
                origin_uri=uri,
                wheel_key=wheel_key,
                compatibility_tag=compatibility_tag,
                hash_algorithm=hash_algorithm,
                hash=hash_value,
                size_bytes=size_bytes,
                timestamp=datetime.now().replace(microsecond=0))
            self._index.put(index_entry)

            return wheel_path

        # All strategies failed.
        return None

    def persist_cache_index(self):
        self._index.to_file(path=self._index_path, fmt="json")

    def to_mapping(self, *args, **kwargs):
        return {
            "config": self._config.to_mapping()
        }
