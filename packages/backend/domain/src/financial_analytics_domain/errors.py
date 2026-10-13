"""Domain failures that do not depend on transport or persistence."""


class DomainError(ValueError):
    """Base class for invalid domain input or state."""


class FloatNotAllowedError(DomainError):
    """Raised when an inexact binary floating-point value crosses a boundary."""


class CurrencyMismatchError(DomainError):
    """Raised when values from different currencies are combined."""


class PrecisionError(DomainError):
    """Raised when money has more precision than its currency permits."""


class UnbalancedTransactionError(DomainError):
    """Raised when postings do not sum to zero."""


class OwnershipError(DomainError):
    """Raised when entities from different owners are combined."""
