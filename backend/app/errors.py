"""Shared application exception; this module has no HTTP dependency."""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
