from contextvars import ContextVar

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pychub.model.build_lifecycle.buildplan_model import BuildPlan

# Hold the active BuildPlan during the build lifecycle
current_build_plan: ContextVar[BuildPlan] = ContextVar("current_build_plan")
