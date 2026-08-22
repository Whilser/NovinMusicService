class CatalogError(Exception):
    code = "catalog_error"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationError(CatalogError):
    code = "validation_error"


class NotFoundError(CatalogError):
    code = "not_found"


class ConflictError(CatalogError):
    code = "conflict"
