"""Structured domain errors shared by services and HTTP adapters."""


class DomainError(ValueError):
    code = "domain_error"
    status_code = 400

    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self):
        payload = {"error": self.message, "code": self.code}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class ValidationError(DomainError):
    code = "validation_error"


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409
