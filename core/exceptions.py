"""
Core exceptions for the Multi-Agent AI Platform.
"""

class MultiAgentError(Exception):
    """Base exception for all platform errors."""
    pass

class UnauthorizedAccessError(MultiAgentError):
    """Raised when an agent attempts an operation it does not have access permissions for."""
    pass

class RegistryError(MultiAgentError):
    """Raised for registry integrity or operational errors."""
    pass

class RegistryNotFoundError(RegistryError):
    """Raised when an entry is not found in the registry."""
    pass

class RegistryDuplicateError(RegistryError):
    """Raised when attempting to create a duplicate registry entry without update intent."""
    pass

class ValidationError(MultiAgentError):
    """Raised when proposal or input validation fails."""
    pass
