from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        code: str = "internal_error",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, status_code=404, code="not_found")


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409, code="conflict")


class InputError(AppError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 422,
        code: str = "invalid_input",
    ) -> None:
        super().__init__(message, status_code=status_code, code=code)


class ModelOutputError(AppError):
    def __init__(self, message: str = "The model returned an invalid response") -> None:
        super().__init__(message, status_code=502, code="model_output_invalid")


class UpstreamServiceError(AppError):
    def __init__(
        self,
        message: str = "The model service is temporarily unavailable",
        *,
        status_code: int = 503,
        code: str = "model_service_unavailable",
    ) -> None:
        super().__init__(message, status_code=status_code, code=code)
