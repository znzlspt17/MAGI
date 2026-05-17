"""Domain errors raised by MAGI Spec Engine."""


class MagiError(Exception):
    """Base class for actionable MAGI errors."""


class MissingCredentialError(MagiError):
    """Raised when a selected provider requires unavailable credentials."""


class ArtifactError(MagiError):
    """Raised when artifact persistence fails."""


class InvalidStateError(MagiError):
    """Raised when a saved run state is malformed or not ready."""


class PermissionDeniedError(MagiError):
    """Raised when an agent tries to use a skill outside its permission set."""


class CommandExecutionError(MagiError):
    """Raised when guarded command execution is blocked or fails policy."""
