from __future__ import annotations

from collections.abc import Mapping, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from packaging.tags import Tag, parse_tag
from packaging.version import Version

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin

_NONE = "__none__"


def tag_from_str(s: str) -> Tag:
    """
    Parse a single tag string (e.g. "py3-none-any") into a Tag.
    """
    parsed = parse_tag(s)
    if len(parsed) != 1:
        raise ValueError(f"Expected single tag, got {len(parsed)}: {s}")
    return next(iter(parsed))


def tags_to_str(tags: frozenset[Tag]) -> str:
    """
    # CHANGE: Deterministic encoding for a set of tags in context_key.
    Uses comma-separated, lexicographically sorted tag strings.
    """
    return ",".join(sorted(str(t) for t in tags))


def tags_from_str(raw: str) -> frozenset[Tag]:
    """
    # CHANGE: Inverse of tags_to_str().
    Accepts comma-separated tag strings.
    """
    raw = raw.strip()
    if not raw:
        return frozenset()

    out: set[Tag] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out |= set(parse_tag(part))
    return frozenset(out)


class ResolutionStatusType(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ReasonType(str, Enum):
    NO_CANDIDATES = "NO_CANDIDATES"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    NO_COMPATIBLE_WHEEL = "NO_COMPATIBLE_WHEEL"
    MARKER_PRUNED_ALL = "MARKER_PRUNED_ALL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=False, kw_only=True, slots=True)
class ResolutionContextResult(MultiformatModelMixin):
    status: ResolutionStatusType
    reason_kind: ReasonType
    detail: str
    additional_info: dict = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_kind": self.reason_kind.value,
            "detail": self.detail,
            "additional_info": self.additional_info
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolutionContextResult:
        return cls(
            status=ResolutionStatusType(mapping["status"]),
            reason_kind=ReasonType(mapping["reason_kind"]),
            detail=mapping["detail"],
            additional_info=mapping.get("additional_info", {}))


@dataclass(frozen=True, kw_only=True, slots=True)
class ResolutionContext(MultiformatModelMixin):
    """
    Represents the context of a single resolution run for dependency tree evaluation.

    This class is used to capture all the environmental and compatibility parameters
    necessary for evaluating the dependency tree of a chub file. Resolution contexts
    are critical in determining which compatibility tag triples the chub can support
    in different scenarios, such as variations in Python implementations, versions, and
    system architectures.

    Pychub performs full dependency tree resolution for multiple contexts to determine
    which compatibility tag triples the chub will support.

    Attributes:
        arch (str): The architecture of the system (e.g., x86_64, arm64).
        os_family (str): The operating system family (e.g., Windows, Linux, macOS).
        python_implementation (str): The Python implementation being used
            (e.g., CPython, PyPy).
        python_version (Version): The version of Python being used in this context.
        tags (frozenset[Tag]): The compatibility tag triples associated with this context.
    """
    arch: str
    os_family: str
    python_implementation: str
    python_version: Version
    tags: frozenset[Tag] = field(default_factory=frozenset)
    result: ResolutionContextResult = field(
        default_factory=lambda: ResolutionContextResult(
            status=ResolutionStatusType.PENDING,
            reason_kind=ReasonType.UNKNOWN,
            detail=""))

    _SEP: ClassVar[str] = "|"

    _KEY_FIELDS: ClassVar[tuple[tuple[str, Callable[[Any], str], Callable[[str], Any]], ...]] = (
        ("arch", str, str),
        ("os_family", str, str),
        ("python_implementation", str, str),
        ("python_version", lambda v: str(v), Version),
        ("tags", tags_to_str, tags_from_str))

    @property
    def context_key(self) -> str:
        parts: list[str] = []
        for name, enc, _dec in self._KEY_FIELDS:
            parts.append(enc(getattr(self, name)))
        return self._SEP.join(parts)

    @classmethod
    def from_context_key(cls, context_key: str) -> ResolutionContext:
        parts = context_key.split(cls._SEP)
        if len(parts) != len(cls._KEY_FIELDS):
            raise ValueError(f"Bad context_id: expected {len(cls._KEY_FIELDS)} parts, got {len(parts)}: {context_key}")

        kwargs: dict[str, Any] = {}
        for (name, _enc, dec), raw in zip(cls._KEY_FIELDS, parts, strict=True):
            kwargs[name] = dec(raw)
        return cls(**kwargs)

    def to_mapping(self) -> dict[str, Any]:
        tags = [{
            "interpreter": t.interpreter,
            "abi": t.abi,
            "platform": t.platform
        } for t in sorted(self.tags, key=str)]
        return {
            "arch": self.arch,
            "os_family": self.os_family,
            "python_implementation": self.python_implementation,
            "python_version": str(self.python_version),
            "tags": tags,
            "result": self.result.to_mapping()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolutionContext:
        tags_list = mapping["tags"]
        tags = [Tag(t["interpreter"], t["abi"], t["platform"]) for t in tags_list]
        return cls(
            arch=mapping["arch"],
            os_family=mapping["os_family"],
            python_implementation=mapping["python_implementation"],
            python_version=Version(mapping["python_version"]),
            tags=frozenset(tags),
            result=ResolutionContextResult.from_mapping(mapping["result"]))
