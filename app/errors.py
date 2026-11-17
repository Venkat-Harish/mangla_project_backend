"""Errors the services raise; app/main.py turns them into JSON responses with the request ID."""


class NotFoundError(Exception):
    """A row the request names does not exist (HTTP 404)."""

    def __init__(self, what: str, value: object) -> None:
        self.detail = f"{what} {value} not found"
        super().__init__(self.detail)


class InvalidInputError(Exception):
    """The body is well-formed but asks for something not allowed (HTTP 422)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
