from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pychub.package.domain.buildplan_model import BuildPlan

if TYPE_CHECKING:
    from pychub.package.lifecycle.plan.resolution.metadata.metadata_resolver import MetadataResolver
    from pychub.package.lifecycle.plan.resolution.wheels.wheel_resolver import WheelResolver


@dataclass(kw_only=True)
class PackagingContext:
    build_plan: BuildPlan
    metadata_resolver: "MetadataResolver"
    wheel_resolver: "WheelResolver"