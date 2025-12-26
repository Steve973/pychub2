from __future__ import annotations

import datetime
import functools
import uuid
from collections.abc import Mapping, Callable
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ParamSpec, TypeVar

from typing_extensions import Self

from pychub.helper.multiformat_model_mixin import MultiformatModelMixin
from pychub.package.domain.buildplan_model import BuildPlan
from pychub.package.packaging_context_vars import current_packaging_context

P = ParamSpec("P")
R = TypeVar("R")


# --------------------------------------------------------------------------- #
# Typed + runtime-safe event type definition
# --------------------------------------------------------------------------- #

class StageType(str, Enum):
    """
    Enumeration of various stages in a process.

    Represents the different phases or steps in an orchestrated process. These
    stages can be used to define workflows, organize tasks, or track the progress
    of a process.

    Attributes:
        LIFECYCLE (str): The overall orchestration stage, which covers the full
            lifecycle from start to completion.
        INIT (str): The initialization stage, including CLI parsing, environment
            checks, and caching.
        PLAN (str): The planning stage, which involves dependency resolution,
            wheel analysis, and SBOM (Software Bill of Materials) generation.
        EXECUTE (str): The execution stage, where the actual build or other
            defined actions based on the plan are carried out.
        CLEANUP (str): The cleanup stage, used for optional teardown or post-build
            validation activities.
    """
    LIFECYCLE = "LIFECYCLE"  # the overall orchestration: start → complete
    INIT = "INIT"  # CLI parsing, environment checks, caching
    PLAN = "PLAN"  # dependency resolution, wheel analysis, SBOM generation
    EXECUTE = "EXECUTE"  # build or other actions based on the plan
    CLEANUP = "CLEANUP"  # optional teardown or post-build validation


class LevelType(str, Enum):
    """
    Represents types of logging levels as an enumeration.

    This class is an enumeration that defines specific string constants for use
    as logging levels. It includes different levels typically used in logging
    systems to categorize the importance or severity of a log message.

    Attributes:
        DEBUG (str): Represents a debug level log, used for detailed debugging
            information.
        INFO (str): Represents an info level log, used for informational messages
            that highlight the progress of the application at a coarse-grained
            level.
        WARN (str): Represents a warning level log, indicating a possible issue or
            unexpected situation that does not prevent the application from
            functioning.
        ERROR (str): Represents an error level log, used for error events that
            might affect the continuation of the application or some part of it.
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class EventType(str, Enum):
    """
    Represents various predefined event types for categorizing and identifying actions or states in a process.

    This enumeration class is used to define a set of predefined constants that represent
    specific types of events or states that can be encountered during the execution
    of a workflow, process, or system operation. Each event type provides a semantic
    categorization that can be used for logging, monitoring, or handling specific
    conditions in a structured manner.

    Attributes:
        ABORTED (str): An action was conditionally aborted.
        ACTION (str): A meaningful step was taken, such as a copy, build, or inject operation.
        ANNOTATION (str): An annotation-related event.
        CHECKPOINT (str): A mid-stage milestone or marker within a process.
        COMPLETE (str): Indicates successful completion of a stage, task, or operation.
        DECISION (str): Indicates the path taken after a conditional logic branch.
        DEFERRED (str): Marks an action that was intentionally delayed.
        EXCEPTION (str): Indicates an event related to an exception.
        FAIL (str): Marks a stage or action that failed irrecoverably.
        INPUT (str): Denotes an external input received or utilized by the system.
        OUTPUT (str): Represents an artifact, such as a file or metadata, produced by the system.
        RESOLVE (str): Indicates that an item such as a dependency or strategy was resolved.
        SKIP (str): Represents an intentionally bypassed stage or step.
        START (str): Marks the beginning of a stage or substage in a process.
        VALIDATION (str): Represents an event related to a validation check.
    """
    ABORTED = "ABORTED"  # An action was conditionally aborted
    ACTION = "ACTION"  # Meaningful step taken (copy, build, inject)
    ANNOTATION = "ANNOTATION"
    CHECKPOINT = "CHECKPOINT"  # Mid-stage milestone or marker
    COMPLETE = "COMPLETE"  # Successfully finished
    DECISION = "DECISION"  # Conditional logic branch taken
    DEFERRED = "DEFERRED"  # Action intentionally delayed
    DISCOVER = "DISCOVER"  # Discovery action invoked
    EXCEPTION = "EXCEPTION"  # Indicates exception-related event
    FAIL = "FAIL"  # Stage failed, unrecoverable
    INPUT = "INPUT"  # External input received or used
    OUTPUT = "OUTPUT"  # Artifact produced (file, archive, metadata)
    RESOLVE = "RESOLVE"  # Item was resolved (e.g., dependency, strategy)
    SKIP = "SKIP"  # Intentionally bypassed
    START = "START"  # Beginning of a stage or substage
    VALIDATION = "VALIDATION"  # Validation event


class AnnotationType(str, Enum):
    """
    Represents types of annotations with specific functionalities.

    This enumeration defines different types of annotations that can be used
    to describe relationships or provide additional context to events or
    data points. Each enumeration value represents a distinct annotation type
    with a specific purpose.

    Attributes:
        AMENDS (str): Replaces or corrects a prior event.
        COMMENT (str): Human or system note, no functional change.
        RELATES_TO (str): Links to another event semantically.
        SUPPLEMENTS (str): Adds context or extra data.
    """
    AMENDS = "AMENDS"  # Replaces or corrects a prior event
    COMMENT = "COMMENT"  # Human or system note, no functional change
    RELATES_TO = "RELATES_TO"  # Links to another event semantically
    SUPPLEMENTS = "SUPPLEMENTS"  # Adds context or extra data


def audit(stage: StageType, substage: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator that logs audit events for a specified stage during the execution of a function.

    Logs START, COMPLETE, and EXCEPTION events into an active BuildPlan's audit log. If no
    active BuildPlan exists in the context, it raises a RuntimeError. All events are associated
    with the given stage and optional substage, along with messages in the event of errors.

    Args:
        stage (StageType): The main stage to log the audit events.
        substage (str | None): Optional substage to include in the logged events.

    Returns:
        Callable[[Callable[P, R]], Callable[P, R]]: A decorator that applies audit logging to the
        wrapped function.

    Raises:
        RuntimeError: If no active BuildPlan exists in the current context.
    """
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            plan: BuildPlan = current_packaging_context.get().build_plan
            if plan is None:
                raise RuntimeError("No active BuildPlan in context for @audit-decorated function")

            plan.audit_log.append(
                BuildEvent.make(
                    stage,
                    EventType.START,
                    substage=substage))

            try:
                result = fn(*args, **kwargs)
                plan.audit_log.append(
                    BuildEvent.make(
                        stage,
                        EventType.COMPLETE,
                        substage=substage))
                return result
            except Exception as e:
                plan.audit_log.append(
                    BuildEvent.make(
                        stage,
                        EventType.EXCEPTION,
                        LevelType.ERROR,
                        substage=substage,
                        message=str(e)))
                raise

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass(slots=True, frozen=True)
class BuildEvent(MultiformatModelMixin):
    """
    Represents a build event occurring during a build process.

    This class encapsulates event details such as the type, stage, level, timing, and optional data
    associated with specific events during the build lifecycle. The `BuildEvent` class ensures
    logical consistency of event attributes and provides methods for serialization and deserialization.

    Attributes:
        annotation_type (AnnotationType | None): Type of annotation associated with the event.
            This is only applicable for events of type `EventType.ANNOTATION`.
        event_id (str): Unique identifier for the event. Defaults to a new UUID string.
        event_type (EventType): Type of the event (e.g., ACTION, ANNOTATION). Defaults to `EventType.ACTION`.
        level (LevelType): Severity level of the event (e.g., INFO, WARNING, ERROR). Defaults to `LevelType.INFO`.
        message (str | None): Optional message providing descriptive details about the event.
        payload (Mapping[str, Any] | None): Optional dictionary containing additional event-related data.
        stage (StageType | None): Stage of the build process where the event occurred.
        substage (str | None): Optional substage identifier within the primary build stage.
        timestamp (datetime.datetime): The exact time at which the event occurred. Defaults to the current UTC time.
    """
    annotation_type: AnnotationType | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.ACTION
    level: LevelType = LevelType.INFO
    message: str | None = field(default=None)
    payload: Mapping[str, Any] | None = field(default=None)
    stage: StageType | None = None
    substage: str | None = field(default=None)
    timestamp: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def __post_init__(self):
        """
        Ensures that the attributes of the BuildEvent object meet the required type and
        value constraints. Specifically, it validates that the `stage`, `event_type`,
        and `level` attributes are of the appropriate types and checks their consistency
        with the `annotation_type` when applicable.

        Raises:
            TypeError: If `stage` is not a StageType, `event_type` is not an EventType,
                `level` is not a LevelType, or `annotation_type` is not an AnnotationType
                when it is set.
            ValueError: If `annotation_type` is provided but `event_type` is not
                EventType.ANNOTATION, or if `event_type` is EventType.ANNOTATION but
                `annotation_type` is not set.
        """
        if not isinstance(self.stage, StageType):
            raise TypeError("BuildEvent.stage must be a StageType")
        if not isinstance(self.event_type, EventType):
            raise TypeError("BuildEvent.event_type must be an EventType")
        if not isinstance(self.level, LevelType):
            raise TypeError("BuildEvent.level must be a LevelType")
        if self.annotation_type is not None:
            if not isinstance(self.annotation_type, AnnotationType):
                raise TypeError("BuildEvent.annotation_type must be an AnnotationType")
            if self.event_type != EventType.ANNOTATION:
                raise ValueError("BuildEvent.annotation_type can only be set for ANNOTATION events")
        if self.event_type == EventType.ANNOTATION:
            if self.annotation_type is None:
                raise ValueError("BuildEvent.annotation_type must be set for ANNOTATION events")

    def to_mapping(self, *args, **kwargs) -> dict[str, Any]:
        """
        Converts the attributes of the object into a dictionary representation.

        The method creates a mapping where each attribute of the object is transformed
        into a dictionary key-value pair. It provides conditional handling for
        attributes that may be optional or require specific formatting, such as
        enums or datetime objects.

        Returns:
            dict[str, Any]: A dictionary representation of the object's attributes.
        """
        return {
            "annotation_type": self.annotation_type.value if self.annotation_type else None,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "level": self.level.value,
            "message": self.message or "",
            "payload": self.payload or {},
            "stage": self.stage.value if self.stage else None,
            "substage": self.substage or "",
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def make(
            cls,
            stage: StageType,
            event_type: EventType,
            level: LevelType = LevelType.INFO,
            annotation_type: AnnotationType | None = None,
            *,
            substage: str | None = None,
            message: str | None = None,
            payload: dict[str, Any] | None = None) -> BuildEvent:
        """
        Creates an instance of the BuildEvent class with the provided attributes.

        Args:
            stage: Stage of the build process.
            event_type: Type of the event occurring within the build process.
            level: Severity level of the event. Defaults to LevelType.INFO.
            annotation_type: Type of annotation associated with the event. Defaults to None.
            substage: Optional substage within the build process. Defaults to None.
            message: Optional descriptive message for the event. Defaults to None.
            payload: Optional dictionary containing additional event details. Defaults to None.

        Returns:
            BuildEvent: A new instance of the BuildEvent class with the provided values.
        """
        frozen_payload = MappingProxyType(payload or {})
        return cls(
            stage=stage,
            substage=substage,
            event_type=event_type,
            annotation_type=annotation_type,
            level=level,
            message=message,
            payload=frozen_payload)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any], **_: Any) -> Self:
        """
        Creates a BuildEvent instance from a mapping object containing the relevant keys and values.

        Args:
            mapping (Mapping[str, Any]): A dictionary-like object containing the data for the BuildEvent.
                Supported keys include:
                    - "annotation_type": A string representation of an AnnotationType or None.
                    - "event_type": A string representation of an EventType. Defaults to EventType.ACTION.
                    - "level": A string representation of a LevelType. Defaults to LevelType.INFO.
                    - "stage": A string representation of a StageType. Defaults to StageType.LIFECYCLE.
                    - "event_id": An identifier string for the event. Defaults to a newly generated UUID.
                    - "message": A string representing the message associated with the event.
                    - "payload": Additional data payload associated with the event.
                    - "substage": A string identifier for a substage associated with the event.
                    - "timestamp": A string ISO 8601 formatted datetime representing when the event occurred.
                      Defaults to the current UTC time.

            **_ (Any): Additional unused keyword arguments.

        Returns:
            BuildEvent: An instance of the BuildEvent class created based on the provided mapping.

        """
        annotation_type = AnnotationType(mapping.get("annotation_type")) if mapping.get("annotation_type") else None
        event_type = EventType(mapping.get("event_type", EventType.ACTION.value))
        level = LevelType(mapping.get("level", LevelType.INFO.value))
        stage = StageType(mapping.get("stage", StageType.LIFECYCLE.value))

        return cls(
            annotation_type=annotation_type,
            event_id=mapping.get("event_id", str(uuid.uuid4())),
            event_type=event_type,
            level=level,
            message=mapping.get("message"),
            payload=mapping.get("payload"),
            stage=stage,
            substage=mapping.get("substage"),
            timestamp=datetime.datetime.fromisoformat(
                mapping.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())))
