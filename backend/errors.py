"""Application error types. Each one maps to an HTTP status in app.py."""

from .calculations import ValidationError  # noqa: F401  (400 Bad Request)


class NotFoundError(LookupError):
    """404 Not Found."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class ConflictError(RuntimeError):
    """409 Conflict - the request clashes with the current state."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message
