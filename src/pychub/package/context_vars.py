from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pychub.package.lifecycle.packaging_context import PackagingContext

current_packaging_context: ContextVar["PackagingContext"] = ContextVar(
    "current_packaging_context")
