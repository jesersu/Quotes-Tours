"""Domain-level errors."""


class DomainError(Exception):
    """Base class for all domain errors."""


class CurrencyMismatchError(DomainError):
    """Raised when amounts in different currencies are combined."""


class InvalidPricingInput(DomainError):
    """Raised when a pricing input violates a domain rule."""
