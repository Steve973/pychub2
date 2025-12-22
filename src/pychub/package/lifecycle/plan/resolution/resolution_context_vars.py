from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pychub.package.lifecycle.plan.resolution.resolution_context_model import ResolutionContext

current_resolution_context: ContextVar["ResolutionContext"] = ContextVar("current_resolution_context")
