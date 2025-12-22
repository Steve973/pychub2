from __future__ import annotations

from collections.abc import Mapping, Callable
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, ClassVar

from packaging.tags import Tag, parse_tag
from packaging.version import Version

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin

_NONE = "__none__"


def tag_from_str(s: str) -> Tag:
    parsed_tags = parse_tag(tag=s)
    if len(parsed_tags) != 1:
        raise ValueError(f"Expected 1 tag, got {len(parsed_tags)}: {s}")
    return next(iter(parsed_tags))


class ResolutionStatusType(str, Enum):
    PENDING = auto()
    SUCCESS = auto()
    FAILED = auto()


class ReasonType(str, Enum):
    NO_CANDIDATES = auto()
    VERSION_CONFLICT = auto()
    NO_COMPATIBLE_WHEEL = auto()
    MARKER_PRUNED_ALL = auto()
    UNKNOWN = auto()


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
        tag (Tag): The compatibility tag triple associated with this context.
    """
    arch: str
    os_family: str
    python_implementation: str
    python_version: Version
    tag: Tag = field(default_factory=lambda: Tag(_NONE, _NONE, _NONE))
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
        ("tag", lambda t: str(t), tag_from_str),
    )

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
        return {
            "arch": self.arch,
            "os_family": self.os_family,
            "python_implementation": self.python_implementation,
            "python_version": str(self.python_version),
            "tag": {
                "interpreter": self.tag.interpreter,
                "abi": self.tag.abi,
                "platform": self.tag.platform
            },
            "result": self.result.to_mapping()
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> ResolutionContext:
        tag_map = mapping["tag"]
        return cls(
            arch=mapping["arch"],
            os_family=mapping["os_family"],
            python_implementation=mapping["python_implementation"],
            python_version=Version(mapping["python_version"]),
            tag=Tag(tag_map["interpreter"], tag_map["abi"], tag_map["platform"]),
            result=ResolutionContextResult.from_mapping(mapping["result"]))
