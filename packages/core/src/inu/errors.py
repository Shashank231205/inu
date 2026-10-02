"""Error taxonomy.

Every error INU raises on purpose is an `InuError`. The class carries a stable
machine-readable `code`, a `category` for dashboards and alerting, and whether a retry
could succeed. Logs and spans record these fields, so failures can be grouped without
parsing message text.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import ClassVar


class ErrorCategory(StrEnum):
    CONFIG = "config"
    DEVICE = "device"
    VALIDATION = "validation"
    PROVIDER = "provider"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class InuError(Exception):
    code: ClassVar[str] = "internal.unexpected"
    category: ClassVar[ErrorCategory] = ErrorCategory.INTERNAL
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, context: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        # Context is logged and attached to spans: never put secrets in it.
        self.context: Mapping[str, object] = dict(context or {})

    def attributes(self) -> dict[str, str | bool]:
        """Flat attributes for logs and spans."""
        return {
            "error.code": self.code,
            "error.category": self.category.value,
            "error.retryable": self.retryable,
        }
