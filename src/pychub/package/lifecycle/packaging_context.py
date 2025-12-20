from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pychub.package.domain.buildplan_model import BuildPlan

if TYPE_CHECKING:
    from pychub.package.lifecycle.plan.resolution.artifact_resolution import MetadataArtifactResolver
    from pychub.package.lifecycle.plan.resolution.artifact_resolution import WheelArtifactResolver


@dataclass(kw_only=True)
class PackagingContext:
    build_plan: BuildPlan

    # Resolvers
    pep658_resolver: "MetadataArtifactResolver"
    pep691_resolver: "MetadataArtifactResolver"
    wheel_resolver: "WheelArtifactResolver"
